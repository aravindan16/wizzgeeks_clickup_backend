"""Data access for the `status_templates` collection (reusable status workflows)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class StatusTemplateRepository(BaseRepository):
    collection_name = "status_templates"

    async def list_for_owner(self, owner_id: str | None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if owner_id:
            query["owner_id"] = to_object_id(owner_id)
        return await self.find_many(query, limit=200, sort=[("created_at", -1)])
