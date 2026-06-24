"""Custom field endpoints (Space- and List-scoped). Access mirrors Space membership."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, get_custom_field_service, make_actor, require
from app.schemas.common import MessageResponse
from app.schemas.custom_field import (
    CustomFieldCreate,
    CustomFieldResponse,
    CustomFieldUpdate,
    DuplicateFieldRequest,
    MoveFieldRequest,
    ReorderFieldsRequest,
)
from app.services.custom_field_service import CustomFieldService

router = APIRouter()

CFServiceDep = Annotated[CustomFieldService, Depends(get_custom_field_service)]


@router.get("", response_model=list[CustomFieldResponse])
async def list_fields(
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
    space_id: str = Query(...),
    list_id: str | None = None,
    all: bool = False,
):
    actor_ctx = make_actor(actor, request)
    if all:
        return await service.list_all_fields(space_id, actor_ctx)
    return await service.list_fields(space_id, list_id, actor_ctx)


@router.get("/reusable", response_model=list[CustomFieldResponse])
async def reusable_fields(
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
    space_id: str = Query(...),
    list_id: str | None = None,
):
    return await service.reusable_fields(space_id, list_id, make_actor(actor, request))


@router.post("", response_model=CustomFieldResponse, status_code=201)
async def create_field(
    payload: CustomFieldCreate,
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.create"))],
):
    return await service.create_field(payload.model_dump(), make_actor(actor, request))


@router.patch("/{field_id}", response_model=CustomFieldResponse)
async def update_field(
    field_id: str,
    payload: CustomFieldUpdate,
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.create"))],
):
    return await service.update_field(field_id, payload.model_dump(exclude_unset=True), make_actor(actor, request))


@router.post("/reorder", response_model=MessageResponse)
async def reorder_fields(
    payload: ReorderFieldsRequest,
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.create"))],
):
    await service.reorder_fields(payload.ids, make_actor(actor, request))
    return MessageResponse(message="Custom fields reordered")


@router.post("/{field_id}/move", response_model=CustomFieldResponse)
async def move_field(
    field_id: str,
    payload: MoveFieldRequest,
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.create"))],
):
    return await service.move_field(field_id, payload.scope, payload.list_id, make_actor(actor, request))


@router.post("/{field_id}/duplicate", response_model=CustomFieldResponse, status_code=201)
async def duplicate_field(
    field_id: str,
    payload: DuplicateFieldRequest,
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.create"))],
):
    return await service.duplicate_field(field_id, payload.scope, payload.space_id, payload.list_id, make_actor(actor, request))


@router.delete("/{field_id}", response_model=MessageResponse)
async def delete_field(
    field_id: str,
    request: Request,
    service: CFServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.create"))],
):
    await service.delete_field(field_id, make_actor(actor, request))
    return MessageResponse(message="Custom field deleted")
