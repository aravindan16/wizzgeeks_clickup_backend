"""Report DTOs. Report payloads are normalized to columns + rows + summary so a
single pair of exporters (Excel/PDF) can render any report type."""
from typing import Any

from pydantic import BaseModel

# Canonical report types.
REPORT_TYPES = [
    "daily_activity",
    "weekly_summary",
    "monthly_productivity",
    "project_progress",
    "task_completion",
    "delayed_tasks",
    "resource_utilization",
    "team_performance",
]


class ReportColumn(BaseModel):
    key: str
    label: str


class ReportData(BaseModel):
    type: str
    title: str
    generated_at: str
    filters: dict[str, Any]
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
