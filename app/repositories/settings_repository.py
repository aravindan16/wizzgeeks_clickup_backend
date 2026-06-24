"""Singleton organization settings document (`settings` collection, key='org')."""
from typing import Any

from app.repositories.base import BaseRepository

ORG_KEY = "org"


class SettingsRepository(BaseRepository):
    collection_name = "settings"

    async def get_org(self) -> dict[str, Any] | None:
        return await self.find_one({"key": ORG_KEY})

    async def upsert_org(self, values: dict[str, Any], when: Any) -> dict[str, Any]:
        await self.collection.update_one(
            {"key": ORG_KEY},
            {"$set": {**values, "updated_at": when},
             "$setOnInsert": {"key": ORG_KEY, "created_at": when}},
            upsert=True,
        )
        return await self.get_org()
