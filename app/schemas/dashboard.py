"""Dashboard & analytics response DTOs (kept loose; values are aggregation output)."""
from typing import Any

from pydantic import BaseModel


class StatusCount(BaseModel):
    status: str
    count: int


class TrendPoint(BaseModel):
    date: str
    hours: float


class EmployeeDashboard(BaseModel):
    open_tasks: int
    completed_tasks: int
    blocked_tasks: int
    overdue_tasks: int
    hours_today: float
    weekly_hours: float
    todays_tasks: list[dict[str, Any]]
    recent_updates: list[dict[str, Any]]
    hours_by_day: dict[str, float]
    activity_trend: list[TrendPoint]


class TeamDashboard(BaseModel):
    team_members: list[dict[str, Any]]
    team_productivity: list[dict[str, Any]]
    missing_updates: list[dict[str, Any]]
    open_blockers: list[dict[str, Any]]
    task_distribution: list[StatusCount]
    team_capacity: list[dict[str, Any]]


class ManagerDashboard(BaseModel):
    project_progress: list[dict[str, Any]]
    team_performance: list[dict[str, Any]]
    delayed_tasks: list[dict[str, Any]]
    delayed_count: int
    weekly_report: dict[str, Any]


class AdminDashboard(BaseModel):
    total_users: int
    active_users: int
    total_projects: int
    active_projects: int
    total_tasks: int
    open_tasks: int
    blocked_tasks: int
    overdue_tasks: int
    completion_rate: float
    productivity_score: float
    weekly_hours: float
    missing_updates_today: int
    tasks_by_status: list[StatusCount]
    project_progress: list[dict[str, Any]]
