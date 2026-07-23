"""Organization settings + system status (admin)."""
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import CurrentUser, CurrentUserDep, DbDep, require
from app.core.config import settings as app_settings
from app.repositories.settings_repository import SettingsRepository
from app.schemas.common import ORMModel
from app.utils.datetime import utcnow

router = APIRouter()


class IconColors(BaseModel):
    colors: list[str]

DEFAULT_ORG = {
    "org_name": "Wizzgeeks",
    "timezone": "UTC",
    "work_week_hours": 40,
    "daily_update_cutoff": "23:59",
}


class OrgSettings(ORMModel):
    org_name: str = "Wizzgeeks"
    timezone: str = "UTC"
    work_week_hours: int = 40
    daily_update_cutoff: str = "23:59"


class OrgSettingsUpdate(ORMModel):
    org_name: str | None = None
    timezone: str | None = None
    work_week_hours: int | None = None
    daily_update_cutoff: str | None = None


@router.get("/settings", response_model=OrgSettings)
async def get_settings(
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require("admin.settings"))],
):
    repo = SettingsRepository(db)
    org = await repo.get_org()
    return OrgSettings(**{**DEFAULT_ORG, **(org or {})})


@router.patch("/settings", response_model=OrgSettings)
async def update_settings(
    payload: OrgSettingsUpdate,
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require("admin.settings"))],
):
    repo = SettingsRepository(db)
    values = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    saved = await repo.upsert_org(values, utcnow())
    return OrgSettings(**{**DEFAULT_ORG, **(saved or {})})


# --- icon-colour palette (DB-driven) ---
# Readable by any authenticated user — the icon picker is used everywhere.
@router.get("/icon-colors")
async def get_icon_colors(db: DbDep, _: CurrentUserDep) -> dict[str, Any]:
    repo = SettingsRepository(db)
    return {"colors": await repo.get_icon_colors()}


# Editing the palette is an admin action.
@router.put("/icon-colors")
async def update_icon_colors(
    payload: IconColors,
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require("admin.settings"))],
) -> dict[str, Any]:
    repo = SettingsRepository(db)
    return {"colors": await repo.set_icon_colors(payload.colors, utcnow())}


@router.get("/status")
async def system_status(
    db: DbDep,
    _: Annotated[CurrentUser, Depends(require("dashboard.view.admin"))],
) -> dict[str, Any]:
    """System status dashboard data: version, DB health, and collection counts."""
    db_ok = True
    try:
        await db.command("ping")
    except Exception:  # noqa: BLE001
        db_ok = False

    counts = {}
    for col in ["users", "projects", "tasks", "notifications", "activity_logs"]:
        counts[col] = await db[col].count_documents({})

    return {
        "version": app_settings.APP_VERSION,
        "environment": app_settings.ENVIRONMENT,
        "database": {"connected": db_ok},
        "collections": counts,
        "features": {
            "self_registration": app_settings.ALLOW_SELF_REGISTRATION,
            "email_verification_required": app_settings.REQUIRE_EMAIL_VERIFICATION,
            "email_enabled": app_settings.EMAIL_ENABLED,
            "google_sign_in": bool(app_settings.GOOGLE_CLIENT_ID),
        },
    }
