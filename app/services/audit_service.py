"""Audit logging business logic.

Writes are best-effort: an audit failure must never break the primary operation,
so `log()` swallows its own errors (and logs them) rather than propagating.
"""
import logging
from typing import Any

from app.repositories.activity_log_repository import ActivityLogRepository
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)


def _serialize(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    out["_id"] = str(entry["_id"])
    return out


class AuditService:
    def __init__(self, repo: ActivityLogRepository):
        self.repo = repo

    async def log(
        self,
        *,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        metadata: dict[str, Any] | None = None,
        ip: str | None = None,
    ) -> None:
        try:
            await self.repo.record(
                {
                    "actor_id": actor_id,
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "metadata": metadata or {},
                    "ip": ip,
                    "created_at": utcnow(),
                }
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write audit log for action=%s", action)

    async def list_logs(
        self,
        *,
        skip: int,
        limit: int,
        actor_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        action: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        filters: dict[str, Any] = {}
        if actor_id:
            filters["actor_id"] = actor_id
        if entity_type:
            filters["entity_type"] = entity_type
        if entity_id:
            filters["entity_id"] = entity_id
        if action:
            filters["action"] = action
        items = await self.repo.query(filters, skip=skip, limit=limit)
        total = await self.repo.count(filters)
        return [_serialize(i) for i in items], total
