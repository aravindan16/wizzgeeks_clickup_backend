"""Chat endpoints — conversations, messages, and message actions (membership-scoped)."""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep, get_chat_service
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.schemas.common import MessageResponse
from app.services.chat_service import ChatService
from app.utils.storage import store_chat_file, store_chat_image

router = APIRouter()

ServiceDep = Annotated[ChatService, Depends(get_chat_service)]

MAX_CHAT_FILE_BYTES = 15 * 1024 * 1024  # 15 MB


class Attachment(BaseModel):
    url: str
    name: str | None = None
    content_type: str | None = None
    size: int | None = None
    kind: str | None = None  # "image" | "file"


class PollCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=12)
    multi: bool = False


class VoteRequest(BaseModel):
    option_id: str


class DirectRequest(BaseModel):
    user_id: str


class GroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    member_ids: list[str] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    body: str = Field(default="", max_length=5000)
    reply_to_id: str | None = None
    attachment: Attachment | None = None


class EditRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ReactRequest(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)


class PinRequest(BaseModel):
    pinned: bool = True


class BookmarkRequest(BaseModel):
    bookmarked: bool = True


class ForwardRequest(BaseModel):
    conversation_id: str


# --- directory & saved ---
@router.get("/contacts")
async def list_contacts(current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list_contacts(current.id)}


@router.get("/bookmarks")
async def list_bookmarks(current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list_bookmarks(current.id)}


# --- conversations ---
@router.get("/conversations")
async def list_conversations(current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list_conversations(current.id)}


@router.post("/conversations/direct")
async def create_direct(payload: DirectRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.create_direct(current.id, payload.user_id)


@router.post("/conversations/group")
async def create_group(payload: GroupRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.create_group(current.id, payload.name, payload.member_ids)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, current: CurrentUserDep, service: ServiceDep):
    return await service.get_conversation(conversation_id, current.id)


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str, current: CurrentUserDep, service: ServiceDep,
    skip: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
):
    items, total = await service.list_messages(conversation_id, current.id, skip=skip, limit=limit)
    return {"items": items, "total": total}


@router.get("/conversations/{conversation_id}/pinned")
async def list_pinned(conversation_id: str, current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list_pinned(conversation_id, current.id)}


@router.post("/upload")
async def upload_attachment(current: CurrentUserDep, file: UploadFile = File(...)):
    """Upload a chat attachment (image or any document); returns an attachment ref."""
    content = await file.read()
    if len(content) > MAX_CHAT_FILE_BYTES:
        raise ValidationError("File is too large (max 15 MB)")
    ctype = file.content_type or "application/octet-stream"
    is_image = ctype.startswith("image/")
    url = (store_chat_image if is_image else store_chat_file)(current.id, content, ctype)
    return {"url": url, "name": file.filename, "content_type": ctype,
            "size": len(content), "kind": "image" if is_image else "file"}


@router.post("/conversations/{conversation_id}/avatar")
async def set_group_avatar(
    conversation_id: str, current: CurrentUserDep, service: ServiceDep, file: UploadFile = File(...),
):
    """Set/change a group conversation's photo. Returns the updated conversation."""
    content = await file.read()
    if len(content) > MAX_CHAT_FILE_BYTES:
        raise ValidationError("Image is too large (max 15 MB)")
    ctype = file.content_type or "application/octet-stream"
    if not ctype.startswith("image/"):
        raise ValidationError("Group photo must be an image")
    return await service.set_group_avatar(conversation_id, current.id, content, ctype)


@router.post("/conversations/{conversation_id}/poll")
async def create_poll(conversation_id: str, payload: PollCreateRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.create_poll(conversation_id, current.id, payload.question, payload.options, payload.multi)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str, payload: SendMessageRequest, current: CurrentUserDep, service: ServiceDep,
):
    attachment = payload.attachment.model_dump() if payload.attachment else None
    return await service.send_message(conversation_id, current.id, payload.body, payload.reply_to_id, attachment)


@router.post("/conversations/{conversation_id}/read", response_model=MessageResponse)
async def mark_read(conversation_id: str, current: CurrentUserDep, service: ServiceDep):
    await service.mark_read(conversation_id, current.id)
    return MessageResponse(message="Read")


# --- message actions ---
@router.patch("/messages/{message_id}")
async def edit_message(message_id: str, payload: EditRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.edit_message(message_id, current.id, payload.body)


@router.delete("/messages/{message_id}")
async def delete_message(message_id: str, current: CurrentUserDep, service: ServiceDep):
    return await service.delete_message(message_id, current.id)


@router.post("/messages/{message_id}/react")
async def react(message_id: str, payload: ReactRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.react(message_id, current.id, payload.emoji)


@router.post("/messages/{message_id}/pin")
async def set_pin(message_id: str, payload: PinRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.set_pin(message_id, current.id, payload.pinned)


@router.post("/messages/{message_id}/bookmark")
async def set_bookmark(message_id: str, payload: BookmarkRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.set_bookmark(message_id, current.id, payload.bookmarked)


@router.post("/messages/{message_id}/forward")
async def forward(message_id: str, payload: ForwardRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.forward_message(message_id, current.id, payload.conversation_id)


@router.post("/messages/{message_id}/vote")
async def vote_poll(message_id: str, payload: VoteRequest, current: CurrentUserDep, service: ServiceDep):
    return await service.vote_poll(message_id, current.id, payload.option_id)
