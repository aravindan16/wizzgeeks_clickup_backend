"""Data access for the `status_history` collection (task workflow audit)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class StatusHistoryRepository(BaseRepository):
    collection_name = "status_history"

    async def record(self, entry: dict[str, Any]) -> None:
        await self.insert_one(entry)

    async def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"task_id": to_object_id(task_id)}, limit=500, sort=[("created_at", 1)]
        )
