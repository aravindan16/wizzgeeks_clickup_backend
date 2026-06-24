"""Per-user starred items (DB-backed). Available to every authenticated user."""
from datetime import timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserDep, DbDep
from app.core.exceptions import NotFoundError
from app.repositories.starred_repository import StarredRepository
from app.schemas.common import MessageResponse
from app.utils.datetime import utcnow

router = APIRouter()


class StarIn(BaseModel):
    entity_type: str = Field(default="space", max_length=40)
    entity_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=200)
    icon: str | None = None


class StarOut(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    path: str
    name: str
    icon: str
    starred_at: int  # epoch milliseconds


def _serialize(doc) -> StarOut:
    starred = doc.get("starred_at")
    if starred and starred.tzinfo is None:
        starred = starred.replace(tzinfo=timezone.utc)
    ms = int(starred.timestamp() * 1000) if starred else 0
    return StarOut(
        id=str(doc["_id"]), entity_type=doc["entity_type"], entity_id=doc["entity_id"],
        path=doc["path"], name=doc["name"], icon=doc.get("icon", "📁"), starred_at=ms,
    )


@router.get("", response_model=list[StarOut])
async def list_starred(current: CurrentUserDep, db: DbDep, entity_type: str | None = None):
    repo = StarredRepository(db)
    rows = await repo.list_for_user(current.id, entity_type)
    return [_serialize(r) for r in rows]


@router.post("", response_model=MessageResponse)
async def star_item(payload: StarIn, current: CurrentUserDep, db: DbDep):
    repo = StarredRepository(db)
    await repo.star(current.id, payload.model_dump(), utcnow())
    return MessageResponse(message="starred")


@router.delete("/{entity_type}/{entity_id}", response_model=MessageResponse)
async def unstar_item(entity_type: str, entity_id: str, current: CurrentUserDep, db: DbDep):
    repo = StarredRepository(db)
    removed = await repo.unstar(current.id, entity_type, entity_id)
    if not removed:
        raise NotFoundError("Starred item not found")
    return MessageResponse(message="unstarred")
