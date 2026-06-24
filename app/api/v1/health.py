"""Health and readiness endpoints."""
from fastapi import APIRouter

from app.core.config import settings
from app.core.database import mongo

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENVIRONMENT}


@router.get("/health/ready")
async def readiness() -> dict:
    """Readiness probe — verifies the DB connection responds."""
    db_ok = False
    try:
        if mongo.client is not None:
            await mongo.client.admin.command("ping")
            db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ready" if db_ok else "degraded", "database": db_ok}


@router.get("/version")
async def version() -> dict:
    """Build/version metadata."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "api_prefix": settings.API_V1_PREFIX,
    }
