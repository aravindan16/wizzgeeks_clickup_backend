"""Worklog (time tracking) for tasks: log / list / delete time entries.

Each entry records minutes spent by one user on one day. The task's `actual_hours`
is kept in sync as the sum of its live entries."""
from datetime import date
from typing import Any

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.time_entry_repository import TimeEntryRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow


def _serialize(e: dict[str, Any], user_name: str | None = None) -> dict[str, Any]:
    return {
        "_id": str(e["_id"]),
        "task_id": str(e["task_id"]),
        "user_id": str(e["user_id"]),
        "user_name": user_name,
        "minutes": e["minutes"],
        "work_date": e["work_date"],
        "note": e.get("note"),
        "created_at": e.get("created_at"),
    }


class TimeEntryService:
    def __init__(
        self,
        entries: TimeEntryRepository,
        tasks: TaskRepository,
        members: ProjectMemberRepository,
        users: UserRepository,
        audit: AuditService,
    ):
        self.entries = entries
        self.tasks = tasks
        self.members = members
        self.users = users
        self.audit = audit

    async def _task_or_404(self, task_id: str) -> dict[str, Any]:
        if not is_valid_object_id(task_id):
            raise NotFoundError("Task not found")
        task = await self.tasks.find_by_id(task_id)
        if not task or task.get("is_deleted"):
            raise NotFoundError("Task not found")
        return task

    async def _assert_member(self, project_id: str, actor: ActorContext) -> None:
        """Same rule as tasks: Space members only, unless elevated (project.update)."""
        if actor.has("project.update"):
            return
        if not actor.user_id or not await self.members.find_active(project_id, actor.user_id):
            raise PermissionDeniedError("You are not a member of this project")

    async def _sync_task_total(self, task_id: str) -> None:
        minutes = await self.entries.total_minutes_for_task(task_id)
        await self.tasks.update_by_id(task_id, {"actual_hours": round(minutes / 60, 2)})

    async def list_entries(self, task_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        task = await self._task_or_404(task_id)
        await self._assert_member(str(task["project_id"]), actor)
        rows = await self.entries.list_for_task(task_id)
        user_ids = list({r["user_id"] for r in rows})
        users = await self.users.find_many({"_id": {"$in": user_ids}}, limit=500, projection={"full_name": 1})
        names = {str(u["_id"]): u.get("full_name") for u in users}
        return [_serialize(r, names.get(str(r["user_id"]))) for r in rows]

    async def log_time(self, task_id: str, minutes: int, work_date: date, note: str | None,
                       actor: ActorContext) -> dict[str, Any]:
        task = await self._task_or_404(task_id)
        await self._assert_member(str(task["project_id"]), actor)
        now = utcnow()
        doc = {
            "task_id": to_object_id(task_id),
            "project_id": task["project_id"],
            "user_id": to_object_id(actor.user_id),
            "minutes": minutes,
            "work_date": work_date.isoformat(),
            "note": (note or "").strip() or None,
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.entries.insert_one(doc)
        await self._sync_task_total(task_id)
        await self.audit.log(actor_id=actor.user_id, action="task.time_logged", entity_type="task",
                             entity_id=task_id, metadata={"entry_id": str(created["_id"]), "minutes": minutes,
                                                          "work_date": doc["work_date"]}, ip=actor.ip)
        user = await self.users.find_safe_by_id(actor.user_id)
        return _serialize(created, user.get("full_name") if user else None)

    async def delete_entry(self, entry_id: str, actor: ActorContext) -> None:
        entry = await self.entries.find_by_id(entry_id) if is_valid_object_id(entry_id) else None
        if not entry or entry.get("is_deleted"):
            raise NotFoundError("Time entry not found")
        # Owners delete their own; managers/admins (project.update) may delete anyone's.
        if str(entry["user_id"]) != actor.user_id and not actor.has("project.update"):
            raise PermissionDeniedError("You can only delete your own time entries")
        task_id = str(entry["task_id"])
        await self.entries.update_by_id(entry["_id"], {"is_deleted": True, "deleted_at": utcnow()})
        await self._sync_task_total(task_id)
        await self.audit.log(actor_id=actor.user_id, action="task.time_deleted", entity_type="task",
                             entity_id=task_id, metadata={"entry_id": entry_id, "minutes": entry["minutes"]},
                             ip=actor.ip)
