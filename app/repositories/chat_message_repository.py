"""Data access for chat `chat_messages`."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class ChatMessageRepository(BaseRepository):
    collection_name = "chat_messages"

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.insert_one(doc)

    async def list_for_conversation(
        self, conversation_id: str, *, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        """Newest-first page of messages (the client reverses for display)."""
        return await self.find_many(
            {"conversation_id": to_object_id(conversation_id)},
            skip=skip, limit=limit, sort=[("created_at", -1)],
        )

    async def count_for_conversation(self, conversation_id: str) -> int:
        return await self.count({"conversation_id": to_object_id(conversation_id)})

    async def count_unread(self, conversation_id: str, user_id: str, since: Any) -> int:
        """Messages the user hasn't read: newer than `since` and not sent by them."""
        query: dict[str, Any] = {
            "conversation_id": to_object_id(conversation_id),
            "sender_id": {"$ne": to_object_id(user_id)},
        }
        if since is not None:
            query["created_at"] = {"$gt": since}
        return await self.count(query)

    async def list_pinned(self, conversation_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"conversation_id": to_object_id(conversation_id), "pinned": True},
            limit=100, sort=[("pinned_at", -1)])

    async def list_bookmarked(self, user_id: str) -> list[dict[str, Any]]:
        """A user's saved messages across all conversations (newest first)."""
        return await self.find_many(
            {"bookmarked_by": user_id}, limit=200, sort=[("created_at", -1)])
