"""Data access for the global `labels` collection.

Labels are workspace-wide (NOT scoped to a Space/List): a label created on any
task is reusable on every task, in any Space or List. `name_lower` is unique so
the same label is never duplicated.
"""
from typing import Any

from app.repositories.base import BaseRepository


class LabelRepository(BaseRepository):
    collection_name = "labels"

    async def list_all(self) -> list[dict[str, Any]]:
        return await self.find_many(
            {"is_deleted": {"$ne": True}}, skip=0, limit=1000, sort=[("name_lower", 1)]
        )

    async def find_by_name(self, name_lower: str) -> dict[str, Any] | None:
        return await self.find_one({"name_lower": name_lower, "is_deleted": {"$ne": True}})

    async def find_any_by_name(self, name_lower: str) -> dict[str, Any] | None:
        """Match by name INCLUDING soft-deleted rows (the unique index covers them)."""
        return await self.find_one({"name_lower": name_lower})
