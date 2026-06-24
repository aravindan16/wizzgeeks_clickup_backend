"""Data access for the `roles` collection."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class RoleRepository(BaseRepository):
    collection_name = "roles"

    async def find_by_key(self, key: str) -> dict[str, Any] | None:
        return await self.find_one({"key": key})

    async def find_by_keys(self, keys: list[str]) -> list[dict[str, Any]]:
        return await self.find_many({"key": {"$in": keys}}, limit=100)

    async def find_by_ids(self, ids: list[Any]) -> list[dict[str, Any]]:
        oids = [to_object_id(i) for i in ids]
        return await self.find_many({"_id": {"$in": oids}}, limit=100)

    async def list_all(self) -> list[dict[str, Any]]:
        return await self.find_many({}, limit=100, sort=[("level", -1)])

    async def upsert_system_role(self, role: dict[str, Any]) -> None:
        await self.collection.update_one(
            {"key": role["key"]},
            {
                "$set": {
                    "name": role["name"],
                    "level": role["level"],
                    "permissions": role["permissions"],
                    "is_system": True,
                },
                "$setOnInsert": {"created_at": role["created_at"]},
            },
            upsert=True,
        )
