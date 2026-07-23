"""Roles & permissions API: the DB-driven permission catalog and roles, plus full
role CRUD (role.create / role.read / role.update / role.delete)."""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import DbDep, get_role_service, require
from app.schemas.common import ORMModel
from app.services.role_service import RoleService

router = APIRouter()

RoleServiceDep = Annotated[RoleService, Depends(get_role_service)]


class RoleResponse(ORMModel):
    id: str = ""
    key: str
    name: str
    level: int
    permissions: list[str]
    is_system: bool = False


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    permissions: list[str] = Field(default_factory=list)
    level: int | None = None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    permissions: list[str] | None = None
    level: int | None = None


def _role_out(r: dict) -> RoleResponse:
    return RoleResponse(id=str(r["_id"]), key=r["key"], name=r["name"],
                        level=r.get("level", 0), permissions=r.get("permissions", []),
                        is_system=bool(r.get("is_system")))


# --- permission catalog (grouped by module, read from the DB) ---
@router.get("/permissions/catalog")
async def permission_catalog(
    db: DbDep,
    _: Annotated[object, Depends(require("permission.manage"))],
):
    perms = await db["permissions"].find({}).sort("order", 1).to_list(length=1000)
    groups: dict[str, dict] = {}
    for p in perms:
        g = groups.setdefault(p["module_key"], {"key": p["module_key"], "module": p["module"], "permissions": []})
        g["permissions"].append({"key": p["key"], "label": p.get("label", p["key"])})
    return {"groups": list(groups.values())}


# --- roles ---
@router.get("", response_model=list[RoleResponse])
async def list_roles(
    service: RoleServiceDep,
    _: Annotated[object, Depends(require("role.read"))],
):
    """List roles (used by role pickers app-wide)."""
    return [_role_out(r) for r in await service.list_roles()]


@router.get("/manage", response_model=list[RoleResponse])
async def list_roles_for_management(
    service: RoleServiceDep,
    _: Annotated[object, Depends(require("permission.manage"))],
):
    """List roles for the Permission setting page (gated by permission.manage)."""
    return [_role_out(r) for r in await service.list_roles()]


@router.post("", response_model=RoleResponse, status_code=201)
async def create_role(
    payload: RoleCreate,
    service: RoleServiceDep,
    _: Annotated[object, Depends(require("role.create"))],
):
    return _role_out(await service.create_role(payload.model_dump()))


@router.patch("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    payload: RoleUpdate,
    service: RoleServiceDep,
    _: Annotated[object, Depends(require("role.update"))],
):
    return _role_out(await service.update_role(role_id, payload.model_dump(exclude_unset=True)))


@router.delete("/{role_id}")
async def delete_role(
    role_id: str,
    service: RoleServiceDep,
    _: Annotated[object, Depends(require("role.delete"))],
):
    await service.delete_role(role_id)
    return {"success": True, "message": "Role deleted"}
