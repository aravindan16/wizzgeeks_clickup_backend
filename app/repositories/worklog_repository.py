"""Data access for the `worklogs` collection (individual time-log entries per task)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class WorklogRepository(BaseRepository):
    collection_name = "worklogs"

    async def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"task_id": to_object_id(task_id)}, limit=500, sort=[("created_at", 1)]
        )
