"""Data access for the `project_members` collection (many-to-many)."""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class ProjectMemberRepository(BaseRepository):
    collection_name = "project_members"

    async def find_active(self, project_id: str, user_id: str) -> dict[str, Any] | None:
        return await self.find_one(
            {
                "project_id": to_object_id(project_id),
                "user_id": to_object_id(user_id),
                "removed_at": None,
            }
        )

    async def list_active_by_project(self, project_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"project_id": to_object_id(project_id), "removed_at": None},
            limit=500,
            sort=[("added_at", 1)],
        )

    async def count_active_by_project(self, project_id: str) -> int:
        return await self.count({"project_id": to_object_id(project_id), "removed_at": None})

    async def list_projects_for_user(self, user_id: str) -> list[Any]:
        rows = await self.find_many(
            {"user_id": to_object_id(user_id), "removed_at": None}, limit=500
        )
        return [r["project_id"] for r in rows]

    async def add(self, *, project_id: str, user_id: str, project_role: str,
                  added_by: str, added_at: Any) -> dict[str, Any]:
        return await self.insert_one(
            {
                "project_id": to_object_id(project_id),
                "user_id": to_object_id(user_id),
                "project_role": project_role,
                "added_by": to_object_id(added_by) if added_by else None,
                "added_at": added_at,
                "removed_at": None,
            }
        )

    async def update_role(self, member_id: Any, project_role: str) -> dict[str, Any] | None:
        return await self.update_by_id(member_id, {"project_role": project_role})

    async def remove(self, project_id: str, user_id: str, when: Any) -> bool:
        result = await self.collection.update_one(
            {
                "project_id": to_object_id(project_id),
                "user_id": to_object_id(user_id),
                "removed_at": None,
            },
            {"$set": {"removed_at": when}},
        )
        return result.modified_count == 1
