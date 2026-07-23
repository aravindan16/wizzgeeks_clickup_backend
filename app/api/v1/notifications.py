"""In-app notification endpoints (recipient-scoped: a user only sees their own)."""
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from jose import JWTError

from app.api.deps import CurrentUserDep, get_notification_service, get_user_repo
from app.core.security import decode_token
from app.realtime.hub import hub
from app.repositories.user_repository import UserRepository
from app.schemas.common import MessageResponse, ORMModel
from app.services.notification_service import NotificationService

router = APIRouter()

ServiceDep = Annotated[NotificationService, Depends(get_notification_service)]

# Drawer filter tabs → passed straight to the service.
FilterParam = Literal["all", "unread", "mentions", "tasks", "comments", "assignments"]


class NotificationResponse(ORMModel):
    id: str
    type: str
    title: str
    body: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    entity_key: str | None = None
    entity_title: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_avatar_url: str | None = None
    actor_avatar_color: str | None = None
    is_read: bool = False
    created_at: Any | None = None
    read_at: Any | None = None


class NotificationList(ORMModel):
    items: list[NotificationResponse]
    unread: int
    total: int


@router.get("", response_model=NotificationList)
async def list_notifications(
    current: CurrentUserDep,
    service: ServiceDep,
    filter: FilterParam = "all",
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    items, unread_count, total = await service.list(
        current.id, filter=filter, skip=skip, limit=limit)
    mapped = [{**i, "id": i["_id"]} for i in items]
    return {"items": mapped, "unread": unread_count, "total": total}


@router.get("/unread-count")
async def unread_count(current: CurrentUserDep, service: ServiceDep):
    return {"unread": await service.unread_count(current.id)}


@router.patch("/read-all", response_model=MessageResponse)
async def mark_all_read(current: CurrentUserDep, service: ServiceDep):
    count = await service.mark_all_read(current.id)
    return MessageResponse(message="Marked all read", details={"count": count})


@router.patch("/{notification_id}/read", response_model=MessageResponse)
async def mark_read(notification_id: str, current: CurrentUserDep, service: ServiceDep):
    await service.mark_read(notification_id, current.id)
    return MessageResponse(message="Marked read")


@router.delete("", response_model=MessageResponse)
async def clear_all(current: CurrentUserDep, service: ServiceDep):
    count = await service.clear_all(current.id)
    return MessageResponse(message="Cleared", details={"count": count})


@router.delete("/{notification_id}", response_model=MessageResponse)
async def delete_notification(notification_id: str, current: CurrentUserDep, service: ServiceDep):
    await service.delete(notification_id, current.id)
    return MessageResponse(message="Deleted")


async def _ws_user_id(token: str | None, users: UserRepository) -> str | None:
    """Authenticate a WS handshake from the `?token=` access token (no header on WS)."""
    if not token:
        return None
    try:
        payload = decode_token(token)
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    user = await users.find_safe_by_id(payload.get("sub"))
    if not user or user.get("is_deleted") or user.get("status") != "active":
        return None
    return str(user["_id"])


@router.websocket("/ws")
async def notifications_ws(
    websocket: WebSocket,
    token: str | None = Query(None),
    users: UserRepository = Depends(get_user_repo),
):
    """Realtime channel: pushes each new notification to the recipient's open sockets.
    Auth via `?token=<access token>` (query param, since WS carries no auth header)."""
    user_id = await _ws_user_id(token, users)
    if not user_id:
        await websocket.close(code=4401)  # reject the handshake (unauthorized)
        return
    await websocket.accept()
    await hub.connect(user_id, websocket)
    try:
        while True:
            # We don't expect messages from the client; this keeps the socket open
            # and lets us detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(user_id, websocket)
