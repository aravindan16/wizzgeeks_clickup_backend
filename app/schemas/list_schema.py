"""List (inside a Space) DTOs."""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.project import StatusItem

Privacy = Literal["public", "private"]
StatusMode = Literal["inherit", "custom"]


class ListCreate(BaseModel):
    space_id: str
    name: str = Field(min_length=1, max_length=120)
    privacy: Privacy = "public"
    template: str | None = None  # optional starter template id (reserved)


class ListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    privacy: Privacy | None = None
    # Per-List task statuses: inherit the Space workflow, or use a custom one.
    status_mode: StatusMode | None = None
    statuses: list[StatusItem] | None = None


class MoveListRequest(BaseModel):
    space_id: str


class ListResponse(ORMModel):
    id: str = Field(alias="_id")
    space_id: str
    name: str
    privacy: str = "public"
    is_archived: bool = False
    owner_id: str | None = None
    task_count: int | None = None
    order: int = 0
    status_mode: str = "inherit"
    statuses: list[dict[str, Any]] = []
    created_at: Any | None = None
    updated_at: Any | None = None
