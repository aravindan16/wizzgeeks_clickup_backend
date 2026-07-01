"""User-defined dashboard (ClickUp-style cards) request/response DTOs.

Distinct from the analytics dashboards in `dashboard.py` — these are per-user
boards holding arbitrary card configs (Portfolio / charts), persisted in DB.
"""
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UserDashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cards: list[dict[str, Any]] = []


class UserDashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    cards: list[dict[str, Any]] | None = None


class UserDashboardResponse(ORMModel):
    id: str
    name: str
    cards: list[dict[str, Any]] = []
    created_at: Any | None = None
    updated_at: Any | None = None


class UserDashboardList(ORMModel):
    items: list[UserDashboardResponse]
