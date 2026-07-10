"""Project and project-member DTOs."""
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel

ProjectStatus = Literal["active", "on_hold", "completed", "archived"]
ProjectRole = Literal["super_admin", "admin", "employee"]
StatusGroup = Literal["not_started", "active", "done", "closed"]


class StatusItem(BaseModel):
    key: str | None = None  # slugified from name server-side if omitted
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(default="#6b7280", max_length=9)
    group: StatusGroup = "active"


class ProjectCreate(BaseModel):
    key: str = Field(min_length=2, max_length=10, pattern=r"^[A-Za-z][A-Za-z0-9]*$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    start_date: str | None = None
    end_date: str | None = None
    # Optional custom workflow; defaults applied server-side when omitted.
    statuses: list[StatusItem] | None = None


class SaveTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    statuses: list[StatusItem] = Field(min_length=1)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    icon: str | None = Field(default=None, max_length=64)  # "FaRocket|#7c3aed" (icon + colour) or emoji
    status: ProjectStatus | None = None
    start_date: str | None = None
    end_date: str | None = None


class ProjectResponse(ORMModel):
    id: str = Field(alias="_id")
    key: str
    name: str
    icon: str | None = None
    description: str | None = None
    status: str
    owner_id: str | None = None
    owner_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    member_count: int | None = None
    statuses: list[dict[str, Any]] = []
    created_at: Any | None = None
    updated_at: Any | None = None


class MemberAdd(BaseModel):
    # Add by user_id (picked from a list) OR by email (resolved server-side).
    user_id: str | None = None
    email: EmailStr | None = None
    project_role: ProjectRole = "employee"


class MemberResponse(ORMModel):
    id: str = Field(alias="_id")
    user_id: str
    full_name: str | None = None
    email: str | None = None
    avatar_color: str | None = None
    avatar_url: str | None = None
    project_role: str
    added_at: Any | None = None


class ProjectStats(BaseModel):
    total_tasks: int
    completed_tasks: int
    pending_tasks: int
    team_members: int
    progress_percentage: float
