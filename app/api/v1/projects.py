"""Project management endpoints."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    CurrentUser,
    get_project_service,
    make_actor,
    require,
)
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.project import (
    MemberAdd,
    MemberResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectStats,
    ProjectUpdate,
    SaveTemplateRequest,
)
from app.services.project_service import ProjectService

router = APIRouter()

ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.get("", response_model=PaginatedResponse[ProjectResponse])
async def list_projects(
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = None,
    search: str | None = None,
):
    items, total = await service.list_projects(
        actor=make_actor(actor, request), skip=skip, limit=limit, status=status, search=search
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.create"))],
):
    return await service.create_project(payload.model_dump(), make_actor(actor, request))


# --- status templates (declared before /{project_id} to avoid path capture) ---
@router.get("/status-templates")
async def list_status_templates(
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.list_status_templates(make_actor(actor, request))


@router.post("/status-templates", status_code=201)
async def save_status_template(
    payload: SaveTemplateRequest,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.create"))],
):
    return await service.save_status_template(
        payload.name, [s.model_dump() for s in payload.statuses], make_actor(actor, request)
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.get_project(project_id, make_actor(actor, request))


@router.get("/{project_id}/stats", response_model=ProjectStats)
async def project_stats(
    project_id: str,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.get_stats(project_id, make_actor(actor, request))


@router.get("/{project_id}/activity")
async def project_activity(
    project_id: str,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.get_activity(project_id, make_actor(actor, request))


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    request: Request,
    service: ProjectServiceDep,
    # Owner OR manager — enforced in the service.
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.update_project(
        project_id, payload.model_dump(exclude_unset=True), make_actor(actor, request)
    )


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: str,
    request: Request,
    service: ProjectServiceDep,
    # Owner OR manager — enforced in the service.
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.archive_project(project_id, make_actor(actor, request))


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(
    project_id: str,
    request: Request,
    service: ProjectServiceDep,
    # Owner OR admin — enforced in the service.
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    await service.soft_delete(project_id, make_actor(actor, request))
    return MessageResponse(message="Project deleted")


# --- members ---
@router.get("/{project_id}/members", response_model=list[MemberResponse])
async def list_members(
    project_id: str,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.list_members(project_id, make_actor(actor, request))


@router.post("/{project_id}/members", response_model=MemberResponse, status_code=201)
async def add_member(
    project_id: str,
    payload: MemberAdd,
    request: Request,
    service: ProjectServiceDep,
    # Owner OR lead — enforced in the service.
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.add_member(
        project_id, payload.project_role, make_actor(actor, request),
        user_id=payload.user_id, email=payload.email,
    )


@router.patch("/{project_id}/members/{user_id}", response_model=MemberResponse)
async def update_member(
    project_id: str,
    user_id: str,
    payload: MemberAdd,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    return await service.update_member_role(
        project_id, user_id, payload.project_role, make_actor(actor, request)
    )


@router.delete("/{project_id}/members/{user_id}", response_model=MessageResponse)
async def remove_member(
    project_id: str,
    user_id: str,
    request: Request,
    service: ProjectServiceDep,
    actor: Annotated[CurrentUser, Depends(require("project.read"))],
):
    await service.remove_member(project_id, user_id, make_actor(actor, request))
    return MessageResponse(message="Member removed")
