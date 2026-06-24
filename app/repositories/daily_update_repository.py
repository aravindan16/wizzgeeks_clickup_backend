"""Data access for the `daily_updates` collection."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class DailyUpdateRepository(BaseRepository):
    collection_name = "daily_updates"

    async def find_by_user_date(self, user_id: str, date: str) -> dict[str, Any] | None:
        return await self.find_one({"user_id": to_object_id(user_id), "date": date})

    async def list_updates(
        self, query: dict[str, Any], *, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            query, skip=skip, limit=limit, sort=[("date", -1), ("created_at", -1)]
        )

    async def find_range(self, user_id: str, start: str, end: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"user_id": to_object_id(user_id), "date": {"$gte": start, "$lte": end}},
            limit=400,
            sort=[("date", 1)],
        )

    async def find_for_users_on_date(self, user_ids: list[Any], date: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"user_id": {"$in": user_ids}, "date": date}, limit=1000
        )
