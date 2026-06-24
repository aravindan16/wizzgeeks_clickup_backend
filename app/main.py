"""FastAPI application entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import close_mongo_connection, connect_to_mongo, get_database
from app.core.exceptions import register_exception_handlers
from app.db.indexes import ensure_indexes
from app.db.seed import run_seed

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup
    await connect_to_mongo()
    await ensure_indexes()
    await run_seed(get_database())
    from app.services.email_service import email_configured
    if email_configured():
        logging.getLogger("app").info(
            "Email: ENABLED via %s (from=%s)", settings.SMTP_HOST,
            settings.SMTP_FROM or settings.SMTP_USER)
    else:
        logging.getLogger("app").warning(
            "Email: DISABLED (EMAIL_ENABLED=%s, SMTP_HOST=%r) — reset/verify links won't be emailed",
            settings.EMAIL_ENABLED, settings.SMTP_HOST)
    yield
    # Shutdown
    await close_mongo_connection()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    cors_kwargs = dict(
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,  # required for httpOnly refresh cookie
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # In development, accept any localhost/127.0.0.1 origin on any port so the
    # dev server works regardless of how it's opened (prevents CORS preflight 400s).
    if settings.ENVIRONMENT == "development":
        cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
    app.add_middleware(CORSMiddleware, **cors_kwargs)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/")
    async def root() -> dict:
        return {"app": settings.APP_NAME, "docs": "/docs", "api": settings.API_V1_PREFIX}

    return app


app = create_app()
