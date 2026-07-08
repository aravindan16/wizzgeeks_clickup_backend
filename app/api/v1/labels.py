"""Global label catalog endpoints — list / create (get-or-create) / delete."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, get_label_service
from app.schemas.common import MessageResponse
from app.schemas.label import LabelCreate, LabelList, LabelResponse
from app.services.label_service import LabelService

router = APIRouter()

ServiceDep = Annotated[LabelService, Depends(get_label_service)]


@router.get("", response_model=LabelList)
async def list_labels(current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list()}


@router.post("", response_model=LabelResponse)
async def create_label(payload: LabelCreate, current: CurrentUserDep, service: ServiceDep):
    return await service.create(payload.name, payload.color)


@router.delete("/{label_id}", response_model=MessageResponse)
async def delete_label(label_id: str, current: CurrentUserDep, service: ServiceDep):
    await service.delete(label_id)
    return MessageResponse(message="Label deleted")
