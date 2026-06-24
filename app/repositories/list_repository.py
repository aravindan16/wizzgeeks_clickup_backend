"""Data access for the `lists` collection (Lists live inside a Space/project)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class ListRepository(BaseRepository):
    collection_name = "lists"

    async def list_for_space(self, space_id: str, *, include_archived: bool = True) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"space_id": to_object_id(space_id), "is_deleted": {"$ne": True}}
        if not include_archived:
            query["is_archived"] = {"$ne": True}
        return await self.find_many(query, limit=500, sort=[("order", 1), ("created_at", 1)])

    async def count_for_space(self, space_id: str) -> int:
        return await self.count({"space_id": to_object_id(space_id), "is_deleted": {"$ne": True}})

    async def first_for_space(self, space_id: str) -> dict[str, Any] | None:
        """The first (top, non-archived) List in a Space — used as the default list."""
        rows = await self.find_many(
            {"space_id": to_object_id(space_id), "is_deleted": {"$ne": True}, "is_archived": {"$ne": True}},
            limit=1, sort=[("order", 1), ("created_at", 1)],
        )
        return rows[0] if rows else None
