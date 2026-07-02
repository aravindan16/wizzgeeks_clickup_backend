"""Business logic for personal saved filters (the Filters page).

Owner-scoped: each user only sees/edits/deletes their own filters. The filter
tree (`cards`) and cross-card conjunction (`conj`) are stored verbatim as the
frontend produces them — the backend does not interpret them.
"""
from __future__ import annotations  # `list` method shadows builtin in class body; defer annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import NotFoundError
from app.repositories.base import to_object_id
from app.repositories.saved_filter_repository import SavedFilterRepository
from app.repositories.user_repository import UserRepository
from app.utils.datetime import utcnow


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", "Filter"),
        "cards": doc.get("cards", []) or [],
        "conj": doc.get("conj", "AND"),
        "owner_id": str(doc["owner_id"]) if doc.get("owner_id") else None,
        "owner_name": doc.get("owner_name"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


class SavedFilterService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = SavedFilterRepository(db)
        self.users = UserRepository(db)

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self.repo.list_for_user(user_id)
        return [_serialize(r) for r in rows]

    async def get(self, filter_id: str, user_id: str) -> dict[str, Any]:
        doc = await self.repo.get_for_user(filter_id, user_id)
        if not doc:
            raise NotFoundError("Filter not found")
        return _serialize(doc)

    async def create(self, owner_id: str, *, name: str, cards: list[dict[str, Any]] | None = None,
                     conj: str = "AND") -> dict[str, Any]:
        owner = await self.users.find_safe_by_id(owner_id)
        now = utcnow()
        doc = {
            "owner_id": to_object_id(owner_id),
            "owner_name": (owner or {}).get("full_name"),
            "name": name.strip() or "Filter",
            "cards": cards or [],
            "conj": conj if conj in ("AND", "OR") else "AND",
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.repo.create(doc)
        return _serialize(created)

    async def update(self, filter_id: str, user_id: str, *, name: str | None = None,
                     cards: list[dict[str, Any]] | None = None, conj: str | None = None) -> dict[str, Any]:
        update: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            update["name"] = name.strip() or "Filter"
        if cards is not None:
            update["cards"] = cards
        if conj is not None:
            update["conj"] = conj if conj in ("AND", "OR") else "AND"
        doc = await self.repo.update_for_user(filter_id, user_id, update)
        if not doc:
            raise NotFoundError("Filter not found")
        return _serialize(doc)

    async def delete(self, filter_id: str, user_id: str) -> None:
        ok = await self.repo.soft_delete_for_user(filter_id, user_id, utcnow())
        if not ok:
            raise NotFoundError("Filter not found")
