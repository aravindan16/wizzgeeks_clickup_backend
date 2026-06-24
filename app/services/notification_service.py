"""Notification business logic (in-app fan-out)."""
from typing import Any

from app.core.exceptions import NotFoundError
from app.repositories.base import to_object_id
from app.repositories.notification_repository import NotificationRepository
from app.utils.datetime import utcnow


def _serialize(n: dict[str, Any]) -> dict[str, Any]:
    out = dict(n)
    out["_id"] = str(n["_id"])
    out["recipient_id"] = str(n["recipient_id"])
    if n.get("entity_id"):
        out["entity_id"] = str(n["entity_id"])
    return out


class NotificationService:
    def __init__(self, repo: NotificationRepository):
        self.repo = repo

    async def notify(
        self,
        *,
        recipient_id: str,
        type: str,
        title: str,
        body: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        await self.repo.create({
            "recipient_id": to_object_id(recipient_id),
            "type": type,
            "title": title,
            "body": body,
            "entity_type": entity_type,
            "entity_id": to_object_id(entity_id) if entity_id else None,
            "is_read": False,
            "channels": ["in_app"],
            "created_at": utcnow(),
            "read_at": None,
        })

    async def list(self, recipient_id: str, *, unread_only: bool, skip: int, limit: int):
        items = await self.repo.list_for_recipient(
            recipient_id, unread_only=unread_only, skip=skip, limit=limit
        )
        unread = await self.repo.count_unread(recipient_id)
        return [_serialize(i) for i in items], unread

    async def mark_read(self, notification_id: str, recipient_id: str) -> None:
        ok = await self.repo.mark_read(notification_id, recipient_id, utcnow())
        if not ok:
            raise NotFoundError("Notification not found")

    async def mark_all_read(self, recipient_id: str) -> int:
        return await self.repo.mark_all_read(recipient_id, utcnow())
