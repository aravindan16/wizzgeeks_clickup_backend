"""Data access for `workspaces`, `workspace_members`, `workspace_invitations`.

Scoped by organization_id directly (not via TenantScopedRepository) because they
define/precede the workspace context used by tenant-scoped data repositories.
"""
from typing import Any

from app.repositories.base import BaseRepository, to_object_id


class WorkspaceRepository(BaseRepository):
    collection_name = "workspaces"

    async def list_for_org(self, organization_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"organization_id": to_object_id(organization_id), "status": {"$ne": "deleted"}},
            limit=500, sort=[("created_at", 1)],
        )

    async def find_in_org(self, organization_id: str, workspace_id: str) -> dict[str, Any] | None:
        return await self.find_one({
            "_id": to_object_id(workspace_id),
            "organization_id": to_object_id(organization_id),
        })


class WorkspaceMemberRepository(BaseRepository):
    collection_name = "workspace_members"

    async def find_membership(self, workspace_id: str, user_id: str) -> dict[str, Any] | None:
        return await self.find_one({
            "workspace_id": to_object_id(workspace_id),
            "user_id": to_object_id(user_id),
            "removed_at": None,
        })

    async def list_for_workspace(self, workspace_id: str) -> list[dict[str, Any]]:
        return await self.find_many(
            {"workspace_id": to_object_id(workspace_id), "removed_at": None}, limit=2000
        )

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return await self.find_many({"user_id": to_object_id(user_id), "removed_at": None}, limit=500)

    async def add(self, *, organization_id: str, workspace_id: str, user_id: str,
                  workspace_role: str, added_by: str | None, when: Any) -> dict[str, Any]:
        return await self.insert_one({
            "organization_id": to_object_id(organization_id),
            "workspace_id": to_object_id(workspace_id),
            "user_id": to_object_id(user_id),
            "workspace_role": workspace_role,
            "added_by": to_object_id(added_by) if added_by else None,
            "added_at": when, "removed_at": None,
        })


class WorkspaceInvitationRepository(BaseRepository):
    collection_name = "workspace_invitations"

    async def find_by_token(self, token_hash: str) -> dict[str, Any] | None:
        return await self.find_one({"token_hash": token_hash})

    async def list_for_org(self, organization_id: str, status: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"organization_id": to_object_id(organization_id)}
        if status:
            query["status"] = status
        return await self.find_many(query, limit=500, sort=[("created_at", -1)])

    async def mark_status(self, invitation_id: Any, status: str, when: Any) -> None:
        await self.collection.update_one(
            {"_id": to_object_id(invitation_id)},
            {"$set": {"status": status, "accepted_at": when if status == "accepted" else None}},
        )
