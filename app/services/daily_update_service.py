"""Daily activity (standup) business logic.

Highlights:
- One update per (user, date); past days are locked for employees, editable by
  managers/admins (dailyupdate.read.all).
- Entry hours roll up into the linked task's actual_hours (delta-applied on edit).
- Blockers raise an in-app notification to the author's manager.
- Team/missing/blocker/summary queries are scoped by the actor's read permission.
"""
from datetime import datetime, timedelta
from typing import Any

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.daily_update_repository import DailyUpdateRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow


def _today() -> str:
    return utcnow().strftime("%Y-%m-%d")


def _entry_out(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": str(e["project_id"]) if e.get("project_id") else None,
        "task_id": str(e["task_id"]) if e.get("task_id") else None,
        "work_done": e.get("work_done"),
        "hours_spent": e.get("hours_spent", 0),
        "blockers": e.get("blockers"),
        "status": e.get("status", "in_progress"),
    }


class DailyUpdateService:
    def __init__(
        self,
        updates: DailyUpdateRepository,
        users: UserRepository,
        tasks: TaskRepository,
        audit: AuditService,
        notifications: NotificationService,
    ):
        self.updates = updates
        self.users = users
        self.tasks = tasks
        self.audit = audit
        self.notifications = notifications

    # --- helpers ---
    def _serialize(self, u: dict[str, Any], *, user_name: str | None, elevated: bool) -> dict[str, Any]:
        entries = [_entry_out(e) for e in u.get("entries", [])]
        return {
            "_id": str(u["_id"]),
            "user_id": str(u["user_id"]),
            "user_name": user_name,
            "date": u["date"],
            "entries": entries,
            "tomorrow_plan": u.get("tomorrow_plan"),
            "mood": u.get("mood"),
            "total_hours": u.get("total_hours", 0),
            "has_blockers": u.get("has_blockers", False),
            "locked": (not elevated) and u["date"] < _today(),
            "submitted_at": u.get("submitted_at"),
            "created_at": u.get("created_at"),
            "updated_at": u.get("updated_at"),
        }

    @staticmethod
    def _normalize_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, bool]:
        norm: list[dict[str, Any]] = []
        total = 0.0
        has_blockers = False
        for e in entries:
            tid = e.get("task_id")
            pid = e.get("project_id")
            if tid and not is_valid_object_id(tid):
                raise ValidationError("Invalid task_id in entry")
            if pid and not is_valid_object_id(pid):
                raise ValidationError("Invalid project_id in entry")
            blockers = (e.get("blockers") or "").strip() or None
            hours = float(e.get("hours_spent") or 0)
            total += hours
            if blockers:
                has_blockers = True
            norm.append({
                "project_id": to_object_id(pid) if pid else None,
                "task_id": to_object_id(tid) if tid else None,
                "work_done": e["work_done"],
                "hours_spent": hours,
                "blockers": blockers,
                "status": e.get("status", "in_progress"),
            })
        return norm, round(total, 2), has_blockers

    @staticmethod
    def _hours_by_task(entries: list[dict[str, Any]]) -> dict[str, float]:
        agg: dict[str, float] = {}
        for e in entries:
            if e.get("task_id"):
                key = str(e["task_id"])
                agg[key] = agg.get(key, 0) + float(e.get("hours_spent") or 0)
        return agg

    async def _apply_task_hours(self, old_entries: list, new_entries: list) -> None:
        """Apply the per-task hour delta between old and new entries to task.actual_hours."""
        old = self._hours_by_task(old_entries)
        new = self._hours_by_task(new_entries)
        for task_id in set(old) | set(new):
            delta = new.get(task_id, 0) - old.get(task_id, 0)
            if delta:
                await self.tasks.increment_actual_hours(task_id, delta)

    async def _maybe_notify_blocker(self, user: dict[str, Any], update_id: str, date: str) -> None:
        manager_id = user.get("manager_id")
        if not manager_id:
            return
        await self.notifications.notify(
            recipient_id=str(manager_id),
            type="dailyupdate.blocker",
            title=f"Blocker reported by {user.get('full_name', 'a team member')}",
            body=f"Daily update for {date} contains a blocker.",
            entity_type="daily_update",
            entity_id=update_id,
        )

    def _elevated(self, actor: ActorContext) -> bool:
        return actor.has("dailyupdate.read.all")

    async def _assert_can_edit(self, actor: ActorContext, update: dict[str, Any]) -> None:
        if self._elevated(actor):
            return
        if str(update["user_id"]) != actor.user_id:
            raise PermissionDeniedError("You can only edit your own updates")
        if update["date"] != _today():
            raise PermissionDeniedError("Past updates are locked and cannot be edited")

    async def _reportee_ids(self, actor: ActorContext) -> list[Any]:
        rows = await self.users.find_many(
            {"manager_id": to_object_id(actor.user_id), "is_deleted": {"$ne": True}},
            limit=1000, projection={"_id": 1},
        )
        return [r["_id"] for r in rows]

    async def _scoped_user_ids(self, actor: ActorContext) -> list[Any] | None:
        """None means all users (org-wide). Otherwise the list the actor may see."""
        if actor.has("dailyupdate.read.all"):
            return None
        ids = {to_object_id(actor.user_id)}
        if actor.has("dailyupdate.read.team"):
            ids.update(await self._reportee_ids(actor))
        return list(ids)

    async def _assert_can_read(self, actor: ActorContext, update: dict[str, Any]) -> None:
        if str(update["user_id"]) == actor.user_id or self._elevated(actor):
            return
        if actor.has("dailyupdate.read.team"):
            reportees = {str(i) for i in await self._reportee_ids(actor)}
            if str(update["user_id"]) in reportees:
                return
        raise PermissionDeniedError("You cannot view this update")

    # --- commands ---
    async def create_update(self, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        date = data.get("date") or _today()
        if await self.updates.find_by_user_date(actor.user_id, date):
            raise ConflictError("A daily update already exists for this date")

        entries, total, has_blockers = self._normalize_entries(data["entries"])
        now = utcnow()
        doc = {
            "user_id": to_object_id(actor.user_id),
            "date": date,
            "entries": entries,
            "tomorrow_plan": data.get("tomorrow_plan"),
            "mood": data.get("mood"),
            "total_hours": total,
            "has_blockers": has_blockers,
            "submitted_at": now,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.updates.insert_one(doc)
        uid = str(created["_id"])

        await self._apply_task_hours([], entries)
        await self.audit.log(actor_id=actor.user_id, action="dailyupdate.created",
                             entity_type="daily_update", entity_id=uid,
                             metadata={"date": date, "hours": total}, ip=actor.ip)
        user = await self.users.find_safe_by_id(actor.user_id)
        if has_blockers and user:
            await self._maybe_notify_blocker(user, uid, date)
        return self._serialize(created, user_name=user.get("full_name") if user else None,
                               elevated=self._elevated(actor))

    async def update_update(self, update_id: str, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        if not is_valid_object_id(update_id):
            raise NotFoundError("Update not found")
        existing = await self.updates.find_by_id(update_id)
        if not existing:
            raise NotFoundError("Update not found")
        await self._assert_can_edit(actor, existing)

        update_doc: dict[str, Any] = {"updated_at": utcnow()}
        new_entries = existing.get("entries", [])
        if data.get("entries") is not None:
            new_entries, total, has_blockers = self._normalize_entries(data["entries"])
            update_doc["entries"] = new_entries
            update_doc["total_hours"] = total
            update_doc["has_blockers"] = has_blockers
        if "tomorrow_plan" in data and data["tomorrow_plan"] is not None:
            update_doc["tomorrow_plan"] = data["tomorrow_plan"]
        if "mood" in data and data["mood"] is not None:
            update_doc["mood"] = data["mood"]

        if "entries" in update_doc:
            await self._apply_task_hours(existing.get("entries", []), new_entries)

        updated = await self.updates.update_by_id(update_id, update_doc)
        await self.audit.log(actor_id=actor.user_id, action="dailyupdate.updated",
                             entity_type="daily_update", entity_id=update_id,
                             metadata={"date": existing["date"]}, ip=actor.ip)

        owner = await self.users.find_safe_by_id(str(existing["user_id"]))
        if updated.get("has_blockers") and owner:
            await self._maybe_notify_blocker(owner, update_id, existing["date"])
        return self._serialize(updated, user_name=owner.get("full_name") if owner else None,
                               elevated=self._elevated(actor))

    # --- queries ---
    async def get_update(self, update_id: str, actor: ActorContext) -> dict[str, Any]:
        if not is_valid_object_id(update_id):
            raise NotFoundError("Update not found")
        update = await self.updates.find_by_id(update_id)
        if not update:
            raise NotFoundError("Update not found")
        await self._assert_can_read(actor, update)
        owner = await self.users.find_safe_by_id(str(update["user_id"]))
        return self._serialize(update, user_name=owner.get("full_name") if owner else None,
                               elevated=self._elevated(actor))

    async def my_updates(self, actor: ActorContext, *, skip: int, limit: int,
                         date_from: str | None, date_to: str | None) -> tuple[list[dict], int]:
        query: dict[str, Any] = {"user_id": to_object_id(actor.user_id)}
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        items = await self.updates.list_updates(query, skip=skip, limit=limit)
        total = await self.updates.count(query)
        user = await self.users.find_safe_by_id(actor.user_id)
        name = user.get("full_name") if user else None
        return [self._serialize(u, user_name=name, elevated=self._elevated(actor)) for u in items], total

    async def list_team(self, actor: ActorContext, *, skip: int, limit: int, date: str | None,
                        date_from: str | None, date_to: str | None, user_id: str | None,
                        ) -> tuple[list[dict], int]:
        scoped = await self._scoped_user_ids(actor)
        query: dict[str, Any] = {}
        if scoped is not None:
            query["user_id"] = {"$in": scoped}
        if user_id and is_valid_object_id(user_id):
            query["user_id"] = to_object_id(user_id)
        if date:
            query["date"] = date
        elif date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to

        items = await self.updates.list_updates(query, skip=skip, limit=limit)
        total = await self.updates.count(query)
        # Resolve user names in one pass.
        ids = list({u["user_id"] for u in items})
        users = await self.users.find_many({"_id": {"$in": ids}}, limit=1000, projection={"full_name": 1})
        names = {str(u["_id"]): u.get("full_name") for u in users}
        out = [self._serialize(u, user_name=names.get(str(u["user_id"])),
                               elevated=self._elevated(actor)) for u in items]
        return out, total

    async def missing_updates(self, actor: ActorContext, date: str | None) -> list[dict[str, Any]]:
        date = date or _today()
        scoped = await self._scoped_user_ids(actor)
        user_query: dict[str, Any] = {"status": "active", "is_deleted": {"$ne": True}}
        if scoped is not None:
            user_query["_id"] = {"$in": scoped}
        users = await self.users.find_many(user_query, limit=2000,
                                           projection={"full_name": 1, "email": 1, "department": 1})
        user_ids = [u["_id"] for u in users]
        submitted = await self.updates.find_for_users_on_date(user_ids, date)
        submitted_ids = {str(s["user_id"]) for s in submitted}
        return [
            {"user_id": str(u["_id"]), "full_name": u.get("full_name"),
             "email": u.get("email"), "department": u.get("department")}
            for u in users if str(u["_id"]) not in submitted_ids
        ]

    async def team_blockers(self, actor: ActorContext, *, date_from: str | None,
                            date_to: str | None) -> list[dict[str, Any]]:
        scoped = await self._scoped_user_ids(actor)
        query: dict[str, Any] = {"has_blockers": True}
        if scoped is not None:
            query["user_id"] = {"$in": scoped}
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        rows = await self.updates.list_updates(query, skip=0, limit=500)
        ids = list({r["user_id"] for r in rows})
        users = await self.users.find_many({"_id": {"$in": ids}}, limit=1000, projection={"full_name": 1})
        names = {str(u["_id"]): u.get("full_name") for u in users}
        out: list[dict[str, Any]] = []
        for r in rows:
            for e in r.get("entries", []):
                if e.get("blockers"):
                    out.append({
                        "update_id": str(r["_id"]),
                        "user_id": str(r["user_id"]),
                        "user_name": names.get(str(r["user_id"])),
                        "date": r["date"],
                        "task_id": str(e["task_id"]) if e.get("task_id") else None,
                        "project_id": str(e["project_id"]) if e.get("project_id") else None,
                        "blockers": e["blockers"],
                    })
        return out

    async def summary(self, actor: ActorContext, *, target_user_id: str | None,
                      period: str, ref_date: str | None) -> dict[str, Any]:
        target = target_user_id or actor.user_id
        if target != actor.user_id:
            # Reading someone else's summary requires team/all scope.
            scoped = await self._scoped_user_ids(actor)
            if scoped is not None and to_object_id(target) not in scoped:
                raise PermissionDeniedError("You cannot view this user's summary")

        ref = datetime.strptime(ref_date, "%Y-%m-%d").date() if ref_date else utcnow().date()
        if period == "month":
            start = ref.replace(day=1)
            next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            end = next_month - timedelta(days=1)
        else:  # week (Mon–Sun)
            start = ref - timedelta(days=ref.weekday())
            end = start + timedelta(days=6)
        start_s, end_s = start.isoformat(), end.isoformat()

        rows = await self.updates.find_range(target, start_s, end_s)
        total = 0.0
        blocker_count = 0
        hours_by_day: dict[str, float] = {}
        hours_by_project: dict[str, float] = {}
        for r in rows:
            day_hours = 0.0
            for e in r.get("entries", []):
                h = float(e.get("hours_spent") or 0)
                day_hours += h
                if e.get("blockers"):
                    blocker_count += 1
                if e.get("project_id"):
                    pid = str(e["project_id"])
                    hours_by_project[pid] = round(hours_by_project.get(pid, 0) + h, 2)
            hours_by_day[r["date"]] = round(hours_by_day.get(r["date"], 0) + day_hours, 2)
            total += day_hours

        return {
            "user_id": target, "period": period, "start_date": start_s, "end_date": end_s,
            "total_hours": round(total, 2), "updates_count": len(rows),
            "blocker_count": blocker_count, "hours_by_day": hours_by_day,
            "hours_by_project": hours_by_project,
        }
