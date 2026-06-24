"""Report generation: builds normalized (columns + rows + summary) reports from
aggregation pipelines. A single normalized shape lets one Excel and one PDF
exporter render every report type."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import ValidationError
from app.core.workflow import BLOCKED, DONE_STATUSES
from app.repositories.base import is_valid_object_id, to_object_id
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow

DONE = list(DONE_STATUSES)


@dataclass
class ReportFilters:
    date: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    ref_date: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    manager_id: str | None = None  # team scope
    status: str | None = None
    priority: str | None = None


def _col(key: str, label: str) -> dict[str, str]:
    return {"key": key, "label": label}


def _days_between(d1: str, d2: str) -> int:
    return (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days


class ReportService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # --- date helpers ---
    def _today(self) -> str:
        return utcnow().strftime("%Y-%m-%d")

    def _week(self, ref_date: str | None) -> tuple[str, str]:
        ref = datetime.strptime(ref_date, "%Y-%m-%d").date() if ref_date else utcnow().date()
        start = ref - timedelta(days=ref.weekday())
        return start.isoformat(), (start + timedelta(days=6)).isoformat()

    def _month(self, ref_date: str | None) -> tuple[str, str]:
        ref = datetime.strptime(ref_date, "%Y-%m-%d").date() if ref_date else utcnow().date()
        start = ref.replace(day=1)
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start.isoformat(), (nxt - timedelta(days=1)).isoformat()

    # --- lookup maps ---
    async def _user_names(self, ids: list[Any]) -> dict[str, str]:
        rows = await self.db.users.find({"_id": {"$in": ids}}, {"full_name": 1}).to_list(length=5000)
        return {str(r["_id"]): r.get("full_name") for r in rows}

    async def _project_map(self) -> dict[str, dict[str, Any]]:
        rows = await self.db.projects.find({"is_deleted": {"$ne": True}},
                                           {"key": 1, "name": 1, "status": 1}).to_list(length=2000)
        return {str(r["_id"]): r for r in rows}

    async def _task_map(self, ids: list[Any]) -> dict[str, dict[str, Any]]:
        ids = [i for i in ids if i]
        rows = await self.db.tasks.find({"_id": {"$in": ids}}, {"key": 1, "title": 1}).to_list(length=5000)
        return {str(r["_id"]): r for r in rows}

    def _envelope(self, rtype: str, title: str, filters: ReportFilters,
                  columns: list[dict], rows: list[dict], summary: dict) -> dict[str, Any]:
        return {
            "type": rtype, "title": title, "generated_at": utcnow().isoformat(),
            "filters": {k: v for k, v in filters.__dict__.items() if v},
            "columns": columns, "rows": rows, "summary": summary,
        }

    # --- scope clamp ---
    def _clamp_user(self, actor: ActorContext, filters: ReportFilters) -> None:
        """Employees without team/all report scope may only report on themselves."""
        if not (actor.has("report.view.team") or actor.has("report.view.all")):
            filters.user_id = actor.user_id

    # === dispatch ===
    async def build(self, rtype: str, filters: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        builders = {
            "daily_activity": self._daily_activity,
            "weekly_summary": self._weekly_summary,
            "monthly_productivity": self._monthly_productivity,
            "project_progress": self._project_progress,
            "task_completion": self._task_completion,
            "delayed_tasks": self._delayed_tasks,
            "resource_utilization": self._resource_utilization,
            "team_performance": self._team_performance,
        }
        if rtype not in builders:
            raise ValidationError(f"Unknown report type '{rtype}'")
        return await builders[rtype](filters, actor)

    # === builders ===
    async def _daily_activity(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        self._clamp_user(actor, f)
        date = f.date or self._today()
        match: dict[str, Any] = {"date": date}
        if f.user_id and is_valid_object_id(f.user_id):
            match["user_id"] = to_object_id(f.user_id)
        updates = await self.db.daily_updates.find(match).to_list(length=2000)

        pmap = await self._project_map()
        task_ids = [e.get("task_id") for u in updates for e in u.get("entries", [])]
        tmap = await self._task_map(task_ids)
        names = await self._user_names(list({u["user_id"] for u in updates}))

        rows, total_hours, blockers = [], 0.0, 0
        for u in updates:
            for e in u.get("entries", []):
                if f.project_id and str(e.get("project_id")) != f.project_id:
                    continue
                h = float(e.get("hours_spent") or 0)
                total_hours += h
                if e.get("blockers"):
                    blockers += 1
                proj = pmap.get(str(e.get("project_id")))
                task = tmap.get(str(e.get("task_id")))
                rows.append({
                    "date": u["date"], "user": names.get(str(u["user_id"])),
                    "project": proj["key"] if proj else "—",
                    "task": task["key"] if task else "—",
                    "work_done": e.get("work_done"), "hours": h,
                    "status": e.get("status"), "blockers": e.get("blockers") or "",
                })
        cols = [_col("date", "Date"), _col("user", "User"), _col("project", "Project"),
                _col("task", "Task"), _col("work_done", "Work Done"), _col("hours", "Hours"),
                _col("status", "Status"), _col("blockers", "Blockers")]
        summary = {"Total Hours": round(total_hours, 2), "Entries": len(rows), "Blockers": blockers}
        return self._envelope("daily_activity", f"Daily Activity Report — {date}", f, cols, rows, summary)

    async def _period_summary(self, f: ReportFilters, actor: ActorContext, *, period: str) -> dict[str, Any]:
        self._clamp_user(actor, f)
        start, end = (self._week(f.ref_date) if period == "week" else self._month(f.ref_date))
        match: dict[str, Any] = {"date": {"$gte": start, "$lte": end}}
        if f.user_id and is_valid_object_id(f.user_id):
            match["user_id"] = to_object_id(f.user_id)
        rows_raw = await self.db.daily_updates.aggregate([
            {"$match": match},
            {"$group": {"_id": "$user_id",
                        "hours": {"$sum": "$total_hours"},
                        "updates": {"$sum": 1},
                        "blockers": {"$sum": {"$cond": ["$has_blockers", 1, 0]}}}},
            {"$sort": {"hours": -1}},
        ]).to_list(length=2000)
        names = await self._user_names([r["_id"] for r in rows_raw])
        span_days = max(1, _days_between(start, end) + 1)
        rows = [{
            "user": names.get(str(r["_id"])), "hours": round(r["hours"], 2),
            "updates": r["updates"], "blockers": r["blockers"],
            "avg_per_day": round(r["hours"] / span_days, 2),
        } for r in rows_raw]
        cols = [_col("user", "User"), _col("hours", "Total Hours"), _col("updates", "Updates"),
                _col("blockers", "Blockers"), _col("avg_per_day", "Avg/Day")]
        total_hours = round(sum(r["hours"] for r in rows), 2)
        summary = {"Period": f"{start} → {end}", "Users": len(rows),
                   "Total Hours": total_hours, "Total Blockers": sum(r["blockers"] for r in rows)}
        if period == "week":
            return self._envelope("weekly_summary", f"Weekly Summary — {start} to {end}", f, cols, rows, summary)
        return self._envelope("monthly_productivity", f"Monthly Productivity — {start[:7]}", f, cols, rows, summary)

    async def _weekly_summary(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        return await self._period_summary(f, actor, period="week")

    async def _monthly_productivity(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        return await self._period_summary(f, actor, period="month")

    async def _project_progress(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        today = self._today()
        pmatch: dict[str, Any] = {"is_deleted": {"$ne": True}}
        if f.project_id and is_valid_object_id(f.project_id):
            pmatch["_id"] = to_object_id(f.project_id)
        projects = await self.db.projects.find(pmatch, {"key": 1, "name": 1, "status": 1}).to_list(length=2000)

        rows = []
        tot_total = tot_done = 0
        for p in projects:
            base = {"project_id": p["_id"], "is_deleted": {"$ne": True}}
            total = await self.db.tasks.count_documents(base)
            completed = await self.db.tasks.count_documents({**base, "status": {"$in": DONE}})
            in_progress = await self.db.tasks.count_documents({**base, "status": "in_progress"})
            blocked = await self.db.tasks.count_documents({**base, "status": BLOCKED})
            overdue = await self.db.tasks.count_documents({**base, "status": {"$nin": DONE},
                                                           "due_date": {"$ne": None, "$lt": today}})
            members = await self.db.project_members.count_documents({"project_id": p["_id"], "removed_at": None})
            tot_total += total; tot_done += completed
            rows.append({"key": p["key"], "name": p["name"], "status": p.get("status"),
                         "total": total, "completed": completed, "in_progress": in_progress,
                         "blocked": blocked, "overdue": overdue, "members": members,
                         "progress": round((completed / total) * 100, 1) if total else 0.0})
        cols = [_col("key", "Key"), _col("name", "Project"), _col("status", "Status"),
                _col("total", "Total"), _col("completed", "Done"), _col("in_progress", "In Progress"),
                _col("blocked", "Blocked"), _col("overdue", "Overdue"), _col("members", "Members"),
                _col("progress", "Progress %")]
        summary = {"Projects": len(rows), "Total Tasks": tot_total, "Completed": tot_done,
                   "Overall Progress": f"{round((tot_done / tot_total) * 100, 1) if tot_total else 0}%"}
        return self._envelope("project_progress", "Project Progress Report", f, cols, rows, summary)

    async def _task_query(self, f: ReportFilters, extra: dict[str, Any]) -> dict[str, Any]:
        q: dict[str, Any] = {"is_deleted": {"$ne": True}, **extra}
        if f.project_id and is_valid_object_id(f.project_id):
            q["project_id"] = to_object_id(f.project_id)
        if f.status:
            q["status"] = f.status
        if f.priority:
            q["priority"] = f.priority
        return q

    async def _task_completion(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        q = await self._task_query(f, {"status": {"$in": DONE}})
        tasks = await self.db.tasks.find(q).sort("updated_at", -1).limit(2000).to_list(length=2000)
        pmap = await self._project_map()
        names = await self._user_names([t["assignee_id"] for t in tasks if t.get("assignee_id")])
        rows, actual = [], 0.0
        for t in tasks:
            actual += float(t.get("actual_hours") or 0)
            proj = pmap.get(str(t.get("project_id")))
            rows.append({"key": t["key"], "title": t["title"],
                         "project": proj["key"] if proj else "—",
                         "assignee": names.get(str(t.get("assignee_id"))) or "—",
                         "status": t["status"], "estimate": t.get("estimate_hours") or 0,
                         "actual": t.get("actual_hours") or 0})
        cols = [_col("key", "Key"), _col("title", "Title"), _col("project", "Project"),
                _col("assignee", "Assignee"), _col("status", "Status"),
                _col("estimate", "Est. Hrs"), _col("actual", "Actual Hrs")]
        summary = {"Completed Tasks": len(rows), "Total Actual Hours": round(actual, 2)}
        return self._envelope("task_completion", "Task Completion Report", f, cols, rows, summary)

    async def _delayed_tasks(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        today = self._today()
        q = await self._task_query(f, {"status": {"$nin": DONE}, "due_date": {"$ne": None, "$lt": today}})
        tasks = await self.db.tasks.find(q).sort("due_date", 1).limit(2000).to_list(length=2000)
        pmap = await self._project_map()
        names = await self._user_names([t["assignee_id"] for t in tasks if t.get("assignee_id")])
        rows = []
        for t in tasks:
            proj = pmap.get(str(t.get("project_id")))
            rows.append({"key": t["key"], "title": t["title"],
                         "project": proj["key"] if proj else "—",
                         "assignee": names.get(str(t.get("assignee_id"))) or "—",
                         "due_date": t.get("due_date"), "days_overdue": _days_between(t["due_date"], today),
                         "priority": t["priority"], "status": t["status"]})
        cols = [_col("key", "Key"), _col("title", "Title"), _col("project", "Project"),
                _col("assignee", "Assignee"), _col("due_date", "Due"), _col("days_overdue", "Days Overdue"),
                _col("priority", "Priority"), _col("status", "Status")]
        summary = {"Delayed Tasks": len(rows)}
        return self._envelope("delayed_tasks", "Delayed Task Report", f, cols, rows, summary)

    async def _resource_utilization(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        wstart, wend = self._week(f.ref_date)
        # Scope users: project members if project filter, else active users.
        if f.project_id and is_valid_object_id(f.project_id):
            members = await self.db.project_members.find(
                {"project_id": to_object_id(f.project_id), "removed_at": None}).to_list(length=2000)
            uids = [m["user_id"] for m in members]
        else:
            urows = await self.db.users.find({"status": "active", "is_deleted": {"$ne": True}},
                                             {"_id": 1}).to_list(length=5000)
            uids = [u["_id"] for u in urows]
        names = await self._user_names(uids)

        hours_rows = await self.db.daily_updates.aggregate([
            {"$match": {"user_id": {"$in": uids}, "date": {"$gte": wstart, "$lte": wend}}},
            {"$group": {"_id": "$user_id", "hours": {"$sum": "$total_hours"}}},
        ]).to_list(length=5000)
        hours_by = {str(r["_id"]): round(r["hours"], 2) for r in hours_rows}

        open_rows = await self.db.tasks.aggregate([
            {"$match": {"assignee_id": {"$in": uids}, "is_deleted": {"$ne": True}, "status": {"$nin": DONE}}},
            {"$group": {"_id": "$assignee_id", "open": {"$sum": 1},
                        "est": {"$sum": {"$ifNull": ["$estimate_hours", 0]}}}},
        ]).to_list(length=5000)
        open_by = {str(r["_id"]): r for r in open_rows}

        rows = []
        capacity = 40.0  # nominal weekly capacity (hours)
        for uid in uids:
            sid = str(uid)
            hrs = hours_by.get(sid, 0)
            o = open_by.get(sid, {})
            rows.append({"user": names.get(sid), "open_tasks": o.get("open", 0),
                         "hours_week": hrs, "est_hours": round(o.get("est", 0), 1),
                         "utilization": f"{round((hrs / capacity) * 100, 1)}%"})
        rows.sort(key=lambda r: r["hours_week"], reverse=True)
        cols = [_col("user", "User"), _col("open_tasks", "Open Tasks"), _col("hours_week", "Hours (wk)"),
                _col("est_hours", "Est. Backlog Hrs"), _col("utilization", "Utilization")]
        summary = {"Users": len(rows), "Total Hours (wk)": round(sum(r["hours_week"] for r in rows), 2),
                   "Week": f"{wstart} → {wend}"}
        return self._envelope("resource_utilization", "Resource Utilization Report", f, cols, rows, summary)

    async def _team_performance(self, f: ReportFilters, actor: ActorContext) -> dict[str, Any]:
        wstart, wend = self._week(f.ref_date)
        if f.manager_id and is_valid_object_id(f.manager_id):
            urows = await self.db.users.find({"manager_id": to_object_id(f.manager_id),
                                              "is_deleted": {"$ne": True}}, {"_id": 1}).to_list(length=2000)
            uids = [u["_id"] for u in urows]
        else:
            urows = await self.db.users.find({"status": "active", "is_deleted": {"$ne": True}},
                                             {"_id": 1}).to_list(length=5000)
            uids = [u["_id"] for u in urows]
        names = await self._user_names(uids)

        hrows = await self.db.daily_updates.aggregate([
            {"$match": {"user_id": {"$in": uids}, "date": {"$gte": wstart, "$lte": wend}}},
            {"$group": {"_id": "$user_id", "hours": {"$sum": "$total_hours"},
                        "blockers": {"$sum": {"$cond": ["$has_blockers", 1, 0]}}}},
        ]).to_list(length=5000)
        hby = {str(r["_id"]): r for r in hrows}

        crows = await self.db.tasks.aggregate([
            {"$match": {"assignee_id": {"$in": uids}, "is_deleted": {"$ne": True}}},
            {"$group": {"_id": "$assignee_id",
                        "completed": {"$sum": {"$cond": [{"$in": ["$status", DONE]}, 1, 0]}},
                        "open": {"$sum": {"$cond": [{"$in": ["$status", DONE]}, 0, 1]}}}},
        ]).to_list(length=5000)
        cby = {str(r["_id"]): r for r in crows}

        rows = []
        for uid in uids:
            sid = str(uid)
            h = hby.get(sid, {})
            c = cby.get(sid, {})
            completed = c.get("completed", 0); openc = c.get("open", 0)
            total = completed + openc
            rows.append({"user": names.get(sid), "hours": round(h.get("hours", 0), 2),
                         "completed": completed, "open": openc, "blockers": h.get("blockers", 0),
                         "completion_rate": f"{round((completed / total) * 100, 1) if total else 0}%"})
        rows.sort(key=lambda r: r["hours"], reverse=True)
        cols = [_col("user", "User"), _col("hours", "Hours (wk)"), _col("completed", "Completed"),
                _col("open", "Open"), _col("blockers", "Blockers"), _col("completion_rate", "Completion")]
        all_completed = sum(r["completed"] for r in rows)
        all_total = all_completed + sum(r["open"] for r in rows)
        summary = {"Team Members": len(rows), "Total Hours (wk)": round(sum(r["hours"] for r in rows), 2),
                   "Productivity Score": f"{round((all_completed / all_total) * 100, 1) if all_total else 0}%"}
        return self._envelope("team_performance", "Team Performance Report", f, cols, rows, summary)
