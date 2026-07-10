"""Business logic for the global Labels catalog.

Labels are workspace-wide and unique by (case-insensitive) name — creating a
label that already exists just returns the existing one (get-or-create). Each
label gets a stable colour for its chip. Tasks store labels by name.
"""
from __future__ import annotations  # `list` method shadows builtin in class body

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core.exceptions import NotFoundError, ValidationError
from app.repositories.label_repository import LabelRepository
from app.utils.datetime import utcnow

# Chip palette — a label's colour is derived from its name so it's stable.
_PALETTE = [
    "#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444",
    "#ec4899", "#8b5cf6", "#14b8a6", "#f97316", "#3b82f6",
]


def _color_for(name_lower: str) -> str:
    h = 0
    for ch in name_lower:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return _PALETTE[h % len(_PALETTE)]


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "color": doc.get("color") or "#6b7280",
        "created_at": doc.get("created_at"),
    }


class LabelService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = LabelRepository(db)

    async def list(self) -> list[dict[str, Any]]:
        return [_serialize(d) for d in await self.repo.list_all()]

    async def create(self, name: str, color: str | None = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Label name is required")
        if len(name) > 40:
            raise ValidationError("Label name is too long (max 40 chars)")
        name_lower = name.lower()

        existing = await self.repo.find_by_name(name_lower)
        if existing:
            return _serialize(existing)  # get-or-create — labels are unique

        # A soft-deleted label with this name still occupies the unique index — bring
        # it back instead of failing to insert a duplicate.
        deleted = await self.repo.find_any_by_name(name_lower)
        if deleted:
            restored = await self.repo.update_by_id(
                str(deleted["_id"]), {"is_deleted": False, "deleted_at": None, "updated_at": utcnow()})
            return _serialize(restored or deleted)

        now = utcnow()
        doc = {
            "name": name,
            "name_lower": name_lower,
            "color": color or _color_for(name_lower),
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            created = await self.repo.insert_one(doc)
        except DuplicateKeyError:
            # Raced with another create (or a soft-deleted row holds the name) — return
            # / restore the existing one.
            existing = await self.repo.find_any_by_name(name_lower)
            if not existing:
                raise ValidationError("Could not create label")
            if existing.get("is_deleted"):
                restored = await self.repo.update_by_id(
                    str(existing["_id"]), {"is_deleted": False, "deleted_at": None, "updated_at": utcnow()})
                return _serialize(restored or existing)
            return _serialize(existing)
        return _serialize(created)

    async def delete(self, label_id: str) -> None:
        ok = await self.repo.soft_delete_by_id(label_id, when=utcnow())
        if not ok:
            raise NotFoundError("Label not found")
