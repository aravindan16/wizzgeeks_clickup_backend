"""Per-user "recently visited" store (`recent_items` collection).

Each user has their own list. Records are deduped by (user_id, path) and capped
at LIMIT most-recent entries.
"""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id

LIMIT = 10


class RecentRepository(BaseRepository):
    collection_name = "recent_items"

    async def record(self, user_id: str, item: dict[str, Any], now: Any) -> None:
        uid = to_object_id(user_id)
        # Upsert dedupes by (user_id, path) and refreshes the timestamp.
        await self.collection.update_one(
            {"user_id": uid, "path": item["path"]},
            {
                "$set": {
                    "name": item["name"],
                    "type": item.get("type") or "Page",
                    "icon": item.get("icon") or "📄",
                    "visited_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        # Trim anything beyond the most-recent LIMIT.
        extra = await self.collection.find({"user_id": uid}).sort("visited_at", -1) \
            .skip(LIMIT).to_list(length=None)
        if extra:
            await self.collection.delete_many({"_id": {"$in": [e["_id"] for e in extra]}})

    async def list_for_user(self, user_id: str, limit: int = LIMIT) -> list[dict[str, Any]]:
        uid = to_object_id(user_id)
        return await self.collection.find({"user_id": uid}).sort("visited_at", -1) \
            .limit(limit).to_list(length=limit)

    async def clear(self, user_id: str) -> None:
        await self.collection.delete_many({"user_id": to_object_id(user_id)})
