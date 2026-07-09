"""Business logic for user-defined dashboards (ClickUp-style boards with cards).

Dashboards are owned by a user and can be shared with members (a user id array
on the doc). Owner ∪ members can view/use; only the owner deletes or shares.
"""
from __future__ import annotations  # `list` method shadows builtin in class body; defer annotations

import re
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.base import to_object_id
from app.repositories.user_dashboard_repository import UserDashboardRepository
from app.repositories.user_repository import UserRepository
from app.utils.datetime import utcnow


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", "Dashboard"),
        "cards": doc.get("cards", []) or [],
        "owner_id": str(doc["owner_id"]) if doc.get("owner_id") else None,
        "member_ids": [str(m) for m in (doc.get("members") or [])],
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


class UserDashboardService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = UserDashboardRepository(db)
        self.users = UserRepository(db)

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self.repo.list_for_user(user_id)
        return [_serialize(r) for r in rows]

    async def get(self, dashboard_id: str, user_id: str) -> dict[str, Any]:
        doc = await self.repo.get_for_user(dashboard_id, user_id)
        if not doc:
            raise NotFoundError("Dashboard not found")
        return _serialize(doc)

    async def _name_taken(self, owner_id: str, name: str, exclude_id: str | None = None) -> bool:
        query: dict[str, Any] = {
            "owner_id": to_object_id(owner_id),
            "name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"},
            "is_deleted": {"$ne": True},
        }
        if exclude_id:
            query["_id"] = {"$ne": to_object_id(exclude_id)}
        return await self.repo.find_one(query) is not None

    async def create(self, owner_id: str, *, name: str, cards: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if await self._name_taken(owner_id, name):
            raise ConflictError("A dashboard with this name already exists")
        now = utcnow()
        doc = {
            "owner_id": to_object_id(owner_id),
            "name": name.strip() or "Dashboard",
            "cards": cards or [],
            "members": [],
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.repo.create(doc)
        return _serialize(created)

    async def update(self, dashboard_id: str, user_id: str, *, name: str | None = None,
                     cards: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        update: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            if await self._name_taken(user_id, name, exclude_id=dashboard_id):
                raise ConflictError("A dashboard with this name already exists")
            update["name"] = name.strip() or "Dashboard"
        if cards is not None:
            update["cards"] = cards
        doc = await self.repo.update_for_user(dashboard_id, user_id, update)
        if not doc:
            raise NotFoundError("Dashboard not found")
        return _serialize(doc)

    async def delete(self, dashboard_id: str, owner_id: str) -> None:
        ok = await self.repo.soft_delete_for_owner(dashboard_id, owner_id, utcnow())
        if not ok:
            raise NotFoundError("Dashboard not found")

    # --- user directory (for the share picker; any authenticated user) ---
    async def search_users(self, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        q = (query or "").strip()
        match: dict[str, Any] = {"is_deleted": {"$ne": True}, "status": "active"}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            match["$or"] = [{"full_name": rx}, {"email": rx}]
        users = await self.users.find_many(match, limit=limit, sort=[("full_name", 1)],
                                           projection={"full_name": 1, "email": 1})
        return [{"user_id": str(u["_id"]), "full_name": u.get("full_name"), "email": u.get("email"), "is_owner": False}
                for u in users]

    # --- members ---
    def _member_view(self, user: dict[str, Any] | None, uid: str, *, is_owner: bool) -> dict[str, Any]:
        return {
            "user_id": uid,
            "full_name": user.get("full_name") if user else None,
            "email": user.get("email") if user else None,
            "is_owner": is_owner,
        }

    async def list_members(self, dashboard_id: str, user_id: str) -> list[dict[str, Any]]:
        doc = await self.repo.get_for_user(dashboard_id, user_id)
        if not doc:
            raise NotFoundError("Dashboard not found")
        owner_id = str(doc["owner_id"])
        member_ids = [str(m) for m in (doc.get("members") or [])]
        ids = [owner_id, *member_ids]
        users = await self.users.find_many({"_id": {"$in": [to_object_id(i) for i in ids]}},
                                           limit=500, projection={"password_hash": 0})
        by_id = {str(u["_id"]): u for u in users}
        return [self._member_view(by_id.get(i), i, is_owner=(i == owner_id)) for i in ids]

    async def add_member(self, dashboard_id: str, owner_id: str, *, member_user_id: str) -> list[dict[str, Any]]:
        user = await self.users.find_safe_by_id(member_user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        if str(user["_id"]) == owner_id:
            raise ConflictError("Owner is already on the dashboard")
        ok = await self.repo.add_member(dashboard_id, owner_id, member_user_id)
        if not ok:
            raise NotFoundError("Dashboard not found")
        return await self.list_members(dashboard_id, owner_id)

    async def remove_member(self, dashboard_id: str, owner_id: str, member_user_id: str) -> list[dict[str, Any]]:
        ok = await self.repo.remove_member(dashboard_id, owner_id, member_user_id)
        if not ok:
            raise NotFoundError("Dashboard not found")
        return await self.list_members(dashboard_id, owner_id)
