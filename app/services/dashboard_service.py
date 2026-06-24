"""Dashboard & analytics business logic via MongoDB aggregation pipelines."""
from datetime import timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.workflow import BLOCKED, DONE_STATUSES
from app.repositories.base import to_object_id
from app.services.user_service import ActorContext
from app.utils.cache import TTLCache
from app.utils.datetime import utcnow

DONE = list(DONE_STATUSES)
_admin_cache = TTLCache(ttl_seconds=30)


def _d(dt) -> str:
    return dt.strftime("%Y-%m-%d")


class DashboardService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # --- date helpers ---
    def _today(self) -> str:
        return _d(utcnow())

    def _week_range(self) -> tuple[str, str]:
        ref = utcnow().date()
        start = ref - timedelta(days=ref.weekday())
        return start.isoformat(), (start + timedelta(days=6)).isoformat()

    def _days_back(self, n: int) -> str:
        return _d(utcnow() - timedelta(days=n))

    # --- shared aggregations ---
    async def _hours_by_day(self, user_ids: list[Any] | None, start: str, end: str) -> dict[str, float]:
        match: dict[str, Any] = {"date": {"$gte": start, "$lte": end}}
        if user_ids is not None:
            match["user_id"] = {"$in": user_ids}
        pipeline = [
            {"$match": match},
            {"$group": {"_id": "$date", "hours": {"$sum": "$total_hours"}}},
        ]
        rows = await self.db.daily_updates.aggregate(pipeline).to_list(length=None)
        return {r["_id"]: round(r["hours"], 2) for r in rows}

    async def _tasks_by_status(self, match: dict[str, Any]) -> list[dict[str, Any]]:
        pipeline = [
            {"$match": {**match, "is_deleted": {"$ne": True}, "is_archived": {"$ne": True}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        rows = await self.db.tasks.aggregate(pipeline).to_list(length=None)
        return [{"status": r["_id"], "count": r["count"]} for r in rows]

    async def _task_counts(self, match: dict[str, Any]) -> dict[str, int]:
        base = {**match, "is_deleted": {"$ne": True}, "is_archived": {"$ne": True}}
        today = self._today()
        return {
            "open": await self.db.tasks.count_documents({**base, "status": {"$nin": DONE}}),
            "completed": await self.db.tasks.count_documents({**base, "status": {"$in": DONE}}),
            "blocked": await self.db.tasks.count_documents({**base, "status": BLOCKED}),
            "overdue": await self.db.tasks.count_documents({
                **base, "status": {"$nin": DONE}, "due_date": {"$ne": None, "$lt": today}}),
        }

    async def _reportee_ids(self, manager_id: str) -> list[Any]:
        rows = await self.db.users.find(
            {"manager_id": to_object_id(manager_id), "is_deleted": {"$ne": True}},
            {"full_name": 1, "email": 1, "department": 1},
        ).to_list(length=1000)
        return rows

    # --- Employee ---
    async def employee(self, actor: ActorContext) -> dict[str, Any]:
        uid = to_object_id(actor.user_id)
        counts = await self._task_counts({"assignee_id": uid})

        today = self._today()
        todays = await self.db.tasks.find(
            {"assignee_id": uid, "is_deleted": {"$ne": True}, "status": {"$nin": DONE}},
            {"key": 1, "title": 1, "status": 1, "priority": 1, "due_date": 1},
        ).sort("due_date", 1).limit(10).to_list(length=10)
        for t in todays:
            t["_id"] = str(t["_id"])

        today_upd = await self.db.daily_updates.find_one({"user_id": uid, "date": today})
        hours_today = today_upd.get("total_hours", 0) if today_upd else 0

        wstart, wend = self._week_range()
        week_hours = await self._hours_by_day([uid], wstart, wend)
        trend_map = await self._hours_by_day([uid], self._days_back(13), today)
        trend = [{"date": self._days_back(13 - i),
                  "hours": trend_map.get(self._days_back(13 - i), 0)} for i in range(14)]

        recent = await self.db.daily_updates.find({"user_id": uid}).sort("date", -1).limit(5).to_list(length=5)
        for r in recent:
            r["_id"] = str(r["_id"]); r["user_id"] = str(r["user_id"])
            r.pop("entries", None)

        return {
            "open_tasks": counts["open"], "completed_tasks": counts["completed"],
            "blocked_tasks": counts["blocked"], "overdue_tasks": counts["overdue"],
            "hours_today": hours_today, "weekly_hours": round(sum(week_hours.values()), 2),
            "todays_tasks": todays, "recent_updates": recent,
            "hours_by_day": week_hours, "activity_trend": trend,
        }

    # --- Team (Team Lead) ---
    async def team(self, actor: ActorContext) -> dict[str, Any]:
        reportees = await self._reportee_ids(actor.user_id)
        ids = [r["_id"] for r in reportees]
        wstart, wend = self._week_range()
        today = self._today()

        members = [{"user_id": str(r["_id"]), "full_name": r.get("full_name"),
                    "email": r.get("email"), "department": r.get("department")} for r in reportees]

        # productivity (week hours per member)
        prod_rows = await self.db.daily_updates.aggregate([
            {"$match": {"user_id": {"$in": ids}, "date": {"$gte": wstart, "$lte": wend}}},
            {"$group": {"_id": "$user_id", "hours": {"$sum": "$total_hours"}}},
        ]).to_list(length=None) if ids else []
        prod_by_id = {str(r["_id"]): round(r["hours"], 2) for r in prod_rows}
        team_productivity = [{"user_id": m["user_id"], "full_name": m["full_name"],
                              "hours": prod_by_id.get(m["user_id"], 0)} for m in members]

        # missing updates today
        submitted = await self.db.daily_updates.find(
            {"user_id": {"$in": ids}, "date": today}, {"user_id": 1}).to_list(length=1000) if ids else []
        submitted_ids = {str(s["user_id"]) for s in submitted}
        missing = [m for m in members if m["user_id"] not in submitted_ids]

        # open blockers (last 7 days)
        blocker_docs = await self.db.daily_updates.find(
            {"user_id": {"$in": ids}, "has_blockers": True, "date": {"$gte": self._days_back(7)}}
        ).to_list(length=200) if ids else []
        names = {m["user_id"]: m["full_name"] for m in members}
        open_blockers = []
        for d in blocker_docs:
            for e in d.get("entries", []):
                if e.get("blockers"):
                    open_blockers.append({"user_name": names.get(str(d["user_id"])),
                                          "date": d["date"], "blockers": e["blockers"]})

        # task distribution + capacity
        distribution = await self._tasks_by_status({"assignee_id": {"$in": ids}}) if ids else []
        cap_rows = await self.db.tasks.aggregate([
            {"$match": {"assignee_id": {"$in": ids}, "is_deleted": {"$ne": True},
                        "status": {"$nin": DONE}}},
            {"$group": {"_id": "$assignee_id", "open": {"$sum": 1}}},
        ]).to_list(length=None) if ids else []
        cap_by_id = {str(r["_id"]): r["open"] for r in cap_rows}
        capacity = [{"user_id": m["user_id"], "full_name": m["full_name"],
                     "open_tasks": cap_by_id.get(m["user_id"], 0),
                     "hours_week": prod_by_id.get(m["user_id"], 0)} for m in members]

        return {
            "team_members": members, "team_productivity": team_productivity,
            "missing_updates": missing, "open_blockers": open_blockers,
            "task_distribution": distribution, "team_capacity": capacity,
        }

    # --- Manager ---
    async def _project_progress(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.tasks.aggregate([
            {"$match": {"is_deleted": {"$ne": True}}},
            {"$group": {"_id": "$project_id", "total": {"$sum": 1},
                        "completed": {"$sum": {"$cond": [{"$in": ["$status", DONE]}, 1, 0]}}}},
        ]).to_list(length=None)
        by_project = {str(r["_id"]): r for r in rows}
        projects = await self.db.projects.find(
            {"is_deleted": {"$ne": True}}, {"key": 1, "name": 1, "status": 1}
        ).limit(limit).to_list(length=limit)
        out = []
        for p in projects:
            stat = by_project.get(str(p["_id"]), {"total": 0, "completed": 0})
            total = stat["total"]; completed = stat["completed"]
            out.append({"project_id": str(p["_id"]), "key": p["key"], "name": p["name"],
                        "status": p.get("status"), "total_tasks": total, "completed_tasks": completed,
                        "progress": round((completed / total) * 100, 1) if total else 0.0})
        return out

    async def manager(self, actor: ActorContext) -> dict[str, Any]:
        wstart, wend = self._week_range()
        today = self._today()
        progress = await self._project_progress()

        perf_rows = await self.db.daily_updates.aggregate([
            {"$match": {"date": {"$gte": wstart, "$lte": wend}}},
            {"$group": {"_id": "$user_id", "hours": {"$sum": "$total_hours"}}},
            {"$sort": {"hours": -1}}, {"$limit": 10},
        ]).to_list(length=10)
        perf_ids = [r["_id"] for r in perf_rows]
        users = await self.db.users.find({"_id": {"$in": perf_ids}}, {"full_name": 1}).to_list(length=10)
        names = {str(u["_id"]): u.get("full_name") for u in users}
        team_performance = [{"user_id": str(r["_id"]), "full_name": names.get(str(r["_id"])),
                             "hours": round(r["hours"], 2)} for r in perf_rows]

        delayed = await self.db.tasks.find(
            {"is_deleted": {"$ne": True}, "status": {"$nin": DONE},
             "due_date": {"$ne": None, "$lt": today}},
            {"key": 1, "title": 1, "status": 1, "due_date": 1, "assignee_id": 1},
        ).sort("due_date", 1).limit(20).to_list(length=20)
        for t in delayed:
            t["_id"] = str(t["_id"])
            if t.get("assignee_id"):
                t["assignee_id"] = str(t["assignee_id"])
        delayed_count = await self.db.tasks.count_documents(
            {"is_deleted": {"$ne": True}, "status": {"$nin": DONE},
             "due_date": {"$ne": None, "$lt": today}})

        week_hours = await self._hours_by_day(None, wstart, wend)
        updates_count = await self.db.daily_updates.count_documents({"date": {"$gte": wstart, "$lte": wend}})
        blocker_count = await self.db.daily_updates.count_documents(
            {"date": {"$gte": wstart, "$lte": wend}, "has_blockers": True})

        return {
            "project_progress": progress, "team_performance": team_performance,
            "delayed_tasks": delayed, "delayed_count": delayed_count,
            "weekly_report": {"total_hours": round(sum(week_hours.values()), 2),
                              "updates_count": updates_count, "blocker_count": blocker_count,
                              "start_date": wstart, "end_date": wend},
        }

    # --- Admin (cached) ---
    async def admin(self) -> dict[str, Any]:
        cached = _admin_cache.get("admin")
        if cached:
            return cached

        wstart, wend = self._week_range()
        total_users = await self.db.users.count_documents({"is_deleted": {"$ne": True}})
        active_users = await self.db.users.count_documents({"is_deleted": {"$ne": True}, "status": "active"})
        total_projects = await self.db.projects.count_documents({"is_deleted": {"$ne": True}})
        active_projects = await self.db.projects.count_documents({"is_deleted": {"$ne": True}, "status": "active"})
        counts = await self._task_counts({})
        total_tasks = await self.db.tasks.count_documents({"is_deleted": {"$ne": True}, "is_archived": {"$ne": True}})
        completion_rate = round((counts["completed"] / total_tasks) * 100, 1) if total_tasks else 0.0

        week_hours = await self._hours_by_day(None, wstart, wend)
        weekly_hours = round(sum(week_hours.values()), 2)

        # missing updates today across active users
        today = self._today()
        active_ids = await self.db.users.find(
            {"is_deleted": {"$ne": True}, "status": "active"}, {"_id": 1}).to_list(length=5000)
        ids = [u["_id"] for u in active_ids]
        submitted = await self.db.daily_updates.find(
            {"user_id": {"$in": ids}, "date": today}, {"user_id": 1}).to_list(length=5000)
        missing_today = len(ids) - len({str(s["user_id"]) for s in submitted})

        # productivity score: blend of completion rate and on-time delivery proxy.
        productivity_score = round(min(100.0, completion_rate * 0.7 + (100 - min(100, counts["overdue"] * 5)) * 0.3), 1)

        result = {
            "total_users": total_users, "active_users": active_users,
            "total_projects": total_projects, "active_projects": active_projects,
            "total_tasks": total_tasks, "open_tasks": counts["open"],
            "blocked_tasks": counts["blocked"], "overdue_tasks": counts["overdue"],
            "completion_rate": completion_rate, "productivity_score": productivity_score,
            "weekly_hours": weekly_hours, "missing_updates_today": max(0, missing_today),
            "tasks_by_status": await self._tasks_by_status({}),
            "project_progress": await self._project_progress(limit=10),
        }
        _admin_cache.set("admin", result)
        return result

    # --- Analytics (filterable) ---
    async def analytics_tasks_by_status(self, *, project_id: str | None, assignee_id: str | None):
        match: dict[str, Any] = {}
        if project_id:
            match["project_id"] = to_object_id(project_id)
        if assignee_id:
            match["assignee_id"] = to_object_id(assignee_id)
        return await self._tasks_by_status(match)

    async def analytics_hours_trend(self, actor: ActorContext, *, user_id: str | None, days: int):
        # Org-wide trend requires team/all scope; otherwise restrict to self.
        if user_id:
            target_ids = [to_object_id(user_id)]
        elif actor.has("report.view.all") or actor.has("dashboard.view.admin"):
            target_ids = None  # everyone
        else:
            target_ids = [to_object_id(actor.user_id)]
        start, end = self._days_back(days - 1), self._today()
        by_day = await self._hours_by_day(target_ids, start, end)
        return [{"date": self._days_back(days - 1 - i), "hours": by_day.get(self._days_back(days - 1 - i), 0)}
                for i in range(days)]
