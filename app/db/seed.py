"""Idempotent data seeding run on startup: system roles + first Super Admin."""
import logging

from app.core.config import settings
from app.core.permissions import PERMISSION_CATALOG, RETIRED_ROLE_KEYS, SYSTEM_ROLES
from app.core.security import hash_password
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)


async def seed_permissions(db) -> None:
    """Mirror the permission catalog into the `permissions` collection so it is
    DB-driven (the frontend reads permissions from the DB, never hardcoded)."""
    now = utcnow()
    order = 0
    for group in PERMISSION_CATALOG:
        for perm in group["permissions"]:
            await db["permissions"].update_one(
                {"key": perm["key"]},
                {"$set": {
                    "key": perm["key"], "label": perm["label"],
                    "module": group["module"], "module_key": group["key"],
                    "order": order, "updated_at": now,
                }, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            order += 1
    # Drop any permission docs no longer in the catalog.
    valid = [p["key"] for g in PERMISSION_CATALOG for p in g["permissions"]]
    await db["permissions"].delete_many({"key": {"$nin": valid}})
    logger.info("Seeded %d permissions", len(valid))


async def seed_roles(db) -> None:
    repo = RoleRepository(db)
    now = utcnow()
    for role in SYSTEM_ROLES:
        await repo.upsert_system_role({**role, "created_at": now})
    logger.info("Seeded %d system roles", len(SYSTEM_ROLES))
    await _retire_old_roles(db)


async def _retire_old_roles(db) -> None:
    """Reassign any users on a retired role (Manager / Team Lead) to Employee,
    then delete the retired role documents. Idempotent."""
    employee = await db["roles"].find_one({"key": "employee"})
    if not employee:
        return
    for key in RETIRED_ROLE_KEYS:
        role = await db["roles"].find_one({"key": key})
        if not role:
            continue
        # Swap the retired role id for the Employee id on every affected user.
        await db["users"].update_many(
            {"role_ids": role["_id"]},
            {"$addToSet": {"role_ids": employee["_id"]}},
        )
        result = await db["users"].update_many(
            {"role_ids": role["_id"]},
            {"$pull": {"role_ids": role["_id"]}},
        )
        await db["roles"].delete_one({"_id": role["_id"]})
        logger.info("Retired role '%s'; reassigned %d users to Employee", key, result.modified_count)


async def seed_superadmin(db) -> None:
    # Development-only: never auto-create a default admin outside development,
    # so production environments cannot ship with known credentials.
    if settings.ENVIRONMENT != "development":
        logger.info("Skipping default super-admin seed (ENVIRONMENT=%s)", settings.ENVIRONMENT)
        return

    users = UserRepository(db)
    roles = RoleRepository(db)

    existing = await users.find_by_email(settings.FIRST_SUPERADMIN_EMAIL)
    if existing:
        return

    super_role = await roles.find_by_key("super_admin")
    if not super_role:
        logger.warning("super_admin role missing; cannot seed first super admin")
        return

    now = utcnow()
    await users.insert_one(
        {
            "email": settings.FIRST_SUPERADMIN_EMAIL.lower(),
            "password_hash": hash_password(settings.FIRST_SUPERADMIN_PASSWORD),
            "full_name": settings.FIRST_SUPERADMIN_NAME,
            "role_ids": [super_role["_id"]],
            "manager_id": None,
            "designation": "System Administrator",
            "department": "IT",
            "timezone": "UTC",
            "avatar_url": None,
            "status": "active",
            "notification_prefs": {"in_app": True, "email": False},
            "is_deleted": False,
            "deleted_at": None,
            "last_login_at": None,
            "password_changed_at": now,
            "created_at": now,
            "updated_at": now,
        }
    )
    logger.info("Seeded first super admin: %s", settings.FIRST_SUPERADMIN_EMAIL)


async def seed_sample_projects(db) -> None:
    """Development-only: a sample project with members so the UI has data."""
    if settings.ENVIRONMENT != "development":
        return

    from app.repositories.project_member_repository import ProjectMemberRepository
    from app.repositories.project_repository import ProjectRepository

    users = UserRepository(db)
    projects = ProjectRepository(db)
    members = ProjectMemberRepository(db)
    roles = RoleRepository(db)

    if await projects.find_by_key("DAT"):
        return

    admin = await users.find_by_email(settings.FIRST_SUPERADMIN_EMAIL)
    if not admin:
        return

    now = utcnow()

    # A couple of sample teammates (idempotent by email).
    async def ensure_user(email, name, role_key, designation):
        existing = await users.find_by_email(email)
        if existing:
            return existing["_id"]
        role = await roles.find_by_key(role_key)
        created = await users.insert_one({
            "email": email, "password_hash": hash_password("Password123!"),
            "full_name": name, "role_ids": [role["_id"]] if role else [],
            "manager_id": None, "designation": designation, "department": "Engineering",
            "timezone": "UTC", "avatar_url": None, "status": "active",
            "notification_prefs": {"in_app": True, "email": False},
            "is_deleted": False, "deleted_at": None, "last_login_at": None,
            "password_changed_at": now, "created_at": now, "updated_at": now,
        })
        return created["_id"]

    lead_id = await ensure_user("lead@dailyactivity.local", "Tara Lead", "employee", "Team Lead")
    dev_id = await ensure_user("dev@dailyactivity.local", "Dan Dev", "employee", "Developer")
    test_id = await ensure_user("qa@dailyactivity.local", "Quinn QA", "employee", "QA Engineer")

    project = await projects.insert_one({
        "key": "DAT", "name": "Daily Activity Tracker",
        "description": "Sample seeded project for development.",
        "status": "active", "owner_id": admin["_id"],
        "start_date": "2026-06-01", "end_date": None, "task_counter": 0,
        "is_deleted": False, "deleted_at": None, "created_at": now, "updated_at": now,
    })
    pid = str(project["_id"])

    seed_members = [
        (admin["_id"], "admin"),
        (lead_id, "employee"),
        (dev_id, "employee"),
        (test_id, "employee"),
    ]
    for uid, prole in seed_members:
        await members.add(
            project_id=pid, user_id=str(uid), project_role=prole,
            added_by=str(admin["_id"]), added_at=now,
        )
    logger.info("Seeded sample project DAT with %d members", len(seed_members))


async def seed_sample_tasks(db) -> None:
    """Development-only: a few tasks across the workflow on the sample project."""
    if settings.ENVIRONMENT != "development":
        return

    from app.repositories.project_member_repository import ProjectMemberRepository
    from app.repositories.project_repository import ProjectRepository

    projects = ProjectRepository(db)
    members = ProjectMemberRepository(db)
    users = UserRepository(db)

    project = await projects.find_by_key("DAT")
    if not project:
        return
    if await db.tasks.count_documents({"project_id": project["_id"]}) > 0:
        return

    admin = await users.find_by_email(settings.FIRST_SUPERADMIN_EMAIL)
    dev = await users.find_by_email("dev@dailyactivity.local")
    qa = await users.find_by_email("qa@dailyactivity.local")
    now = utcnow()
    pid = str(project["_id"])

    samples = [
        {"title": "Set up CI pipeline", "status": "in_progress", "priority": "high",
         "assignee": dev, "labels": ["devops"], "estimate_hours": 8},
        {"title": "Design login screen", "status": "review", "priority": "medium",
         "assignee": dev, "labels": ["frontend", "ui"], "estimate_hours": 5},
        {"title": "Write API tests", "status": "testing", "priority": "high",
         "assignee": qa, "labels": ["backend", "qa"], "estimate_hours": 6},
        {"title": "Draft release notes", "status": "backlog", "priority": "low",
         "assignee": None, "labels": ["docs"], "estimate_hours": 2},
        {"title": "Fix logout redirect bug", "status": "blocked", "priority": "critical",
         "assignee": dev, "labels": ["bug"], "estimate_hours": 3},
        {"title": "Deploy v1 to staging", "status": "completed", "priority": "medium",
         "assignee": qa, "labels": ["devops"], "estimate_hours": 4},
    ]

    for i, sample in enumerate(samples, start=1):
        await db.projects.update_one({"_id": project["_id"]}, {"$inc": {"task_counter": 1}})
        assignee = sample["assignee"]
        await db.tasks.insert_one({
            "project_id": project["_id"], "key": f"DAT-{i}", "title": sample["title"],
            "description": f"Seeded sample task: {sample['title']}.", "type": "task",
            "status": sample["status"], "priority": sample["priority"],
            "reporter_id": admin["_id"] if admin else None,
            "assignee_id": assignee["_id"] if assignee else None,
            "watchers": [], "labels": sample["labels"], "due_date": None,
            "estimate_hours": sample["estimate_hours"], "actual_hours": 0,
            "comment_count": 0, "is_archived": False, "is_deleted": False, "deleted_at": None,
            "created_at": now, "updated_at": now,
        })
    logger.info("Seeded %d sample tasks on project DAT", len(samples))


async def seed_sample_daily_updates(db) -> None:
    """Development-only: a few daily updates (incl. a blocker) for the sample team."""
    if settings.ENVIRONMENT != "development":
        return

    from datetime import timedelta

    from app.repositories.project_repository import ProjectRepository

    users = UserRepository(db)
    projects = ProjectRepository(db)

    project = await projects.find_by_key("DAT")
    if not project:
        return
    if await db.daily_updates.count_documents({}) > 0:
        return

    dev = await users.find_by_email("dev@dailyactivity.local")
    qa = await users.find_by_email("qa@dailyactivity.local")
    if not dev:
        return

    task1 = await db.tasks.find_one({"key": "DAT-1"})
    task3 = await db.tasks.find_one({"key": "DAT-3"})
    now = utcnow()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    def entry(task, work, hours, blockers=None, status="in_progress"):
        return {
            "project_id": project["_id"],
            "task_id": task["_id"] if task else None,
            "work_done": work, "hours_spent": hours,
            "blockers": blockers, "status": status,
        }

    docs = [
        {"user_id": dev["_id"], "date": yesterday,
         "entries": [entry(task1, "Configured CI runners", 4.0)],
         "tomorrow_plan": "Finish pipeline", "total_hours": 4.0, "has_blockers": False},
        {"user_id": dev["_id"], "date": today,
         "entries": [entry(task1, "Pipeline caching + tests", 3.5, "Waiting on infra secrets", "blocked")],
         "tomorrow_plan": "Unblock and deploy", "total_hours": 3.5, "has_blockers": True},
    ]
    if qa:
        docs.append({"user_id": qa["_id"], "date": today,
                     "entries": [entry(task3, "Wrote 12 API tests", 5.0, None, "in_progress")],
                     "tomorrow_plan": "Cover edge cases", "total_hours": 5.0, "has_blockers": False})

    for d in docs:
        d.update({"mood": "good", "submitted_at": now, "created_at": now, "updated_at": now})
        await db.daily_updates.insert_one(d)
    logger.info("Seeded %d sample daily updates", len(docs))


async def seed_dashboard_demo(db) -> None:
    """Development-only: manager relationships + an overdue task so dashboards
    have meaningful team/delay data. Idempotent (uses targeted updates)."""
    if settings.ENVIRONMENT != "development":
        return
    from datetime import timedelta

    users = UserRepository(db)
    admin = await users.find_by_email(settings.FIRST_SUPERADMIN_EMAIL)
    lead = await users.find_by_email("lead@dailyactivity.local")
    dev = await users.find_by_email("dev@dailyactivity.local")
    qa = await users.find_by_email("qa@dailyactivity.local")
    if not (admin and lead and dev and qa):
        return

    # Tara Lead manages Dan & Quinn; admin manages Tara.
    await db.users.update_one({"_id": dev["_id"]}, {"$set": {"manager_id": lead["_id"]}})
    await db.users.update_one({"_id": qa["_id"]}, {"$set": {"manager_id": lead["_id"]}})
    await db.users.update_one({"_id": lead["_id"]}, {"$set": {"manager_id": admin["_id"]}})

    # Make one open task overdue for the "delayed tasks" widget.
    overdue_date = (utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")
    await db.tasks.update_one(
        {"key": "DAT-1"}, {"$set": {"due_date": overdue_date}}
    )
    logger.info("Seeded dashboard demo relationships + overdue task")


async def run_seed(db) -> None:
    await seed_permissions(db)
    await seed_roles(db)
    await seed_superadmin(db)
    await seed_sample_projects(db)
    await seed_sample_tasks(db)
    await seed_sample_daily_updates(db)
    await seed_dashboard_demo(db)
