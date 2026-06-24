"""Permission catalog and default role → permission matrix (DB-driven RBAC).

These constants are the *seed* source of truth. Once seeded into the `roles`
collection, a Super Admin can edit permissions at runtime; the database is then
authoritative. `WILDCARD` ("*") grants every permission.
"""

WILDCARD = "*"

# --- Permission catalog (single source of truth for known permission strings) ---
PERMISSIONS: list[str] = [
    # users
    "user.create", "user.read", "user.update", "user.delete",
    # roles
    "role.read", "role.manage",
    # projects
    "project.create", "project.read", "project.update", "project.delete",
    "project.member.manage",
    # tasks
    "task.create", "task.read", "task.update", "task.delete",
    "task.assign", "task.status.update",
    # daily updates
    "dailyupdate.create", "dailyupdate.read.self", "dailyupdate.read.team",
    "dailyupdate.read.all", "dailyupdate.acknowledge",
    # comments
    "comment.create", "comment.update", "comment.delete",
    # reports
    "report.view.self", "report.view.team", "report.view.all",
    # dashboards
    "dashboard.view.team", "dashboard.view.admin",
    # admin
    "audit.read", "admin.settings",
]

# --- System role definitions (key, display name, level, permissions) ---
EMPLOYEE_PERMS = [
    "project.read",
    "project.create",  # anyone can create a space; the creator becomes its owner/admin
    "task.create", "task.read", "task.update", "task.status.update",
    "dailyupdate.create", "dailyupdate.read.self",
    "comment.create", "comment.update", "comment.delete",
    "report.view.self",
]

TEAM_LEAD_PERMS = EMPLOYEE_PERMS + [
    "user.read",  # view team members; employees cannot browse the org directory
    "task.assign",
    "project.member.manage",
    "dailyupdate.read.team", "dailyupdate.acknowledge",
    "report.view.team",
    "dashboard.view.team",
]

MANAGER_PERMS = TEAM_LEAD_PERMS + [
    "project.create", "project.update",
    "dailyupdate.read.all",
    "report.view.all",
]

ADMIN_PERMS = sorted(set(MANAGER_PERMS + [
    "user.create", "user.update", "user.delete",
    "role.read",
    "project.delete",
    "task.delete",
    "dashboard.view.admin",
    "audit.read",
]))

SYSTEM_ROLES: list[dict] = [
    {"key": "super_admin", "name": "Super Admin", "level": 100, "permissions": [WILDCARD]},
    {"key": "admin", "name": "Admin", "level": 80, "permissions": ADMIN_PERMS},
    {"key": "manager", "name": "Manager", "level": 60, "permissions": sorted(set(MANAGER_PERMS))},
    {"key": "team_lead", "name": "Team Lead", "level": 40, "permissions": sorted(set(TEAM_LEAD_PERMS))},
    {"key": "employee", "name": "Employee", "level": 20, "permissions": sorted(set(EMPLOYEE_PERMS))},
]


def has_permission(granted: set[str], required: str) -> bool:
    return WILDCARD in granted or required in granted
