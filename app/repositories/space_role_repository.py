"""Data access for the `space_roles` collection (custom per-space roles)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class SpaceRoleRepository(BaseRepository):
    collection_name = "space_roles"

    async def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"project_id": to_object_id(project_id), "is_deleted": {"$ne": True}},
            sort=[("created_at", 1)],
        )
