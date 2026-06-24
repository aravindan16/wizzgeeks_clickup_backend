"""Data access for `organizations` and `organization_members`.

These are NOT TenantScopedRepository: organizations define the tenant boundary,
and a user lists their orgs across tenants (filtered by user_id, not org_id).
"""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class OrganizationRepository(BaseRepository):
    collection_name = "organizations"

    async def find_by_slug(self, slug: str) -> dict[str, Any] | None:
        return await self.find_one({"slug": slug})


class OrganizationMemberRepository(BaseRepository):
    collection_name = "organization_members"

    async def find_membership(self, organization_id: str, user_id: str) -> dict[str, Any] | None:
        return await self.find_one({
            "organization_id": to_object_id(organization_id),
            "user_id": to_object_id(user_id),
            "status": "active",
        })

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"user_id": to_object_id(user_id), "status": "active"}, limit=200
        )

    async def list_for_org(self, organization_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"organization_id": to_object_id(organization_id), "status": "active"}, limit=2000
        )

    async def add(self, *, organization_id: str, user_id: str, org_role: str, when: Any) -> dict[str, Any]:
        return await self.insert_one({
            "organization_id": to_object_id(organization_id),
            "user_id": to_object_id(user_id),
            "org_role": org_role,
            "status": "active",
            "joined_at": when,
        })
