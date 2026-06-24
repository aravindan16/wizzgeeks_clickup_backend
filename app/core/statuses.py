"""Per-Space (project) customizable task statuses — ClickUp-style.

Each space stores its own ordered list of statuses, grouped into four buckets:
not_started → active → done → closed. Tasks created in a space use that space's
status keys. Spaces created before this feature have no `statuses` field; for them
we synthesize a list from the legacy global workflow so existing boards keep working.
"""
from __future__ import annotations

import re
from typing import Any

# Four fixed groups (columns are ordered within and across these).
GROUPS = ["not_started", "active", "done", "closed"]
GROUP_LABELS = {
    "not_started": "Not started", "active": "Active",
    "done": "Done", "closed": "Closed",
}

# Default statuses for a brand-new space.
DEFAULT_STATUSES = [
    {"key": "todo", "name": "TO DO", "color": "#94a3b8", "group": "not_started"},
    {"key": "in_progress", "name": "IN PROGRESS", "color": "#3b82f6", "group": "active"},
    {"key": "complete", "name": "COMPLETE", "color": "#22c55e", "group": "closed"},
]

# Legacy global workflow → group mapping, so pre-existing spaces still render.
_LEGACY = [
    {"key": "backlog", "name": "Backlog", "color": "#6b7280", "group": "not_started"},
    {"key": "planned", "name": "Planned", "color": "#64748b", "group": "not_started"},
    {"key": "in_progress", "name": "In Progress", "color": "#2563eb", "group": "active"},
    {"key": "blocked", "name": "Blocked", "color": "#b91c1c", "group": "active"},
    {"key": "review", "name": "Review", "color": "#7c3aed", "group": "active"},
    {"key": "testing", "name": "Testing", "color": "#d97706", "group": "active"},
    {"key": "completed", "name": "Completed", "color": "#16a34a", "group": "done"},
    {"key": "closed", "name": "Closed", "color": "#15803d", "group": "closed"},
]

# Predefined templates the user can pick from in the editor.
SYSTEM_TEMPLATES = [
    {"id": "default", "name": "Default", "statuses": DEFAULT_STATUSES},
    {"id": "kanban", "name": "Kanban", "statuses": [
        {"key": "todo", "name": "TO DO", "color": "#6b7280", "group": "not_started"},
        {"key": "in_progress", "name": "IN PROGRESS", "color": "#2563eb", "group": "active"},
        {"key": "done", "name": "DONE", "color": "#16a34a", "group": "done"},
    ]},
    {"id": "software", "name": "Software", "statuses": _LEGACY},
]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "status"


def legacy_statuses() -> list[dict[str, Any]]:
    """Status list for spaces created before custom statuses existed."""
    return [{**s, "order": i} for i, s in enumerate(_LEGACY)]


def default_statuses() -> list[dict[str, Any]]:
    return [{**s, "order": i} for i, s in enumerate(DEFAULT_STATUSES)]


def normalize_statuses(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Validate + clean a user-supplied status list into the stored shape.

    Ensures: at least one status, unique keys, a valid group, an explicit order.
    """
    if not raw:
        return default_statuses()

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        name = (item.get("name") or "").strip()
        if not name:
            continue
        key = item.get("key") or _slug(name)
        base = key
        n = 2
        while key in seen:
            key = f"{base}_{n}"
            n += 1
        seen.add(key)
        group = item.get("group") if item.get("group") in GROUPS else "active"
        color = item.get("color") or "#6b7280"
        out.append({"key": key, "name": name, "color": color, "group": group, "order": i})

    if not out:
        return default_statuses()
    # Sort by group order, then incoming order, so columns are coherent.
    out.sort(key=lambda s: (GROUPS.index(s["group"]), s["order"]))
    for i, s in enumerate(out):
        s["order"] = i
    return out


def statuses_for(project: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Resolved status list for a project (custom if set, else legacy)."""
    if project and project.get("statuses"):
        return sorted(project["statuses"], key=lambda s: s.get("order", 0))
    return legacy_statuses()


def status_keys(project: dict[str, Any] | None) -> list[str]:
    return [s["key"] for s in statuses_for(project)]


def default_status_key(project: dict[str, Any] | None) -> str:
    """First not_started status, else the very first status."""
    sts = statuses_for(project)
    for s in sts:
        if s["group"] == "not_started":
            return s["key"]
    return sts[0]["key"]


def done_keys(project: dict[str, Any] | None) -> set[str]:
    return {s["key"] for s in statuses_for(project) if s["group"] in ("done", "closed")}
