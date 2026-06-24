"""Migration 0001 — single-tenant → multi-tenant.

Creates one legacy organization + default workspace, backfills org/workspace
memberships for all existing users, and stamps organization_id/workspace_id on
all tenant-owned records. Idempotent and reversible.

Usage (from backend/, venv active):
    python -m app.db.migrations.m0001_multitenant            # DRY-RUN (no writes)
    python -m app.db.migrations.m0001_multitenant --apply    # APPLY
    python -m app.db.migrations.m0001_multitenant --rollback # ROLLBACK

DRY-RUN reports exactly what APPLY would change without modifying data.
"""
import argparse
import asyncio

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.core.tenant_roles import org_role_from_legacy, workspace_role_from_legacy
from app.utils.datetime import utcnow

LEGACY_ORG_SLUG = "wizzgeeks"
LEGACY_ORG_NAME = "Wizzgeeks"
LEGACY_WS_KEY = "DEV"
LEGACY_WS_NAME = "Default Workspace"

# Collections that carry both organization_id and workspace_id.
WS_SCOPED = [
    "projects", "tasks", "daily_updates", "comments",
    "status_history", "task_assignments", "project_members",
]
# Collections that carry organization_id only.
ORG_ONLY = ["notifications", "activity_logs", "recent_items", "starred_items"]


async def _legacy_role_key(db, user) -> str:
    role_ids = user.get("role_ids", [])
    if not role_ids:
        return "employee"
    role = await db.roles.find_one({"_id": role_ids[0]}, {"key": 1})
    return role.get("key", "employee") if role else "employee"


async def run(db, *, apply: bool, rollback: bool = False) -> dict:
    report: dict = {"mode": "apply" if apply else ("rollback" if rollback else "dry-run"), "steps": []}

    def log(msg, **data):
        report["steps"].append({"msg": msg, **data})
        print(f"  {msg}" + (f"  {data}" if data else ""))

    if rollback:
        return await _rollback(db, log, report)

    # 1) Legacy organization + owner
    admin = await db.users.find_one({"email": settings.FIRST_SUPERADMIN_EMAIL}) \
        or await db.users.find_one({})
    if not admin:
        log("No users found — nothing to migrate")
        return report
    owner_id = admin["_id"]

    org = await db.organizations.find_one({"slug": LEGACY_ORG_SLUG})
    if org:
        org_id = org["_id"]
        log("Legacy org exists", org_id=str(org_id))
    elif apply:
        now = utcnow()
        res = await db.organizations.insert_one({
            "name": LEGACY_ORG_NAME, "slug": LEGACY_ORG_SLUG, "owner_id": owner_id,
            "plan": "free", "status": "active",
            "settings": {"timezone": "UTC", "allow_invites": True},
            "created_at": now, "updated_at": now,
        })
        org_id = res.inserted_id
        log("Created legacy org", org_id=str(org_id))
    else:
        org_id = None
        log("WOULD create legacy org", slug=LEGACY_ORG_SLUG, owner=str(owner_id))

    # 2) Default workspace
    ws = await db.workspaces.find_one({"slug": LEGACY_WS_KEY}) if False else \
        (await db.workspaces.find_one({"key": LEGACY_WS_KEY, "organization_id": org_id}) if org_id else None)
    if ws:
        ws_id = ws["_id"]
        log("Default workspace exists", ws_id=str(ws_id))
    elif apply and org_id:
        now = utcnow()
        res = await db.workspaces.insert_one({
            "organization_id": org_id, "name": LEGACY_WS_NAME, "key": LEGACY_WS_KEY,
            "created_by": owner_id, "status": "active", "created_at": now, "updated_at": now,
        })
        ws_id = res.inserted_id
        log("Created default workspace", ws_id=str(ws_id))
    else:
        ws_id = None
        log("WOULD create default workspace", key=LEGACY_WS_KEY)

    # 3) Backfill memberships
    users = await db.users.find({"is_deleted": {"$ne": True}}).to_list(length=10000)
    org_added = ws_added = 0
    for u in users:
        legacy = await _legacy_role_key(db, u)
        org_role = org_role_from_legacy(legacy)
        ws_role = workspace_role_from_legacy(legacy)
        if apply and org_id:
            exists = await db.organization_members.find_one({"organization_id": org_id, "user_id": u["_id"]})
            if not exists:
                await db.organization_members.insert_one({
                    "organization_id": org_id, "user_id": u["_id"], "org_role": org_role,
                    "status": "active", "joined_at": utcnow(),
                })
                org_added += 1
            wexists = await db.workspace_members.find_one({"workspace_id": ws_id, "user_id": u["_id"]})
            if not wexists:
                await db.workspace_members.insert_one({
                    "organization_id": org_id, "workspace_id": ws_id, "user_id": u["_id"],
                    "workspace_role": ws_role, "added_by": owner_id, "added_at": utcnow(), "removed_at": None,
                })
                ws_added += 1
        else:
            org_added += 1
            ws_added += 1
    log(("Added" if apply else "WOULD add") + " org memberships", count=org_added)
    log(("Added" if apply else "WOULD add") + " workspace memberships", count=ws_added)

    # 4) Stamp tenant keys on existing records
    for col in WS_SCOPED + ORG_ONLY:
        missing = await db[col].count_documents({"organization_id": {"$exists": False}})
        if apply and org_id and missing:
            set_fields = {"organization_id": org_id}
            if col in WS_SCOPED:
                set_fields["workspace_id"] = ws_id
            await db[col].update_many({"organization_id": {"$exists": False}}, {"$set": set_fields})
        log(("Stamped" if apply else "WOULD stamp") + f" {col}", docs=missing)

    # 5) Move global settings into org
    if apply and org_id:
        s = await db.settings.find_one({"key": "org"})
        if s:
            await db.organizations.update_one({"_id": org_id}, {"$set": {"settings": {
                "timezone": s.get("timezone", "UTC"),
                "org_name": s.get("org_name", LEGACY_ORG_NAME),
                "work_week_hours": s.get("work_week_hours", 40),
                "allow_invites": True,
            }}})
            log("Migrated org settings")

    # 6) Verify (apply only)
    if apply:
        leaks = {c: await db[c].count_documents({"organization_id": {"$exists": False}})
                 for c in WS_SCOPED + ORG_ONLY}
        report["verification"] = leaks
        bad = {c: n for c, n in leaks.items() if n}
        log("Verification — docs still missing organization_id", **(bad or {"all": "clean"}))

    return report


async def _rollback(db, log, report) -> dict:
    org = await db.organizations.find_one({"slug": LEGACY_ORG_SLUG})
    org_id = org["_id"] if org else None
    for col in WS_SCOPED:
        await db[col].update_many({}, {"$unset": {"organization_id": "", "workspace_id": ""}})
    for col in ORG_ONLY:
        await db[col].update_many({}, {"$unset": {"organization_id": ""}})
    await db.organization_members.delete_many({})
    await db.workspace_members.delete_many({})
    if org_id:
        await db.workspaces.delete_many({"organization_id": org_id})
    await db.organizations.delete_many({"slug": LEGACY_ORG_SLUG})
    log("Rolled back tenant fields, memberships, workspaces, legacy org")
    return report


async def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    client = AsyncIOMotorClient(settings.MONGODB_URI, tz_aware=True)
    db = client[settings.MONGODB_DB_NAME]
    mode = "ROLLBACK" if args.rollback else ("APPLY" if args.apply else "DRY-RUN")
    print(f"\n=== Migration 0001 multitenant [{mode}] on db={settings.MONGODB_DB_NAME} ===")
    report = await run(db, apply=args.apply, rollback=args.rollback)
    print("=== done ===\n")
    client.close()
    return report


if __name__ == "__main__":
    asyncio.run(_main())
