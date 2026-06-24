"""Two-level tenant RBAC: organization roles + workspace roles.

Effective permissions for a request = union(org_role.permissions,
workspace_role.permissions), evaluated within the active TenantContext.
The organization_owner holds WILDCARD within their org.
"""
from app.core.permissions import WILDCARD

# --- Organization-level roles ---
ORG_OWNER = "organization_owner"
ORG_ADMIN = "organization_admin"
ORG_MANAGER = "manager"
ORG_TEAM_LEAD = "team_lead"
ORG_EMPLOYEE = "employee"

# --- Workspace-level roles ---
WS_ADMIN = "workspace_admin"
WS_PROJECT_MANAGER = "project_manager"
WS_TEAM_LEAD = "team_lead"
WS_MEMBER = "member"
WS_VIEWER = "viewer"

# Base permission building blocks (reuse the existing permission strings).
_EMPLOYEE = [
    "project.read", "project.create",
    "task.create", "task.read", "task.update", "task.status.update",
    "dailyupdate.create", "dailyupdate.read.self",
    "comment.create", "comment.update", "comment.delete",
    "report.view.self",
]
_TEAM_LEAD = _EMPLOYEE + [
    "user.read", "task.assign", "project.member.manage",
    "dailyupdate.read.team", "dailyupdate.acknowledge",
    "report.view.team", "dashboard.view.team",
]
_MANAGER = _TEAM_LEAD + [
    "project.update", "dailyupdate.read.all", "report.view.all",
]
_ORG_ADMIN = sorted(set(_MANAGER + [
    "user.create", "user.update", "user.delete", "role.read",
    "project.delete", "task.delete", "dashboard.view.admin",
    "audit.read", "org.manage", "org.members.manage", "org.invite",
    "workspace.manage", "workspace.members.manage",
]))

ORG_ROLE_PERMISSIONS: dict[str, list[str]] = {
    ORG_OWNER: [WILDCARD],
    ORG_ADMIN: _ORG_ADMIN,
    ORG_MANAGER: sorted(set(_MANAGER + ["org.invite", "workspace.manage"])),
    ORG_TEAM_LEAD: sorted(set(_TEAM_LEAD)),
    ORG_EMPLOYEE: sorted(set(_EMPLOYEE)),
}

# Workspace roles grant permissions scoped to the active workspace.
_WS_MEMBER = [
    "project.read", "task.create", "task.read", "task.update", "task.status.update",
    "dailyupdate.create", "dailyupdate.read.self", "comment.create",
    "comment.update", "comment.delete", "report.view.self",
]
_WS_TEAM_LEAD = _WS_MEMBER + [
    "task.assign", "project.member.manage", "dailyupdate.read.team",
    "dailyupdate.acknowledge", "report.view.team", "dashboard.view.team", "user.read",
]
_WS_PM = _WS_TEAM_LEAD + ["project.create", "project.update", "report.view.all", "dailyupdate.read.all"]
_WS_ADMIN = sorted(set(_WS_PM + [
    "project.delete", "task.delete", "workspace.manage", "workspace.members.manage",
    "dashboard.view.admin", "audit.read",
]))

WS_ROLE_PERMISSIONS: dict[str, list[str]] = {
    WS_ADMIN: _WS_ADMIN,
    WS_PROJECT_MANAGER: sorted(set(_WS_PM)),
    WS_TEAM_LEAD: sorted(set(_WS_TEAM_LEAD)),
    WS_MEMBER: sorted(set(_WS_MEMBER)),
    WS_VIEWER: ["project.read", "task.read", "dailyupdate.read.self", "report.view.self"],
}

ORG_ROLES = list(ORG_ROLE_PERMISSIONS.keys())
WS_ROLES = list(WS_ROLE_PERMISSIONS.keys())


def effective_permissions(org_role: str | None, workspace_role: str | None) -> set[str]:
    perms: set[str] = set()
    if org_role:
        perms.update(ORG_ROLE_PERMISSIONS.get(org_role, []))
    if workspace_role:
        perms.update(WS_ROLE_PERMISSIONS.get(workspace_role, []))
    return perms


def org_role_from_legacy(legacy_role_key: str) -> str:
    """Map an old global role key to an organization role (used by migration)."""
    return {
        "super_admin": ORG_OWNER,
        "admin": ORG_ADMIN,
        "manager": ORG_MANAGER,
        "team_lead": ORG_TEAM_LEAD,
        "employee": ORG_EMPLOYEE,
    }.get(legacy_role_key, ORG_EMPLOYEE)


def workspace_role_from_legacy(legacy_role_key: str) -> str:
    return {
        "super_admin": WS_ADMIN,
        "admin": WS_ADMIN,
        "manager": WS_PROJECT_MANAGER,
        "team_lead": WS_TEAM_LEAD,
        "employee": WS_MEMBER,
    }.get(legacy_role_key, WS_MEMBER)
