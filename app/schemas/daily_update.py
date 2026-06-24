"""Daily activity (standup) DTOs."""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

EntryStatus = Literal["planned", "in_progress", "completed", "blocked", "on_hold"]


class DailyEntry(BaseModel):
    project_id: str | None = None
    task_id: str | None = None
    work_done: str = Field(min_length=1, max_length=2000)
    hours_spent: float = Field(default=0, ge=0, le=24)
    blockers: str | None = Field(default=None, max_length=2000)
    status: EntryStatus = "in_progress"


class DailyUpdateCreate(BaseModel):
    date: str | None = None  # YYYY-MM-DD; defaults to today (server UTC)
    entries: list[DailyEntry] = Field(min_length=1)
    tomorrow_plan: str | None = Field(default=None, max_length=2000)
    mood: str | None = None


class DailyUpdateUpdate(BaseModel):
    entries: list[DailyEntry] | None = Field(default=None, min_length=1)
    tomorrow_plan: str | None = Field(default=None, max_length=2000)
    mood: str | None = None


class DailyEntryResponse(ORMModel):
    project_id: str | None = None
    task_id: str | None = None
    work_done: str
    hours_spent: float = 0
    blockers: str | None = None
    status: str = "in_progress"


class DailyUpdateResponse(ORMModel):
    id: str = Field(alias="_id")
    user_id: str
    user_name: str | None = None
    date: str
    entries: list[DailyEntryResponse] = []
    tomorrow_plan: str | None = None
    mood: str | None = None
    total_hours: float = 0
    has_blockers: bool = False
    locked: bool = False
    submitted_at: Any | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class MissingUpdateUser(BaseModel):
    user_id: str
    full_name: str | None = None
    email: str | None = None
    department: str | None = None


class BlockerItem(BaseModel):
    update_id: str
    user_id: str
    user_name: str | None = None
    date: str
    task_id: str | None = None
    project_id: str | None = None
    blockers: str


class DailySummary(BaseModel):
    user_id: str
    period: str
    start_date: str
    end_date: str
    total_hours: float
    updates_count: int
    blocker_count: int
    hours_by_day: dict[str, float]
    hours_by_project: dict[str, float]
