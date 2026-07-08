"""Shared FastAPI dependencies: DB wiring, DI factories, auth & RBAC guards."""
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import settings
from app.core.database import get_database
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import has_permission
from app.core.security import decode_token, JWTError
from app.core.tenant import TenantContext
from app.core.tenant_roles import effective_permissions
from app.repositories.organization_repository import OrganizationMemberRepository
from app.repositories.workspace_repository import WorkspaceMemberRepository
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.comment_repository import CommentRepository
from app.repositories.daily_update_repository import DailyUpdateRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.space_role_repository import SpaceRoleRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.custom_field_repository import CustomFieldRepository
from app.repositories.list_repository import ListRepository
from app.repositories.status_history_repository import StatusHistoryRepository
from app.repositories.status_template_repository import StatusTemplateRepository
from app.repositories.worklog_repository import WorklogRepository
from app.repositories.task_assignment_repository import TaskAssignmentRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.comment_service import CommentService
from app.services.daily_update_service import DailyUpdateService
from app.services.dashboard_service import DashboardService
from app.services.user_dashboard_service import UserDashboardService
from app.services.saved_filter_service import SavedFilterService
from app.services.label_service import LabelService
from app.services.notification_service import NotificationService
from app.services.custom_field_service import CustomFieldService
from app.services.list_service import ListService
from app.services.project_service import ProjectService
from app.services.role_service import RoleService
from app.services.task_service import TaskService
from app.services.user_service import ActorContext, UserService

bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> AsyncIOMotorDatabase:
    return get_database()


DbDep = Annotated[AsyncIOMotorDatabase, Depends(get_db)]


# --- Repository / service factories ---
def get_user_repo(db: DbDep) -> UserRepository:
    return UserRepository(db)


def get_role_repo(db: DbDep) -> RoleRepository:
    return RoleRepository(db)


def get_token_repo(db: DbDep) -> RefreshTokenRepository:
    return RefreshTokenRepository(db)


def get_audit_repo(db: DbDep) -> ActivityLogRepository:
    return ActivityLogRepository(db)


def get_audit_service(
    repo: Annotated[ActivityLogRepository, Depends(get_audit_repo)],
) -> AuditService:
    return AuditService(repo)


def get_role_service(
    roles: Annotated[RoleRepository, Depends(get_role_repo)],
) -> RoleService:
    return RoleService(roles)


def get_notification_repo(db: DbDep) -> NotificationRepository:
    return NotificationRepository(db)


def get_notification_service(
    repo: Annotated[NotificationRepository, Depends(get_notification_repo)],
) -> NotificationService:
    return NotificationService(repo)


def get_user_service(
    users: Annotated[UserRepository, Depends(get_user_repo)],
    roles: Annotated[RoleService, Depends(get_role_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
) -> UserService:
    return UserService(users, roles, audit, notifications)


def get_project_repo(db: DbDep) -> ProjectRepository:
    return ProjectRepository(db)


def get_project_member_repo(db: DbDep) -> ProjectMemberRepository:
    return ProjectMemberRepository(db)


def get_status_template_repo(db: DbDep) -> StatusTemplateRepository:
    return StatusTemplateRepository(db)


def get_space_role_repo(db: DbDep) -> SpaceRoleRepository:
    return SpaceRoleRepository(db)


def get_project_service(
    projects: Annotated[ProjectRepository, Depends(get_project_repo)],
    members: Annotated[ProjectMemberRepository, Depends(get_project_member_repo)],
    users: Annotated[UserRepository, Depends(get_user_repo)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    status_templates: Annotated[StatusTemplateRepository, Depends(get_status_template_repo)],
    space_roles: Annotated[SpaceRoleRepository, Depends(get_space_role_repo)],
) -> ProjectService:
    return ProjectService(projects, members, users, audit, notifications, status_templates, space_roles)


def get_task_repo(db: DbDep) -> TaskRepository:
    return TaskRepository(db)


def get_list_repo(db: DbDep) -> ListRepository:
    return ListRepository(db)


def get_list_service(
    lists: Annotated[ListRepository, Depends(get_list_repo)],
    projects: Annotated[ProjectRepository, Depends(get_project_repo)],
    members: Annotated[ProjectMemberRepository, Depends(get_project_member_repo)],
    tasks: Annotated[TaskRepository, Depends(get_task_repo)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> ListService:
    return ListService(lists, projects, members, tasks, audit)


def get_custom_field_repo(db: DbDep) -> CustomFieldRepository:
    return CustomFieldRepository(db)


def get_custom_field_service(
    fields: Annotated[CustomFieldRepository, Depends(get_custom_field_repo)],
    projects: Annotated[ProjectRepository, Depends(get_project_repo)],
    members: Annotated[ProjectMemberRepository, Depends(get_project_member_repo)],
    lists: Annotated[ListRepository, Depends(get_list_repo)],
    users: Annotated[UserRepository, Depends(get_user_repo)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    tasks: Annotated[TaskRepository, Depends(get_task_repo)],
) -> CustomFieldService:
    return CustomFieldService(fields, projects, members, lists, users, audit, tasks)


def get_comment_repo(db: DbDep) -> CommentRepository:
    return CommentRepository(db)


def get_status_history_repo(db: DbDep) -> StatusHistoryRepository:
    return StatusHistoryRepository(db)


def get_worklog_repo(db: DbDep) -> WorklogRepository:
    return WorklogRepository(db)


def get_assignment_repo(db: DbDep) -> TaskAssignmentRepository:
    return TaskAssignmentRepository(db)


def get_task_service(
    tasks: Annotated[TaskRepository, Depends(get_task_repo)],
    projects: Annotated[ProjectRepository, Depends(get_project_repo)],
    members: Annotated[ProjectMemberRepository, Depends(get_project_member_repo)],
    users: Annotated[UserRepository, Depends(get_user_repo)],
    history: Annotated[StatusHistoryRepository, Depends(get_status_history_repo)],
    assignments: Annotated[TaskAssignmentRepository, Depends(get_assignment_repo)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
    worklogs: Annotated[WorklogRepository, Depends(get_worklog_repo)],
    lists: Annotated[ListRepository, Depends(get_list_repo)],
    custom_fields: Annotated[CustomFieldRepository, Depends(get_custom_field_repo)],
) -> TaskService:
    return TaskService(tasks, projects, members, users, history, assignments, audit, notifications, worklogs, lists,
                       custom_fields)


def get_comment_service(
    comments: Annotated[CommentRepository, Depends(get_comment_repo)],
    tasks: Annotated[TaskRepository, Depends(get_task_repo)],
    users: Annotated[UserRepository, Depends(get_user_repo)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> CommentService:
    return CommentService(comments, tasks, users, audit)


def get_daily_update_repo(db: DbDep) -> DailyUpdateRepository:
    return DailyUpdateRepository(db)


def get_daily_update_service(
    updates: Annotated[DailyUpdateRepository, Depends(get_daily_update_repo)],
    users: Annotated[UserRepository, Depends(get_user_repo)],
    tasks: Annotated[TaskRepository, Depends(get_task_repo)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    notifications: Annotated[NotificationService, Depends(get_notification_service)],
) -> DailyUpdateService:
    return DailyUpdateService(updates, users, tasks, audit, notifications)


def get_dashboard_service(db: DbDep) -> DashboardService:
    return DashboardService(db)


def get_user_dashboard_service(db: DbDep) -> UserDashboardService:
    return UserDashboardService(db)


def get_saved_filter_service(db: DbDep) -> SavedFilterService:
    return SavedFilterService(db)


def get_label_service(db: DbDep) -> LabelService:
    return LabelService(db)



def get_auth_service(
    users: Annotated[UserRepository, Depends(get_user_repo)],
    roles: Annotated[RoleService, Depends(get_role_service)],
    tokens: Annotated[RefreshTokenRepository, Depends(get_token_repo)],
) -> AuthService:
    return AuthService(users, roles, tokens)


# --- Current user / RBAC ---
@dataclass
class CurrentUser:
    id: str
    email: str
    full_name: str
    roles: list[str]
    permissions: set[str] = field(default_factory=set)
    status: str = "active"
    raw: dict = field(default_factory=dict)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    users: Annotated[UserRepository, Depends(get_user_repo)],
    roles: Annotated[RoleService, Depends(get_role_service)],
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise AuthenticationError("Invalid or expired token")
    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token type")

    user = await users.find_safe_by_id(payload.get("sub"))
    if not user or user.get("is_deleted") or user.get("status") != "active":
        raise AuthenticationError("Account is not active")

    # Permissions are resolved from the DB each request so role edits take effect
    # immediately (DB-driven RBAC), rather than trusting stale token claims.
    role_keys, perms = await roles.aggregate_for_user(user.get("role_ids", []))
    return CurrentUser(
        id=str(user["_id"]),
        email=user["email"],
        full_name=user["full_name"],
        roles=role_keys,
        permissions=perms,
        status=user["status"],
        raw=user,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def make_actor(user: CurrentUser, request: Request) -> ActorContext:
    """Build an audit/access actor context from the current user and request."""
    return ActorContext(
        user_id=user.id,
        ip=request.client.host if request.client else None,
        permissions=user.permissions,
        roles=user.roles,
    )


async def get_tenant_context(
    request: Request,
    current: CurrentUserDep,
    db: DbDep,
) -> TenantContext:
    """Resolve and authorize the active organization/workspace for this request.

    The active workspace comes from the `X-Workspace-Id` header (or the user's
    first workspace membership as a fallback). Membership is verified BEFORE any
    tenant data is touched — a non-member gets 403, making cross-tenant access
    impossible. (Wired into tenant-scoped routes in later phases.)
    """
    ws_members = WorkspaceMemberRepository(db)
    org_members = OrganizationMemberRepository(db)

    ws_id = request.headers.get(settings.TENANT_HEADER_WORKSPACE)
    if not ws_id:
        memberships = await ws_members.list_for_user(current.id)
        if not memberships:
            raise PermissionDeniedError("No active workspace for this user")
        ws_id = str(memberships[0]["workspace_id"])

    membership = await ws_members.find_membership(ws_id, current.id)
    if not membership:
        raise PermissionDeniedError("You are not a member of this workspace")

    organization_id = str(membership["organization_id"])
    org_membership = await org_members.find_membership(organization_id, current.id)
    org_role = org_membership.get("org_role") if org_membership else None
    workspace_role = membership.get("workspace_role")

    return TenantContext(
        organization_id=organization_id,
        workspace_id=ws_id,
        org_role=org_role,
        workspace_role=workspace_role,
        permissions=effective_permissions(org_role, workspace_role),
    )


TenantDep = Annotated[TenantContext, Depends(get_tenant_context)]


def require(*required_permissions: str):
    """Dependency factory enforcing that the current user holds ALL given permissions."""

    async def _checker(user: CurrentUserDep) -> CurrentUser:
        for perm in required_permissions:
            if not has_permission(user.permissions, perm):
                raise PermissionDeniedError(
                    f"Missing required permission: {perm}",
                    {"required": list(required_permissions)},
                )
        return user

    return _checker
