"""Daily activity (standup) endpoints."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import CurrentUser, get_daily_update_service, make_actor, require
from app.schemas.common import PaginatedResponse
from app.schemas.daily_update import (
    BlockerItem,
    DailySummary,
    DailyUpdateCreate,
    DailyUpdateResponse,
    DailyUpdateUpdate,
    MissingUpdateUser,
)
from app.services.daily_update_service import DailyUpdateService

router = APIRouter()

ServiceDep = Annotated[DailyUpdateService, Depends(get_daily_update_service)]


@router.post("", response_model=DailyUpdateResponse, status_code=201)
async def create_update(
    payload: DailyUpdateCreate,
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.create"))],
):
    return await service.create_update(payload.model_dump(), make_actor(actor, request))


@router.get("/me", response_model=PaginatedResponse[DailyUpdateResponse])
async def my_updates(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.read.self"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    date_from: str | None = None,
    date_to: str | None = None,
):
    items, total = await service.my_updates(
        make_actor(actor, request), skip=skip, limit=limit, date_from=date_from, date_to=date_to
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/summary", response_model=DailySummary)
async def summary(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.read.self"))],
    period: str = Query("week", pattern="^(week|month)$"),
    ref_date: str | None = None,
    user_id: str | None = None,
):
    return await service.summary(
        make_actor(actor, request), target_user_id=user_id, period=period, ref_date=ref_date
    )


@router.get("/team", response_model=PaginatedResponse[DailyUpdateResponse])
async def team_updates(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.read.team"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user_id: str | None = None,
):
    items, total = await service.list_team(
        make_actor(actor, request), skip=skip, limit=limit, date=date,
        date_from=date_from, date_to=date_to, user_id=user_id,
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/missing", response_model=list[MissingUpdateUser])
async def missing_updates(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.read.team"))],
    date: str | None = None,
):
    return await service.missing_updates(make_actor(actor, request), date)


@router.get("/blockers", response_model=list[BlockerItem])
async def team_blockers(
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.read.team"))],
    date_from: str | None = None,
    date_to: str | None = None,
):
    return await service.team_blockers(
        make_actor(actor, request), date_from=date_from, date_to=date_to
    )


@router.get("/{update_id}", response_model=DailyUpdateResponse)
async def get_update(
    update_id: str,
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.read.self"))],
):
    return await service.get_update(update_id, make_actor(actor, request))


@router.patch("/{update_id}", response_model=DailyUpdateResponse)
async def update_update(
    update_id: str,
    payload: DailyUpdateUpdate,
    request: Request,
    service: ServiceDep,
    actor: Annotated[CurrentUser, Depends(require("dailyupdate.create"))],
):
    return await service.update_update(update_id, payload.model_dump(exclude_unset=True), make_actor(actor, request))
