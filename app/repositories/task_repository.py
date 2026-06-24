"""Data access for the `tasks` collection."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class TaskRepository(BaseRepository):
    collection_name = "tasks"

    async def list_tasks(
        self, query: dict[str, Any], *, skip: int, limit: int, sort: list[tuple[str, int]]
    ) -> list[dict[str, Any]]:
        return await self.find_many(query, skip=skip, limit=limit, sort=sort)

    async def adjust_comment_count(self, task_id: Any, delta: int) -> None:
        await self.collection.update_one(
            {"_id": to_object_id(task_id)}, {"$inc": {"comment_count": delta}}
        )

    async def add_watcher(self, task_id: Any, user_id: str) -> dict[str, Any] | None:
        return await self.collection.find_one_and_update(
            {"_id": to_object_id(task_id)},
            {"$addToSet": {"watchers": user_id}},
            return_document=True,
        )

    async def remove_watcher(self, task_id: Any, user_id: str) -> dict[str, Any] | None:
        return await self.collection.find_one_and_update(
            {"_id": to_object_id(task_id)},
            {"$pull": {"watchers": user_id}},
            return_document=True,
        )

    async def increment_actual_hours(self, task_id: Any, hours: float) -> dict[str, Any] | None:
        return await self.collection.find_one_and_update(
            {"_id": to_object_id(task_id)},
            {"$inc": {"actual_hours": hours}},
            return_document=True,
        )

    async def count_with(self, query: dict[str, Any]) -> int:
        return await self.count(query)

    # --- subtasks ---
    async def list_subtasks(self, parent_id: Any) -> list[dict[str, Any]]:
        return await self.find_many(
            {"parent_id": to_object_id(parent_id), "is_deleted": {"$ne": True}},
            limit=200, sort=[("created_at", 1)],
        )

    # --- issue links ---
    async def add_link(self, task_id: Any, target_id: Any, link_type: str) -> None:
        # Replace any existing link to the same target so the type stays current.
        await self.collection.update_one(
            {"_id": to_object_id(task_id)},
            {"$pull": {"links": {"task_id": to_object_id(target_id)}}},
        )
        await self.collection.update_one(
            {"_id": to_object_id(task_id)},
            {"$push": {"links": {"task_id": to_object_id(target_id), "type": link_type}}},
        )

    async def remove_link(self, task_id: Any, target_id: Any) -> None:
        await self.collection.update_one(
            {"_id": to_object_id(task_id)},
            {"$pull": {"links": {"task_id": to_object_id(target_id)}}},
        )
