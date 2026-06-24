"""In-app notification endpoints."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUserDep, get_notification_service
from app.schemas.common import MessageResponse, ORMModel
from app.services.notification_service import NotificationService

router = APIRouter()

ServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


class NotificationResponse(ORMModel):
    id: str
    type: str
    title: str
    body: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    is_read: bool = False
    created_at: Any | None = None


class NotificationList(ORMModel):
    items: list[NotificationResponse]
    unread: int


@router.get("", response_model=NotificationList)
async def list_notifications(
    current: CurrentUserDep,
    service: ServiceDep,
    unread: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    items, unread_count = await service.list(current.id, unread_only=unread, skip=skip, limit=limit)
    mapped = [{**i, "id": i["_id"]} for i in items]
    return {"items": mapped, "unread": unread_count}


@router.patch("/{notification_id}/read", response_model=MessageResponse)
async def mark_read(notification_id: str, current: CurrentUserDep, service: ServiceDep):
    await service.mark_read(notification_id, current.id)
    return MessageResponse(message="Marked read")


@router.patch("/read-all", response_model=MessageResponse)
async def mark_all_read(current: CurrentUserDep, service: ServiceDep):
    count = await service.mark_all_read(current.id)
    return MessageResponse(message="Marked all read", details={"count": count})
