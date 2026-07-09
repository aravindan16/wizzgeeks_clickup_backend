"""User management endpoints (admin-scoped) + self profile.

Mutations are audit-logged with the acting user and client IP.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from pydantic import BaseModel

from app.api.deps import CurrentUser, CurrentUserDep, get_user_service, make_actor, require
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.user import AdminPasswordReset, UserCreate, UserResponse, UserUpdate
from app.services.user_service import UserService
from app.utils.storage import store_avatar

ALLOWED_AVATAR_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}


class PreferencesUpdate(BaseModel):
    in_app: bool | None = None
    email: bool | None = None

router = APIRouter()

UserServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    service: UserServiceDep,
    _: Annotated[CurrentUser, Depends(require("user.read"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = None,
    search: str | None = None,
):
    items, total = await service.list_users(
        skip=skip, limit=limit, status=status, search=search
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    request: Request,
    service: UserServiceDep,
    actor: Annotated[CurrentUser, Depends(require("user.create"))],
):
    return await service.create_user(payload.model_dump(), make_actor(actor, request))


# --- self profile (any authenticated user) ---
@router.get("/me/profile", response_model=UserResponse)
async def my_profile(current: CurrentUserDep, service: UserServiceDep):
    return await service.get_user(current.id)


@router.patch("/me/profile", response_model=UserResponse)
async def update_my_profile(
    payload: UserUpdate, request: Request, current: CurrentUserDep, service: UserServiceDep
):
    # A user cannot change their own roles via the self-profile route.
    data = payload.model_dump(exclude_unset=True)
    data.pop("role_keys", None)
    return await service.update_user(current.id, data, make_actor(current, request))


@router.patch("/me/preferences", response_model=UserResponse)
async def update_my_preferences(
    payload: PreferencesUpdate, current: CurrentUserDep, service: UserServiceDep
):
    prefs = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    return await service.set_preferences(current.id, prefs)


@router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    current: CurrentUserDep, service: UserServiceDep, file: UploadFile = File(...)
):
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise ValidationError(f"Unsupported image type: {file.content_type}")
    content = await file.read()
    if len(content) > settings.MAX_AVATAR_BYTES:
        raise ValidationError("Image exceeds the maximum allowed size")
    url = store_avatar(current.id, content, file.content_type)
    return await service.set_avatar(current.id, url)


# --- admin user management ---
@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    service: UserServiceDep,
    _: Annotated[CurrentUser, Depends(require("user.read"))],
):
    return await service.get_user(user_id)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    service: UserServiceDep,
    actor: Annotated[CurrentUser, Depends(require("user.update"))],
):
    return await service.update_user(
        user_id, payload.model_dump(exclude_unset=True), make_actor(actor, request)
    )


@router.post("/{user_id}/disable", response_model=UserResponse)
async def disable_user(
    user_id: str,
    request: Request,
    service: UserServiceDep,
    actor: Annotated[CurrentUser, Depends(require("user.update"))],
):
    return await service.set_status(user_id, "suspended", make_actor(actor, request))


@router.post("/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user_id: str,
    request: Request,
    service: UserServiceDep,
    actor: Annotated[CurrentUser, Depends(require("user.update"))],
):
    return await service.set_status(user_id, "active", make_actor(actor, request))


@router.post("/{user_id}/reset-password", response_model=UserResponse)
async def reset_user_password(
    user_id: str,
    payload: AdminPasswordReset,
    request: Request,
    service: UserServiceDep,
    actor: Annotated[CurrentUser, Depends(require("user.update"))],
):
    """Admin resets a user's password (used when a user forgets theirs)."""
    return await service.reset_password(user_id, payload.new_password, make_actor(actor, request))


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: str,
    request: Request,
    service: UserServiceDep,
    actor: Annotated[CurrentUser, Depends(require("user.delete"))],
):
    await service.soft_delete(user_id, make_actor(actor, request))
    return MessageResponse(message="User deactivated")
