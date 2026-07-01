"""Business logic for user-defined dashboards (ClickUp-style boards with cards)."""
from __future__ import annotations  # `list` method shadows builtin in class body; defer annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import NotFoundError
from app.repositories.base import to_object_id
from app.repositories.user_dashboard_repository import UserDashboardRepository
from app.utils.datetime import utcnow


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", "Dashboard"),
        "cards": doc.get("cards", []) or [],
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


class UserDashboardService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = UserDashboardRepository(db)

    async def list(self, owner_id: str) -> list[dict[str, Any]]:
        rows = await self.repo.list_for_owner(owner_id)
        return [_serialize(r) for r in rows]

    async def get(self, dashboard_id: str, owner_id: str) -> dict[str, Any]:
        doc = await self.repo.get_for_owner(dashboard_id, owner_id)
        if not doc:
            raise NotFoundError("Dashboard not found")
        return _serialize(doc)

    async def create(self, owner_id: str, *, name: str, cards: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        now = utcnow()
        doc = {
            "owner_id": to_object_id(owner_id),
            "name": name.strip() or "Dashboard",
            "cards": cards or [],
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.repo.create(doc)
        return _serialize(created)

    async def update(self, dashboard_id: str, owner_id: str, *, name: str | None = None,
                     cards: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        update: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            update["name"] = name.strip() or "Dashboard"
        if cards is not None:
            update["cards"] = cards
        doc = await self.repo.update_for_owner(dashboard_id, owner_id, update)
        if not doc:
            raise NotFoundError("Dashboard not found")
        return _serialize(doc)

    async def delete(self, dashboard_id: str, owner_id: str) -> None:
        ok = await self.repo.soft_delete_for_owner(dashboard_id, owner_id, utcnow())
        if not ok:
            raise NotFoundError("Dashboard not found")
