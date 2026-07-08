"""Custom per-space role DTOs."""
from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SpaceRoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    permissions: list[str] = Field(default_factory=list)


class SpaceRoleResponse(ORMModel):
    id: str = Field(alias="_id")
    project_id: str
    name: str
    description: str | None = None
    permissions: list[str] = []
    is_system: bool = False
    created_at: object | None = None
