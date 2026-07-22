"""Data access for the `notifications` collection (per-recipient fan-out)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class NotificationRepository(BaseRepository):
    collection_name = "notifications"

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.insert_one(doc)

    def _scope(self, recipient_id: str, *, unread_only: bool = False,
               types: list[str] | None = None) -> dict[str, Any]:
        query: dict[str, Any] = {"recipient_id": to_object_id(recipient_id)}
        if unread_only:
            query["is_read"] = False
        if types:
            query["type"] = {"$in": types}
        return query

    async def list_for_recipient(
        self, recipient_id: str, *, unread_only: bool, skip: int, limit: int,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query = self._scope(recipient_id, unread_only=unread_only, types=types)
        return await self.find_many(query, skip=skip, limit=limit, sort=[("created_at", -1)])

    async def count_for_recipient(
        self, recipient_id: str, *, unread_only: bool = False, types: list[str] | None = None
    ) -> int:
        return await self.count(self._scope(recipient_id, unread_only=unread_only, types=types))

    async def count_unread(self, recipient_id: str) -> int:
        return await self.count({"recipient_id": to_object_id(recipient_id), "is_read": False})

    async def delete_one(self, notification_id: str, recipient_id: str) -> bool:
        result = await self.collection.delete_one(
            {"_id": to_object_id(notification_id), "recipient_id": to_object_id(recipient_id)},
        )
        return result.deleted_count == 1

    async def delete_all(self, recipient_id: str, *, unread_only: bool = False) -> int:
        result = await self.collection.delete_many(
            self._scope(recipient_id, unread_only=unread_only))
        return result.deleted_count

    async def mark_read(self, notification_id: str, recipient_id: str, when: Any) -> bool:
        result = await self.collection.update_one(
            {"_id": to_object_id(notification_id), "recipient_id": to_object_id(recipient_id)},
            {"$set": {"is_read": True, "read_at": when}},
        )
        return result.modified_count == 1

    async def mark_all_read(self, recipient_id: str, when: Any) -> int:
        result = await self.collection.update_many(
            {"recipient_id": to_object_id(recipient_id), "is_read": False},
            {"$set": {"is_read": True, "read_at": when}},
        )
        return result.modified_count
