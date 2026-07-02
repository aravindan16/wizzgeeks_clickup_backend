"""Saved-filter endpoints (personal, owner-scoped)."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, get_saved_filter_service
from app.schemas.common import MessageResponse
from app.schemas.saved_filter import (
    SavedFilterCreate, SavedFilterList, SavedFilterResponse, SavedFilterUpdate,
)
from app.services.saved_filter_service import SavedFilterService

router = APIRouter()

ServiceDep = Annotated[SavedFilterService, Depends(get_saved_filter_service)]


@router.get("", response_model=SavedFilterList)
async def list_filters(current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list(current.id)}


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
