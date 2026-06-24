"""Data access for the `custom_fields` collection.

A custom field is scoped either to a Space (applies to all its Lists) or to a
single List. Tasks store values keyed by field id (handled elsewhere).
"""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class CustomFieldRepository(BaseRepository):
    collection_name = "custom_fields"

    async def list_for_space(self, space_id: str) -> list[dict[str, Any]]:
        """Space-scoped fields only."""
        return await self.find_many(
            {"space_id": to_object_id(space_id), "scope": "space", "is_deleted": {"$ne": True}},
            limit=500, sort=[("order", 1), ("created_at", 1)],
        )

    async def list_for_list(self, list_id: str) -> list[dict[str, Any]]:
        """List-scoped fields only."""
        return await self.find_many(
            {"list_id": to_object_id(list_id), "scope": "list", "is_deleted": {"$ne": True}},
            limit=500, sort=[("order", 1), ("created_at", 1)],
        )

    async def list_all_in_space(self, space_id: str) -> list[dict[str, Any]]:
        """Every field anywhere under a space (space-scoped + all its lists)."""
        return await self.find_many(
            {"space_id": to_object_id(space_id), "is_deleted": {"$ne": True}},
            limit=1000, sort=[("created_at", 1)],
        )
