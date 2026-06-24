"""Data access for the `notifications` collection (per-recipient fan-out)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class NotificationRepository(BaseRepository):
    collection_name = "notifications"

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.insert_one(doc)

    async def list_for_recipient(
        self, recipient_id: str, *, unread_only: bool, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"recipient_id": to_object_id(recipient_id)}
        if unread_only:
            query["is_read"] = False
        return await self.find_many(query, skip=skip, limit=limit, sort=[("created_at", -1)])

    async def count_unread(self, recipient_id: str) -> int:
        return await self.count({"recipient_id": to_object_id(recipient_id), "is_read": False})

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
