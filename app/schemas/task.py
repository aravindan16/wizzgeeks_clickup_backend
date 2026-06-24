"""Task, comment, history, and metrics DTOs."""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.core.workflow import WORKFLOW_STATES

TaskType = Literal["epic", "story", "task", "bug", "subtask"]
Priority = Literal["low", "medium", "high", "critical"]
# Issue-link relationships (Jira-style). Each has an inverse stored on the other side.
LinkType = Literal["relates_to", "blocks", "blocked_by", "duplicates", "duplicated_by"]


class TaskCreate(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    type: TaskType = "task"
    priority: Priority = "medium"
    assignee_id: str | None = None
    assignee_email: str | None = None  # assign by email; resolved + added as member if needed
    start_date: str | None = None
    end_date: str | None = None
    due_date: str | None = None
    labels: list[str] = Field(default_factory=list)
    estimate_hours: float | None = Field(default=None, ge=0)
    # Optional initial column (board inline-create). Defaults to backlog.
    status: str | None = None
    # When set, this task is a subtask of the given parent (same space).
    parent_id: str | None = None
    # Optional List (inside the Space) this task belongs to.
    list_id: str | None = None
    # Custom field values, keyed by field id.
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    type: TaskType | None = None
    priority: Priority | None = None
    start_date: str | None = None
    end_date: str | None = None
    due_date: str | None = None
    labels: list[str] | None = None
    estimate_hours: float | None = Field(default=None, ge=0)
    custom_fields: dict[str, Any] | None = None


class TaskResponse(ORMModel):
    id: str = Field(alias="_id")
    project_id: str
    key: str
    title: str
    description: str | None = None
    type: str
    status: str
    priority: str
    reporter_id: str | None = None
    assignee_id: str | None = None
    watchers: list[str] = []
    labels: list[str] = []
    start_date: str | None = None
    end_date: str | None = None
    due_date: str | None = None
    estimate_hours: float | None = None
    actual_hours: float = 0
    comment_count: int = 0
    is_archived: bool = False
    parent_id: str | None = None
    list_id: str | None = None
    custom_fields: dict[str, Any] = {}
    links: list[dict[str, Any]] = []
    created_at: Any | None = None
    updated_at: Any | None = None


class SubtaskResponse(ORMModel):
    id: str = Field(alias="_id")
    key: str
    title: str
    type: str
    status: str
    priority: str
    assignee_id: str | None = None


class LinkRequest(BaseModel):
    target_task_id: str
    link_type: LinkType = "relates_to"


class LinkResponse(BaseModel):
    type: str
    task_id: str
    key: str | None = None
    title: str | None = None
    status: str | None = None
    task_type: str | None = None


class WorklogResponse(ORMModel):
    id: str = Field(alias="_id")
    task_id: str
    user_id: str | None = None
    user_name: str | None = None
    hours: float
    note: str | None = None
    created_at: Any | None = None


class ActivityResponse(ORMModel):
    id: str = Field(alias="_id")
    actor_id: str | None = None
    actor_name: str | None = None
    action: str
    metadata: dict[str, Any] = {}
    created_at: Any | None = None


class StatusChangeRequest(BaseModel):
    to_status: str = Field(description="Target workflow state")
    note: str | None = Field(default=None, max_length=1000)

    @property
    def normalized(self) -> str:
        return self.to_status.strip().lower()


class AssignRequest(BaseModel):
    assignee_id: str | None = None  # null = unassign


class WatcherRequest(BaseModel):
    user_id: str


class WorklogRequest(BaseModel):
    hours: float = Field(gt=0, le=1000)
    note: str | None = Field(default=None, max_length=1000)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CommentResponse(ORMModel):
    id: str = Field(alias="_id")
    task_id: str
    author_id: str
    author_name: str | None = None
    body: str
    is_edited: bool = False
    created_at: Any | None = None
    updated_at: Any | None = None


class StatusHistoryResponse(ORMModel):
    id: str = Field(alias="_id")
    from_status: str | None = None
    to_status: str
    changed_by: str | None = None
    note: str | None = None
    created_at: Any | None = None


class AssignmentHistoryResponse(ORMModel):
    id: str = Field(alias="_id")
    assignee_id: str | None = None
    assigned_by: str | None = None
    assigned_at: Any | None = None
    unassigned_at: Any | None = None
    is_active: bool = True


class TaskMetrics(BaseModel):
    open_tasks: int
    closed_tasks: int
    blocked_tasks: int
    overdue_tasks: int


class WorkflowInfo(BaseModel):
    states: list[str] = WORKFLOW_STATES
    transitions: dict[str, list[str]]
