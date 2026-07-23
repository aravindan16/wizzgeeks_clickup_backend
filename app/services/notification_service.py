"""Notification business logic (in-app fan-out)."""
from typing import Any, Iterable

from app.core.exceptions import NotFoundError
from app.realtime.hub import hub
from app.repositories.base import to_object_id
from app.repositories.notification_repository import NotificationRepository
from app.utils.datetime import utcnow

# Named filters used by the drawer → the notification `type`s they include.
# "all" / "unread" are handled separately (no / is_read scope).
FILTER_TYPES: dict[str, list[str]] = {
    "mentions": ["comment.mention"],
    "comments": ["comment.added"],
    "assignments": ["task.assigned"],
    "tasks": ["task.assigned", "task.status_changed"],
}


def _serialize(n: dict[str, Any]) -> dict[str, Any]:
    out = dict(n)
    out["_id"] = str(n["_id"])
    out["recipient_id"] = str(n["recipient_id"])
    if n.get("entity_id"):
        out["entity_id"] = str(n["entity_id"])
    if n.get("actor_id"):
        out["actor_id"] = str(n["actor_id"])
    return out


class NotificationService:
    def __init__(self, repo: NotificationRepository):
        self.repo = repo

    @staticmethod
    def actor_fields(actor_id: str | None, user: dict[str, Any] | None) -> dict[str, Any]:
        """Denormalize the acting user's name/avatar for the notification card."""
        return {
            "actor_id": actor_id,
            "actor_name": (user or {}).get("full_name"),
            "actor_avatar_url": (user or {}).get("avatar_url"),
            "actor_avatar_color": (user or {}).get("avatar_color"),
        }

    async def notify(
        self,
        *,
        recipient_id: str,
        type: str,
        title: str,
        body: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        entity_key: str | None = None,
        entity_title: str | None = None,
        actor_id: str | None = None,
        actor_name: str | None = None,
        actor_avatar_url: str | None = None,
        actor_avatar_color: str | None = None,
    ) -> None:
        created = await self.repo.create({
            "recipient_id": to_object_id(recipient_id),
            "type": type,
            "title": title,
            "body": body,
            "entity_type": entity_type,
            "entity_id": to_object_id(entity_id) if entity_id else None,
            "entity_key": entity_key,      # e.g. "PROJ-12" — the task name/key shown on the card
            "entity_title": entity_title,  # e.g. "Implement Dashboard"
            "actor_id": to_object_id(actor_id) if actor_id else None,
            "actor_name": actor_name,
            "actor_avatar_url": actor_avatar_url,
            "actor_avatar_color": actor_avatar_color,
            "is_read": False,
            "channels": ["in_app"],
            "created_at": utcnow(),
            "read_at": None,
        })
        # Realtime push to the recipient's open sockets (best-effort; a WS failure
        # must never break notification creation).
        try:
            data = _serialize(created)
            data["id"] = data["_id"]
            # ws.send_json uses plain json.dumps, which can't encode datetimes —
            # send them as ISO strings (the client parses them with `new Date()`).
            for k in ("created_at", "read_at"):
                v = data.get(k)
                if hasattr(v, "isoformat"):
                    data[k] = v.isoformat()
            await hub.push(str(recipient_id), {"event": "notification.created", "data": data})
        except Exception:  # noqa: BLE001
            pass

    async def notify_many(self, recipient_ids: Iterable[str], *, exclude: str | None = None, **kwargs) -> None:
        """Fan out one notification to a set of recipients (deduped; never to `exclude`/self)."""
        seen: set[str] = set()
        for rid in recipient_ids:
            if not rid:
                continue
            rid = str(rid)
            if rid == exclude or rid in seen:
                continue
            seen.add(rid)
            await self.notify(recipient_id=rid, **kwargs)

    async def list(self, recipient_id: str, *, filter: str | None, skip: int, limit: int):
        unread_only = filter == "unread"
        types = FILTER_TYPES.get(filter or "")
        items = await self.repo.list_for_recipient(
            recipient_id, unread_only=unread_only, skip=skip, limit=limit, types=types,
        )
        total = await self.repo.count_for_recipient(
            recipient_id, unread_only=unread_only, types=types)
        unread = await self.repo.count_unread(recipient_id)
        return [_serialize(i) for i in items], unread, total

    async def unread_count(self, recipient_id: str) -> int:
        return await self.repo.count_unread(recipient_id)

    async def mark_read(self, notification_id: str, recipient_id: str) -> None:
        ok = await self.repo.mark_read(notification_id, recipient_id, utcnow())
        if not ok:
            raise NotFoundError("Notification not found")

    async def mark_all_read(self, recipient_id: str) -> int:
        return await self.repo.mark_all_read(recipient_id, utcnow())

    async def delete(self, notification_id: str, recipient_id: str) -> None:
        ok = await self.repo.delete_one(notification_id, recipient_id)
        if not ok:
            raise NotFoundError("Notification not found")

    async def clear_all(self, recipient_id: str) -> int:
        return await self.repo.delete_all(recipient_id)
