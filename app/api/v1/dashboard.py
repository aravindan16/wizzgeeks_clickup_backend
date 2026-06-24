"""Dashboard & analytics endpoints (role-aware, RBAC-gated)."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, get_dashboard_service, make_actor, require
from app.schemas.dashboard import (
    AdminDashboard,
    EmployeeDashboard,
    ManagerDashboard,
    StatusCount,
    TeamDashboard,
    TrendPoint,
)
from app.services.dashboard_service import DashboardService

router = APIRouter()

ServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]


@router.get("/employee", response_model=EmployeeDashboard)
async def employee_dashboard(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.employee(make_actor(actor, request))


@router.get("/team", response_model=TeamDashboard)
async def team_dashboard(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dashboard.view.team"))],
):
    return await service.team(make_actor(actor, request))


@router.get("/manager", response_model=ManagerDashboard)
async def manager_dashboard(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("report.view.all"))],
):
    return await service.manager(make_actor(actor, request))


@router.get("/admin", response_model=AdminDashboard)
async def admin_dashboard(
    service: ServiceDep,
    _: Annotated[CurrentUser, Depends(require("dashboard.view.admin"))],
):
    return await service.admin()


# --- analytics ---
@router.get("/analytics/tasks-by-status", response_model=list[StatusCount])
async def tasks_by_status(
    service: ServiceDep,
    _: Annotated[CurrentUser, Depends(require("task.read"))],
    project_id: str | None = None,
    assignee_id: str | None = None,
):
    return await service.analytics_tasks_by_status(project_id=project_id, assignee_id=assignee_id)


@router.get("/analytics/hours-trend", response_model=list[TrendPoint])
async def hours_trend(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
    user_id: str | None = None,
    days: int = Query(14, ge=1, le=90),
):
    return await service.analytics_hours_trend(make_actor(actor, request), user_id=user_id, days=days)
