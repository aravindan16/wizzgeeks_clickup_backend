"""Task management endpoints: CRUD, workflow, assignment, watchers, worklog,
comments, history, and metrics. All mutations enforce project membership in the
service layer."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import (
    CurrentUser,
    get_comment_service,
    get_current_user,
    get_task_service,
    make_actor,
    require,
)
from app.core.workflow import ALLOWED_TRANSITIONS, WORKFLOW_STATES
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.task import (
    ActivityResponse,
    AssignmentHistoryResponse,
    AssignRequest,
    CommentCreate,
    CommentResponse,
    CommentUpdate,
    LinkRequest,
    LinkResponse,
    StatusChangeRequest,
    StatusHistoryResponse,
    SubtaskResponse,
    TaskCreate,
    TaskMetrics,
    TaskResponse,
    TaskUpdate,
    WatcherRequest,
    WorklogRequest,
    WorklogResponse,
)
from app.services.comment_service import CommentService
from app.services.task_service import TaskService

router = APIRouter()

TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
CommentServiceDep = Annotated[CommentService, Depends(get_comment_service)]


# --- workflow metadata (any authenticated reader) ---
@router.get("/workflow")
async def workflow(_: Annotated[CurrentUser, Depends(require("task.read"))]):
    return {
        "states": WORKFLOW_STATES,
        "transitions": {k: sorted(v) for k, v in ALLOWED_TRANSITIONS.items()},
    }


@router.get("/metrics", response_model=TaskMetrics)
async def metrics(
    service: TaskServiceDep,
    _: Annotated[CurrentUser, Depends(require("task.read"))],
    project_id: str | None = None,
    assignee_id: str | None = None,
):
    return await service.metrics(project_id=project_id, assignee_id=assignee_id)


# --- CRUD / list ---
@router.get("", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    request: Request,
    service: TaskServiceDep,
    actor_user: Annotated[CurrentUser, Depends(require("task.read"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    project_id: str | None = None,
    list_id: str | None = None,
    status: str | None = None,
    assignee_id: str | None = None,
    priority: str | None = None,
    label: str | None = None,
    search: str | None = None,
    include_archived: bool = False,
    sort_by: str = "created_at",
    sort_dir: int = Query(-1, ge=-1, le=1),
):
    items, total = await service.list_tasks(
        actor=make_actor(actor_user, request), skip=skip, limit=limit, project_id=project_id,
        list_id=list_id, status=status, assignee_id=assignee_id, priority=priority, label=label,
        search=search, include_archived=include_archived, sort_by=sort_by, sort_dir=(-1 if sort_dir < 0 else 1),
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    payload: TaskCreate,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.create"))],
):
    return await service.create_task(payload.model_dump(), make_actor(actor, request))


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.get_task(task_id, make_actor(actor, request))


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.update"))],
):
    return await service.update_task(task_id, payload.model_dump(exclude_unset=True), make_actor(actor, request))


@router.patch("/{task_id}/status", response_model=TaskResponse)
async def change_status(
    task_id: str,
    payload: StatusChangeRequest,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.status.update"))],
):
    return await service.change_status(task_id, payload.normalized, payload.note, make_actor(actor, request))


@router.post("/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: str,
    payload: AssignRequest,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.assign"))],
):
    return await service.assign(task_id, payload.assignee_id, make_actor(actor, request))


@router.post("/{task_id}/worklog", response_model=TaskResponse)
async def log_work(
    task_id: str,
    payload: WorklogRequest,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.update"))],
):
    return await service.log_work(task_id, payload.hours, make_actor(actor, request), payload.note)


@router.get("/{task_id}/worklogs", response_model=list[WorklogResponse])
async def list_worklogs(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.list_worklogs(task_id, make_actor(actor, request))


# --- subtasks ---
@router.get("/{task_id}/subtasks", response_model=list[SubtaskResponse])
async def list_subtasks(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.list_subtasks(task_id, make_actor(actor, request))


# --- issue links ---
@router.get("/{task_id}/links", response_model=list[LinkResponse])
async def list_links(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.list_links(task_id, make_actor(actor, request))


@router.post("/{task_id}/links", response_model=list[LinkResponse])
async def add_link(
    task_id: str,
    payload: LinkRequest,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.update"))],
):
    return await service.add_link(task_id, payload.target_task_id, payload.link_type, make_actor(actor, request))


@router.delete("/{task_id}/links/{target_id}", response_model=list[LinkResponse])
async def remove_link(
    task_id: str,
    target_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.update"))],
):
    return await service.remove_link(task_id, target_id, make_actor(actor, request))


# --- watchers ---
@router.post("/{task_id}/watchers", response_model=TaskResponse)
async def add_watcher(
    task_id: str,
    payload: WatcherRequest,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.add_watcher(task_id, payload.user_id, make_actor(actor, request))


@router.delete("/{task_id}/watchers/{user_id}", response_model=TaskResponse)
async def remove_watcher(
    task_id: str,
    user_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.remove_watcher(task_id, user_id, make_actor(actor, request))


# --- archive / delete ---
@router.post("/{task_id}/archive", response_model=TaskResponse)
async def archive_task(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.update"))],
):
    return await service.archive(task_id, make_actor(actor, request))


@router.delete("/{task_id}", response_model=MessageResponse)
async def delete_task(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    # Project membership is enforced in the service (same gate as create/move).
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    await service.soft_delete(task_id, make_actor(actor, request))
    return MessageResponse(message="Task deleted")


# --- activity / history ---
@router.get("/{task_id}/activity", response_model=list[ActivityResponse])
async def task_activity(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.task_activity(task_id, make_actor(actor, request))


@router.get("/{task_id}/history", response_model=list[StatusHistoryResponse])
async def status_history(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.status_history(task_id, make_actor(actor, request))


@router.get("/{task_id}/assignments", response_model=list[AssignmentHistoryResponse])
async def assignment_history(
    task_id: str,
    request: Request,
    service: TaskServiceDep,
    actor: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.assignment_history(task_id, make_actor(actor, request))


# --- comments ---
@router.get("/{task_id}/comments", response_model=list[CommentResponse])
async def list_comments(
    task_id: str,
    service: CommentServiceDep,
    _: Annotated[CurrentUser, Depends(require("task.read"))],
):
    return await service.list_comments(task_id)


@router.post("/{task_id}/comments", response_model=CommentResponse, status_code=201)
async def add_comment(
    task_id: str,
    payload: CommentCreate,
    request: Request,
    service: CommentServiceDep,
    # "Comment on tasks" (task.comment) is the toggle users see in the Tasks module,
    # so gate commenting on that (not the separate comment.create).
    actor: Annotated[CurrentUser, Depends(require("task.comment"))],
):
    return await service.add_comment(task_id, payload.body, make_actor(actor, request))


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
async def edit_comment(
    comment_id: str,
    payload: CommentUpdate,
    request: Request,
    service: CommentServiceDep,
    actor: Annotated[CurrentUser, Depends(require("comment.update"))],
):
    return await service.edit_comment(comment_id, payload.body, make_actor(actor, request))


@router.delete("/comments/{comment_id}", response_model=MessageResponse)
async def delete_comment(
    comment_id: str,
    request: Request,
    service: CommentServiceDep,
    actor: Annotated[CurrentUser, Depends(require("comment.delete"))],
):
    await service.delete_comment(comment_id, make_actor(actor, request))
    return MessageResponse(message="Comment deleted")
