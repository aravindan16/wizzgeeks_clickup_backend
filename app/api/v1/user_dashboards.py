"""User-defined dashboard endpoints (ClickUp-style boards, owner-scoped)."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUserDep, get_user_dashboard_service
from app.schemas.common import MessageResponse
from app.schemas.user_dashboard import (
    DashboardMemberAdd, DashboardMemberList,
    UserDashboardCreate, UserDashboardList, UserDashboardResponse, UserDashboardUpdate,
)
from app.services.user_dashboard_service import UserDashboardService

router = APIRouter()

ServiceDep = Annotated[UserDashboardService, Depends(get_user_dashboard_service)]


@router.get("", response_model=UserDashboardList)
async def list_dashboards(current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list(current.id)}


# Static route declared before /{dashboard_id} so it isn't captured as an id.
@router.get("/users/search", response_model=DashboardMemberList)
async def search_users(current: CurrentUserDep, service: ServiceDep, q: str = ""):
    return {"items": await service.search_users(q)}


@router.post("", response_model=UserDashboardResponse)
async def create_dashboard(payload: UserDashboardCreate, current: CurrentUserDep, service: ServiceDep):
    return await service.create(current.id, name=payload.name, cards=payload.cards)


@router.get("/{dashboard_id}", response_model=UserDashboardResponse)
async def get_dashboard(dashboard_id: str, current: CurrentUserDep, service: ServiceDep):
    return await service.get(dashboard_id, current.id)


@router.patch("/{dashboard_id}", response_model=UserDashboardResponse)
async def update_dashboard(dashboard_id: str, payload: UserDashboardUpdate, current: CurrentUserDep, service: ServiceDep):
    return await service.update(dashboard_id, current.id, name=payload.name, cards=payload.cards)


@router.delete("/{dashboard_id}", response_model=MessageResponse)
async def delete_dashboard(dashboard_id: str, current: CurrentUserDep, service: ServiceDep):
    await service.delete(dashboard_id, current.id)
    return MessageResponse(message="Dashboard deleted")


@router.get("/{dashboard_id}/members", response_model=DashboardMemberList)
async def list_members(dashboard_id: str, current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.list_members(dashboard_id, current.id)}


@router.post("/{dashboard_id}/members", response_model=DashboardMemberList)
async def add_member(dashboard_id: str, payload: DashboardMemberAdd, current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.add_member(dashboard_id, current.id, member_user_id=payload.user_id)}


@router.delete("/{dashboard_id}/members/{user_id}", response_model=DashboardMemberList)
async def remove_member(dashboard_id: str, user_id: str, current: CurrentUserDep, service: ServiceDep):
    return {"items": await service.remove_member(dashboard_id, current.id, user_id)}
