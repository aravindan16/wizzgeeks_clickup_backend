"""Data access for chat `conversations` (direct messages and group chats)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class ConversationRepository(BaseRepository):
    collection_name = "conversations"

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.insert_one(doc)

    async def list_for_member(self, user_id: str) -> list[dict[str, Any]]:
        """All conversations the user belongs to, most-recently-active first."""
        return await self.find_many(
            {"member_ids": to_object_id(user_id)},
            limit=200,
            sort=[("last_activity_at", -1)],
        )

    async def find_direct(self, a: str, b: str) -> dict[str, Any] | None:
        """The existing 1:1 conversation between two users, if any."""
        return await self.find_one({
            "type": "direct",
            "member_ids": {"$all": [to_object_id(a), to_object_id(b)], "$size": 2},
        })

    async def get_for_member(self, conv_id: str, user_id: str) -> dict[str, Any] | None:
        """A conversation the user is a member of (access-scoped)."""
        return await self.find_one({
            "_id": to_object_id(conv_id),
            "member_ids": to_object_id(user_id),
        })

    async def touch_last_message(self, conv_id: str, last_message: dict[str, Any], when: Any) -> None:
        await self.collection.update_one(
            {"_id": to_object_id(conv_id)},
            {"$set": {"last_message": last_message, "last_activity_at": when, "updated_at": when}},
        )

    async def set_read(self, conv_id: str, user_id: str, when: Any) -> None:
        await self.collection.update_one(
            {"_id": to_object_id(conv_id)},
            {"$set": {f"reads.{user_id}": when}},
        )

    async def add_members(self, conv_id: str, user_ids: list[str], when: Any) -> None:
        await self.collection.update_one(
            {"_id": to_object_id(conv_id)},
            {"$addToSet": {"member_ids": {"$each": [to_object_id(u) for u in user_ids]}},
             "$set": {"updated_at": when}},
        )

    async def rename(self, conv_id: str, name: str, when: Any) -> dict[str, Any] | None:
        return await self.update_by_id(conv_id, {"name": name, "updated_at": when})
