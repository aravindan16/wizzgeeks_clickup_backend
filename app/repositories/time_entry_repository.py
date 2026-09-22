"""Data access for the `time_entries` collection (per-task worklog)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class TimeEntryRepository(BaseRepository):
    collection_name = "time_entries"

    async def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"task_id": to_object_id(task_id), "is_deleted": {"$ne": True}},
            limit=1000,
            sort=[("work_date", -1), ("created_at", -1)],
        )

    async def total_minutes_for_task(self, task_id: str) -> int:
        rows = await self.collection.aggregate([
            {"$match": {"task_id": to_object_id(task_id), "is_deleted": {"$ne": True}}},
            {"$group": {"_id": None, "total": {"$sum": "$minutes"}}},
        ]).to_list(length=1)
        return int(rows[0]["total"]) if rows else 0
