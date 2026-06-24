"""Data access for the `task_assignments` collection (assignment history)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class TaskAssignmentRepository(BaseRepository):
    collection_name = "task_assignments"

    async def deactivate_active(self, task_id: str, when: Any) -> None:
        await self.collection.update_many(
            {"task_id": to_object_id(task_id), "is_active": True},
            {"$set": {"is_active": False, "unassigned_at": when}},
        )

    async def add(self, *, task_id: str, assignee_id: str, assigned_by: str | None,
                  when: Any) -> dict[str, Any]:
        return await self.insert_one(
            {
                "task_id": to_object_id(task_id),
                "assignee_id": to_object_id(assignee_id),
                "assigned_by": to_object_id(assigned_by) if assigned_by else None,
                "assigned_at": when,
                "unassigned_at": None,
                "is_active": True,
            }
        )

    async def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"task_id": to_object_id(task_id)}, limit=500, sort=[("assigned_at", 1)]
        )
