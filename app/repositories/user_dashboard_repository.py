"""Data access for the `user_dashboards` collection (per-owner ClickUp-style boards)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class UserDashboardRepository(BaseRepository):
    collection_name = "user_dashboards"

    async def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        return await self.insert_one(doc)

    async def list_for_owner(self, owner_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"owner_id": to_object_id(owner_id), "is_deleted": {"$ne": True}},
            skip=0, limit=500, sort=[("created_at", 1)],
        )

    async def get_for_owner(self, dashboard_id: str, owner_id: str) -> dict[str, Any] | None:
        try:
            oid = to_object_id(dashboard_id)
        except Exception:
            return None
        return await self.find_one({"_id": oid, "owner_id": to_object_id(owner_id), "is_deleted": {"$ne": True}})

    async def update_for_owner(self, dashboard_id: str, owner_id: str, update: dict[str, Any]) -> dict[str, Any] | None:
        return await self.update_one(
            {"_id": to_object_id(dashboard_id), "owner_id": to_object_id(owner_id), "is_deleted": {"$ne": True}},
            {"$set": update},
        )

    async def soft_delete_for_owner(self, dashboard_id: str, owner_id: str, when: Any) -> bool:
        result = await self.collection.update_one(
            {"_id": to_object_id(dashboard_id), "owner_id": to_object_id(owner_id), "is_deleted": {"$ne": True}},
            {"$set": {"is_deleted": True, "deleted_at": when}},
        )
        return result.modified_count == 1
