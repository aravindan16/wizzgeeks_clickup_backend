"""Append-only audit/event store (`activity_logs`)."""
from typing import Any

from app.repositories.base import BaseRepository


class ActivityLogRepository(BaseRepository):
    collection_name = "activity_logs"

    async def record(self, entry: dict[str, Any]) -> None:
        await self.insert_one(entry)

    async def query(
        self, filters: dict[str, Any], *, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            filters, skip=skip, limit=limit, sort=[("created_at", -1)]
        )
