"""Per-user "starred" store (`starred_items` collection).

Each user stars items (currently spaces) independently. Keyed by
(user_id, entity_type, entity_id) so a star is unique per user per entity.
"""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class StarredRepository(BaseRepository):
    collection_name = "starred_items"

    async def star(self, user_id: str, item: dict[str, Any], now: Any) -> None:
        uid = to_object_id(user_id)
        await self.collection.update_one(
            {"user_id": uid, "entity_type": item["entity_type"], "entity_id": item["entity_id"]},
            {
                "$set": {
                    "path": item["path"],
                    "name": item["name"],
                    "icon": item.get("icon") or "📁",
                    "starred_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    async def unstar(self, user_id: str, entity_type: str, entity_id: str) -> bool:
        result = await self.collection.delete_one(
            {"user_id": to_object_id(user_id), "entity_type": entity_type, "entity_id": entity_id}
        )
        return result.deleted_count == 1

    async def list_for_user(self, user_id: str, entity_type: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"user_id": to_object_id(user_id)}
        if entity_type:
            query["entity_type"] = entity_type
        return await self.collection.find(query).sort("starred_at", -1).to_list(length=200)
