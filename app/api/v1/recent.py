"""Per-user recently-visited endpoints (DB-backed, scoped to the current user)."""
from datetime import timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep, DbDep
from app.repositories.recent_repository import RecentRepository
from app.schemas.common import MessageResponse
from app.utils.datetime import utcnow

router = APIRouter()


class RecentItemIn(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=200)
    type: str | None = None
    icon: str | None = None


class RecentItemOut(BaseModel):
    id: str
    path: str
    name: str
    type: str
    icon: str
    visited_at: int  # epoch milliseconds (UI renders relative time)


def _serialize(doc) -> RecentItemOut:
    visited = doc.get("visited_at")
    # Defensive: if a value comes back naive, treat it as UTC (not server-local).
    if visited and visited.tzinfo is None:
        visited = visited.replace(tzinfo=timezone.utc)
    ms = int(visited.timestamp() * 1000) if visited else 0
    return RecentItemOut(
        id=str(doc["_id"]), path=doc["path"], name=doc["name"],
        type=doc.get("type", "Page"), icon=doc.get("icon", "📄"), visited_at=ms,
    )


@router.get("", response_model=list[RecentItemOut])
async def list_recent(current: CurrentUserDep, db: DbDep):
    repo = RecentRepository(db)
    rows = await repo.list_for_user(current.id)
    return [_serialize(r) for r in rows]


@router.post("", response_model=MessageResponse)
async def record_recent(payload: RecentItemIn, current: CurrentUserDep, db: DbDep):
    repo = RecentRepository(db)
    await repo.record(current.id, payload.model_dump(), utcnow())
    return MessageResponse(message="recorded")


@router.delete("", response_model=MessageResponse)
async def clear_recent(current: CurrentUserDep, db: DbDep):
    repo = RecentRepository(db)
    await repo.clear(current.id)
    return MessageResponse(message="cleared")
