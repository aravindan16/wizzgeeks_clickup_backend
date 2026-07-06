"""Saved-filter endpoints (owner-scoped, shareable with members)."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, get_saved_filter_service
from app.schemas.common import MessageResponse
from app.schemas.saved_filter import (
    FilterMemberAdd, FilterMemberList,
    SavedFilterCreate, SavedFilterList, SavedFilterResponse, SavedFilterUpdate,
)
from app.services.saved_filter_service import SavedFilterService

router = APIRouter()

ServiceDep = Annotated[SavedFilterService, Depends(get_saved_filter_service)]


@router.get("", response_model=SavedFilterList)
async def list_filters(current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list(current.id)}


# Static route declared before /{filter_id} so it isn't captured as an id.
@router.get("/users/search", response_model=FilterMemberList)
async def search_users(current: CurrentUserDep, service: ServiceDep, q: str = ""):
    return {"items": await service.search_users(q)}


@router.post("", response_model=SavedFilterResponse)
async def create_filter(payload: SavedFilterCreate, current: CurrentUserDep, service: ServiceDep):
    return await service.create(current.id, name=payload.name, cards=payload.cards, conj=payload.conj)


@router.get("/{filter_id}", response_model=SavedFilterResponse)
async def get_filter(filter_id: str, current: CurrentUserDep, service: ServiceDep):
    return await service.get(filter_id, current.id)


@router.patch("/{filter_id}", response_model=SavedFilterResponse)
async def update_filter(filter_id: str, payload: SavedFilterUpdate, current: CurrentUserDep, service: ServiceDep):
    return await service.update(filter_id, current.id, name=payload.name, cards=payload.cards, conj=payload.conj)


@router.delete("/{filter_id}", response_model=MessageResponse)
async def delete_filter(filter_id: str, current: CurrentUserDep, service: ServiceDep):
    await service.delete(filter_id, current.id)
    return MessageResponse(message="Filter deleted")


@router.get("/{filter_id}/members", response_model=FilterMemberList)
async def list_members(filter_id: str, current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list_members(filter_id, current.id)}


@router.post("/{filter_id}/members", response_model=FilterMemberList)
async def add_member(filter_id: str, payload: FilterMemberAdd, current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.add_member(filter_id, current.id, member_user_id=payload.user_id)}


@router.delete("/{filter_id}/members/{user_id}", response_model=FilterMemberList)
async def remove_member(filter_id: str, user_id: str, current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.remove_member(filter_id, current.id, user_id)}
