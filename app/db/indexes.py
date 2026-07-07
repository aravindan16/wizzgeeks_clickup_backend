"""Index creation, run idempotently on startup.

Each module contributes its indexes here so the full set is created in one place.
createIndex is idempotent, so this is safe to run on every boot.
"""
import logging

from pymongo import ASCENDING, DESCENDING

from app.core.database import get_database

logger = logging.getLogger(__name__)


async def ensure_indexes() -> None:
    db = get_database()

    # users
    await db.users.create_index([("email", ASCENDING)], unique=True, name="uniq_email")
    await db.users.create_index([("manager_id", ASCENDING)], name="by_manager")
    await db.users.create_index(
        [("department", ASCENDING), ("status", ASCENDING)], name="dept_status"
    )

    # roles
    await db.roles.create_index([("key", ASCENDING)], unique=True, name="uniq_role_key")

    # refresh_tokens
    await db.refresh_tokens.create_index([("jti", ASCENDING)], unique=True, name="uniq_jti")
    await db.refresh_tokens.create_index([("user_id", ASCENDING)], name="rt_by_user")
    # TTL: auto-purge expired refresh tokens.
    await db.refresh_tokens.create_index(
        [("expires_at", ASCENDING)], expireAfterSeconds=0, name="rt_ttl"
    )

    # projects
    await db.projects.create_index([("key", ASCENDING)], unique=True, name="uniq_project_key")
    await db.projects.create_index([("status", ASCENDING)], name="proj_status")
    await db.projects.create_index([("owner_id", ASCENDING)], name="proj_owner")

    # project_members
    await db.project_members.create_index(
        [("project_id", ASCENDING), ("user_id", ASCENDING), ("removed_at", ASCENDING)],
        name="pm_project_user",
    )
    await db.project_members.create_index([("user_id", ASCENDING)], name="pm_by_user")

    # tasks
    await db.tasks.create_index([("key", ASCENDING)], unique=True, name="uniq_task_key")
    await db.tasks.create_index(
        [("project_id", ASCENDING), ("status", ASCENDING)], name="task_project_status"
    )
    await db.tasks.create_index(
        [("assignee_id", ASCENDING), ("status", ASCENDING)], name="task_assignee_status"
    )
    await db.tasks.create_index([("due_date", ASCENDING), ("status", ASCENDING)], name="task_due")
    await db.tasks.create_index(
        [("project_id", ASCENDING), ("updated_at", DESCENDING)], name="task_recent"
    )

    # comments
    await db.comments.create_index(
        [("entity_type", ASCENDING), ("entity_id", ASCENDING), ("created_at", ASCENDING)],
        name="comment_entity",
    )

    # status_history
    await db.status_history.create_index(
        [("task_id", ASCENDING), ("created_at", ASCENDING)], name="sh_task"
    )

    # task_assignments
    await db.task_assignments.create_index(
        [("task_id", ASCENDING), ("is_active", ASCENDING)], name="ta_task_active"
    )
    await db.task_assignments.create_index(
        [("assignee_id", ASCENDING), ("is_active", ASCENDING)], name="ta_assignee_active"
    )

    # daily_updates
    await db.daily_updates.create_index(
        [("user_id", ASCENDING), ("date", DESCENDING)], unique=True, name="uniq_user_date"
    )
    await db.daily_updates.create_index([("date", DESCENDING)], name="du_date")
    await db.daily_updates.create_index(
        [("has_blockers", ASCENDING), ("date", DESCENDING)], name="du_blockers"
    )

    # notifications
    await db.notifications.create_index(
        [("recipient_id", ASCENDING), ("is_read", ASCENDING), ("created_at", DESCENDING)],
        name="notif_recipient",
    )
    # TTL: auto-purge notifications after 90 days.
    await db.notifications.create_index(
        [("created_at", ASCENDING)], expireAfterSeconds=90 * 24 * 3600, name="notif_ttl"
    )

    # --- Multi-tenancy ---
    # organizations
    await db.organizations.create_index([("slug", ASCENDING)], unique=True, name="uniq_org_slug")
    await db.organizations.create_index([("owner_id", ASCENDING)], name="org_owner")

    # organization_members
    await db.organization_members.create_index(
        [("organization_id", ASCENDING), ("user_id", ASCENDING)], unique=True, name="uniq_org_member"
    )
    await db.organization_members.create_index([("user_id", ASCENDING)], name="orgmember_by_user")

    # workspaces
    await db.workspaces.create_index([("organization_id", ASCENDING)], name="ws_by_org")
    await db.workspaces.create_index(
        [("organization_id", ASCENDING), ("key", ASCENDING)], unique=True, name="uniq_ws_key"
    )

    # workspace_members
    await db.workspace_members.create_index(
        [("workspace_id", ASCENDING), ("user_id", ASCENDING)], name="ws_member_unique"
    )
    await db.workspace_members.create_index([("user_id", ASCENDING)], name="wsmember_by_user")
    await db.workspace_members.create_index([("organization_id", ASCENDING)], name="wsmember_by_org")

    # workspace_invitations
    await db.workspace_invitations.create_index([("token_hash", ASCENDING)], name="invite_token")
    await db.workspace_invitations.create_index(
        [("organization_id", ASCENDING), ("email", ASCENDING)], name="invite_org_email"
    )

    # activity_logs (audit trail)
    await db.activity_logs.create_index(
        [("entity_type", ASCENDING), ("entity_id", ASCENDING), ("created_at", DESCENDING)],
        name="al_entity",
    )
    await db.activity_logs.create_index(
        [("actor_id", ASCENDING), ("created_at", DESCENDING)], name="al_actor"
    )
    await db.activity_logs.create_index([("action", ASCENDING)], name="al_action")

    logger.info("Indexes ensured")
