"""Data access for the `comments` collection."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class CommentRepository(BaseRepository):
    collection_name = "comments"

    async def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {
                "entity_type": "task",
                "entity_id": to_object_id(task_id),
                "is_deleted": {"$ne": True},
            },
            limit=500,
            sort=[("created_at", 1)],
        )

    async def count_for_task(self, task_id: str) -> int:
        return await self.count(
            {"entity_type": "task", "entity_id": to_object_id(task_id), "is_deleted": {"$ne": True}}
        )
