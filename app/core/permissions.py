"""Permission catalog and default role → permission matrix (DB-driven RBAC).

This module is the *seed* source of truth. `seed_permissions()` mirrors the
catalog into the `permissions` collection (so the frontend reads permissions
from the DB, never hardcoded), and `SYSTEM_ROLES` seeds the `roles` collection.
A Super Admin can then edit roles at runtime; the database is authoritative.
`WILDCARD` ("*") grants every permission.

Adding a new module = add one entry to PERMISSION_CATALOG. Everything else
(the flat PERMISSIONS list, the DB seed, the catalog endpoint, and the Admin
role's full grant) derives from it automatically — the system is extensible by
design.
"""

WILDCARD = "*"

# --- Grouped permission catalog (single source of truth) ---
# Each module: { key, module, permissions: [{ key, label }] }.
PERMISSION_CATALOG: list[dict] = [
    {"key": "users", "module": "Users", "permissions": [
        {"key": "user.create", "label": "Create users"},
        {"key": "user.read", "label": "View users"},
        {"key": "user.update", "label": "Edit users"},
        {"key": "user.delete", "label": "Delete users"},
    ]},
    {"key": "spaces", "module": "Spaces", "permissions": [
        {"key": "project.create", "label": "Create spaces"},
        {"key": "project.read", "label": "View spaces"},
        {"key": "project.update", "label": "Edit spaces"},
        {"key": "project.delete", "label": "Delete spaces"},
        {"key": "project.archive", "label": "Archive spaces"},
        {"key": "project.restore", "label": "Restore spaces"},
        {"key": "project.member.manage", "label": "Manage space members & roles"},
    ]},
    {"key": "lists", "module": "Lists", "permissions": [
        {"key": "list.create", "label": "Create lists"},
        {"key": "list.read", "label": "View lists"},
        {"key": "list.update", "label": "Edit lists"},
        {"key": "list.delete", "label": "Delete lists"},
    ]},
    {"key": "tasks", "module": "Tasks", "permissions": [
        {"key": "task.create", "label": "Create tasks"},
        {"key": "task.read", "label": "View tasks"},
        {"key": "task.update", "label": "Edit tasks"},
        {"key": "task.delete", "label": "Delete tasks"},
        {"key": "task.assign", "label": "Assign tasks"},
        {"key": "task.status.update", "label": "Change task status"},
        {"key": "task.priority.update", "label": "Change task priority"},
        {"key": "task.comment", "label": "Comment on tasks"},
        {"key": "task.attachments", "label": "Manage task attachments"},
    ]},
    {"key": "customfields", "module": "Custom fields", "permissions": [
        {"key": "customfield.create", "label": "Create custom fields"},
        {"key": "customfield.read", "label": "View custom fields"},
        {"key": "customfield.update", "label": "Edit custom fields"},
        {"key": "customfield.delete", "label": "Delete custom fields"},
    ]},
    {"key": "views", "module": "Views", "permissions": [
        {"key": "view.create", "label": "Create views"},
        {"key": "view.update", "label": "Edit views"},
        {"key": "view.delete", "label": "Delete views"},
    ]},
    {"key": "comments", "module": "Comments", "permissions": [
        {"key": "comment.create", "label": "Create comments"},
        {"key": "comment.read", "label": "View comments"},
        {"key": "comment.update", "label": "Edit comments"},
        {"key": "comment.delete", "label": "Delete comments"},
    ]},
    {"key": "roles", "module": "Roles & Permissions", "permissions": [
        {"key": "permission.manage", "label": "Access the Permission setting page"},
        {"key": "role.create", "label": "Create roles"},
        {"key": "role.read", "label": "View roles"},
        {"key": "role.update", "label": "Edit roles"},
        {"key": "role.delete", "label": "Delete roles"},
    ]},
    {"key": "daily", "module": "Daily updates", "permissions": [
        {"key": "dailyupdate.create", "label": "Create daily updates"},
        {"key": "dailyupdate.read.self", "label": "Read own daily updates"},
        {"key": "dailyupdate.read.team", "label": "Read team daily updates"},
        {"key": "dailyupdate.read.all", "label": "Read all daily updates"},
        {"key": "dailyupdate.acknowledge", "label": "Acknowledge daily updates"},
    ]},
    {"key": "reports", "module": "Reports", "permissions": [
        {"key": "report.view.self", "label": "View own reports"},
        {"key": "report.view.team", "label": "View team reports"},
        {"key": "report.view.all", "label": "View all reports"},
    ]},
    {"key": "dashboards", "module": "Dashboards", "permissions": [
        {"key": "dashboard.view.team", "label": "View team dashboards"},
        {"key": "dashboard.view.admin", "label": "View admin dashboards"},
    ]},
    {"key": "admin", "module": "Administration", "permissions": [
        {"key": "audit.read", "label": "View audit log"},
        {"key": "admin.settings", "label": "Manage app settings"},
    ]},
]

# Flat list of every known permission string (derived from the catalog).
PERMISSIONS: list[str] = [p["key"] for group in PERMISSION_CATALOG for p in group["permissions"]]


def _module(*keys: str) -> list[str]:
    """All permission keys for one or more catalog module keys."""
    out: list[str] = []
    for group in PERMISSION_CATALOG:
        if group["key"] in keys:
            out += [p["key"] for p in group["permissions"]]
    return out


# --- Default role → permission matrix ---
# Employee: work inside the spaces they belong to (space membership is the finer
# gate, enforced in the services) — manage lists/views/tasks, collaborate, own reports.
EMPLOYEE_PERMS = sorted(set(
    ["project.read", "project.create", "comment.read"]
    + _module("lists")          # list.create / read / update / delete
    + _module("customfields")   # customfield.create / read / update / delete
    + _module("views")   # view.create / update / delete
    + ["task.create", "task.read", "task.update", "task.status.update",
       "task.priority.update", "task.assign", "task.comment", "task.attachments"]
    + ["comment.create", "comment.update", "comment.delete"]
    + ["dailyupdate.create", "dailyupdate.read.self", "report.view.self"]
))

# Admin: every explicit permission (manages users, spaces, tasks, roles, reports,
# settings). Differs from Super Admin only in lacking the "*" future-proof wildcard.
ADMIN_PERMS = sorted(set(PERMISSIONS))

SYSTEM_ROLES: list[dict] = [
    {"key": "super_admin", "name": "Super Admin", "level": 100, "permissions": [WILDCARD]},
    {"key": "admin", "name": "Admin", "level": 80, "permissions": ADMIN_PERMS},
    {"key": "employee", "name": "Employee", "level": 20, "permissions": EMPLOYEE_PERMS},
]

# Roles that were removed from the system; startup cleanup reassigns their users
# to Employee and deletes the leftover role docs.
RETIRED_ROLE_KEYS = ["manager", "team_lead"]


def has_permission(granted: set[str], required: str) -> bool:
    return WILDCARD in granted or required in granted
