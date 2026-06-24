"""Audit log viewer (admin)."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.api.deps import get_audit_service, require
from app.schemas.common import ORMModel, PaginatedResponse
from app.services.audit_service import AuditService

router = APIRouter()


class AuditLogResponse(ORMModel):
    id: str = Field(alias="_id")
    actor_id: str | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    metadata: dict[str, Any] = {}
    ip: str | None = None
    created_at: Any | None = None


@router.get("/audit-logs", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    service: Annotated[AuditService, Depends(get_audit_service)],
    _: Annotated[object, Depends(require("audit.read"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
):
    items, total = await service.list_logs(
        skip=skip,
        limit=limit,
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)
