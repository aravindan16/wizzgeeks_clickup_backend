"""Role listing endpoint (RBAC matrix is seeded; runtime editing is a future module)."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_role_service, require
from app.schemas.common import ORMModel
from app.services.role_service import RoleService

router = APIRouter()


class RoleResponse(ORMModel):
    key: str
    name: str
    level: int
    permissions: list[str]


@router.get("", response_model=list[RoleResponse])
async def list_roles(
    service: Annotated[RoleService, Depends(get_role_service)],
    _: Annotated[object, Depends(require("role.read"))],
):
    roles = await service.list_roles()
    return [
        RoleResponse(
            key=r["key"], name=r["name"], level=r["level"], permissions=r.get("permissions", [])
        )
        for r in roles
    ]
