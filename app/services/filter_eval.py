"""Server-side evaluation of the Filters page rule tree.

This is a faithful port of the frontend `evalNode` (src/features/filters/FiltersPage.jsx)
so the backend produces the SAME matches as the old client-side filtering. It runs over
raw task documents (ObjectId fields), comparing everything as strings.

A rule tree is a list of "cards" (groups) joined by a top-level conjunction. Each node is
either a group ({type:'group', conj:'AND'|'OR', children:[...]}) or a rule
({type:'rule', field, op:'is'|'is_not', value}). `value` is an array for multi-select
fields, a scalar for Space / text custom fields, and for the date fields (start_date,
end_date) a range {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD", "tz": <minutes>} where
either end may be empty and `tz` is the browser's getTimezoneOffset() (so a timestamp is
bucketed into the user's LOCAL calendar day).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

DATE_FIELDS = {"start_date", "end_date"}


def _rule_active(node: dict[str, Any]) -> bool:
    v = node.get("value")
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, dict):  # date range
        return bool(v.get("from") or v.get("to"))
    return v not in (None, "")


def _task_day(task: dict[str, Any], field: str, tz_minutes: int) -> str | None:
    """The task's Start / End date as a local "YYYY-MM-DD" (None when unset).

    Values are a plain "YYYY-MM-DD" (picked by hand) or an automatic UTC timestamp
    ("…T…Z", stamped when the status moved to Active / Done / Closed), which is bucketed
    into the user's local day. End date falls back to due_date for older tasks.
    """
    raw = task.get("start_date") if field == "start_date" else (task.get("end_date") or task.get("due_date"))
    if not raw:
        return None
    raw = str(raw)
    if "T" in raw:
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            # getTimezoneOffset() is UTC − local (e.g. −330 for IST) → local = UTC − offset.
            return (ts.astimezone(timezone.utc) - timedelta(minutes=tz_minutes)).date().isoformat()
        except ValueError:
            pass
    return raw[:10]


def _match_date_range(task: dict[str, Any], field: str, value: dict[str, Any]) -> bool:
    try:
        tz = int(value.get("tz") or 0)
    except (TypeError, ValueError):
        tz = 0
    day = _task_day(task, field, tz)
    if not day:
        return False  # no date → never "in range"
    lo, hi = value.get("from") or "", value.get("to") or ""
    return (not lo or day >= lo) and (not hi or day <= hi)


def _node_active(node: dict[str, Any]) -> bool:
    if node.get("type") == "group":
        return any(_node_active(c) for c in node.get("children", []))
    return _rule_active(node)


def _eval_node(node: dict[str, Any], task: dict[str, Any], me_id: str) -> bool:
    if node.get("type") == "group":
        kids = [c for c in node.get("children", []) if _node_active(c)]
        if not kids:
            return True
        res = [_eval_node(k, task, me_id) for k in kids]
        return any(res) if node.get("conj") == "OR" else all(res)

    if not _rule_active(node):
        return True
    neg = node.get("op") == "is_not"
    field = node.get("field") or ""
    value = node.get("value")
    m = True

    # Custom field: compare against task.custom_fields[<id>].
    if field.startswith("cf:"):
        cf_id = field[3:]
        tv = (task.get("custom_fields") or {}).get(cf_id)
        if isinstance(value, list):  # dropdown (labels) / relationship (ids)
            tv_arr = [str(x) for x in tv] if isinstance(tv, list) else ([str(tv)] if tv not in (None, "") else [])
            m = any(str(v) in tv_arr for v in value)
        else:  # text — contains
            m = str(value).lower() in str(tv if tv is not None else "").lower()
        return (not m) if neg else m

    if field in DATE_FIELDS:
        m = _match_date_range(task, field, value) if isinstance(value, dict) else True
        return (not m) if neg else m

    vals = [str(x) for x in value] if isinstance(value, list) else [str(value)]
    if field == "space":
        m = str(task.get("project_id")) == str(value)
    elif field == "list":
        m = str(task.get("list_id")) in vals
    elif field == "type":
        m = str(task.get("type") or "task") in vals
    elif field == "status":
        def match_status(v: str) -> bool:
            sep = v.find("::")
            if sep == -1:
                return str(task.get("status")) == v
            return str(task.get("list_id")) == v[:sep] and str(task.get("status")) == v[sep + 2:]
        m = any(match_status(v) for v in vals)
    elif field == "assignee":
        def match_assignee(v: str) -> bool:
            if v == "__unassigned__":
                return not task.get("assignee_id")
            if v == "__me__":
                return str(task.get("assignee_id")) == str(me_id)
            return str(task.get("assignee_id")) == v
        m = any(match_assignee(v) for v in vals)
    elif field == "reporter":
        def match_reporter(v: str) -> bool:
            if v == "__me__":
                return str(task.get("reporter_id")) == str(me_id)
            return str(task.get("reporter_id")) == v
        m = any(match_reporter(v) for v in vals)
    elif field == "label":
        labels = [str(x) for x in (task.get("labels") or [])]
        m = any(v in labels for v in vals)
    else:
        m = True
    return (not m) if neg else m


def task_matches(cards: list[dict[str, Any]], conj: str, task: dict[str, Any], me_id: str) -> bool:
    """True if the task satisfies the rule tree. Empty/inactive filter → matches all."""
    active = [c for c in (cards or []) if _node_active(c)]
    if not active:
        return True
    res = [_eval_node(c, task, me_id) for c in active]
    return any(res) if conj == "OR" else all(res)
