"""List management endpoints (Lists live inside a Space). Access mirrors Space
membership; all mutations are enforced in the service layer."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, get_list_service, make_actor, require
from app.schemas.common import MessageResponse
from app.schemas.list_schema import (
    ListCreate,
    ListResponse,
    ListUpdate,
    MoveListRequest,
)
from app.services.list_service import ListService

router = APIRouter()

ListServiceDep = Annotated[ListService, Depends(get_list_service)]


@router.get("", response_model=list[ListResponse])
async def list_lists(
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.read"))],
    space_id: str = Query(...),
    include_archived: bool = False,
):
    return await service.list_lists(space_id, make_actor(actor, request), include_archived=include_archived)


@router.post("", response_model=ListResponse, status_code=201)
async def create_list(
    payload: ListCreate,
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.create"))],
):
    return await service.create_list(payload.model_dump(), make_actor(actor, request))


@router.get("/{list_id}", response_model=ListResponse)
async def get_list(
    list_id: str,
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.read"))],
):
    return await service.get_list(list_id, make_actor(actor, request))


@router.patch("/{list_id}", response_model=ListResponse)
async def update_list(
    list_id: str,
    payload: ListUpdate,
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.update"))],
):
    return await service.update_list(list_id, payload.model_dump(exclude_unset=True), make_actor(actor, request))


@router.post("/{list_id}/duplicate", response_model=ListResponse, status_code=201)
async def duplicate_list(
    list_id: str,
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.create"))],
):
    return await service.duplicate_list(list_id, make_actor(actor, request))


@router.post("/{list_id}/archive", response_model=ListResponse)
async def archive_list(
    list_id: str,
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.update"))],
):
    return await service.archive_list(list_id, make_actor(actor, request))


@router.post("/{list_id}/move", response_model=ListResponse)
async def move_list(
    list_id: str,
    payload: MoveListRequest,
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.update"))],
):
    return await service.move_list(list_id, payload.space_id, make_actor(actor, request))


@router.delete("/{list_id}", response_model=MessageResponse)
async def delete_list(
    list_id: str,
    request: Request,
    service: ListServiceDep,
    actor: Annotated[CurrentUser, Depends(require("list.delete"))],
):
    await service.delete_list(list_id, make_actor(actor, request))
    return MessageResponse(message="List deleted")
