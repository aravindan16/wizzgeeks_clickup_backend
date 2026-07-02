"""Data access for the `saved_filters` collection.

A saved filter is a personal, owner-scoped ClickUp-style task filter (the
Filters page). It stores the filter builder tree (`cards`) and the cross-card
conjunction (`conj`). Only the owner can see/edit/delete their filters.
"""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class SavedFilterRepository(BaseRepository):
    collection_name = "saved_filters"

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.insert_one(doc)

    def _owned(self, user_id: str) -> dict[str, Any]:
        return {"owner_id": to_object_id(user_id), "is_deleted": {"$ne": True}}

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return await self.find_many(self._owned(user_id), skip=0, limit=500, sort=[("created_at", 1)])

    async def get_for_user(self, filter_id: str, user_id: str) -> dict[str, Any] | None:
        try:
            oid = to_object_id(filter_id)
        except Exception:
            return None
        return await self.find_one({"_id": oid, **self._owned(user_id)})

    async def update_for_user(self, filter_id: str, user_id: str, update: dict[str, Any]) -> dict[str, Any] | None:
        return await self.update_one({"_id": to_object_id(filter_id), **self._owned(user_id)}, {"$set": update})

    async def soft_delete_for_user(self, filter_id: str, user_id: str, when: Any) -> bool:
        result = await self.collection.update_one(
            {"_id": to_object_id(filter_id), **self._owned(user_id)},
            {"$set": {"is_deleted": True, "deleted_at": when}},
        )
        return result.modified_count == 1
