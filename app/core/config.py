"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Side-effect import: relax email validation to permit the `.local` dev TLD.
# Must run before any EmailStr field is validated; config loads first.
from app.core import email_validation  # noqa: F401

# Absolute path to backend/.env so it loads no matter which directory uvicorn
# is started from (a relative ".env" silently fails when CWD differs).
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    APP_NAME: str = "Wizzgeeks API"
    APP_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # --- Multi-tenancy ---
    # When False (default during rollout), tenant context is resolved if present but
    # not required — the app keeps working single-tenant. Flip to True at cutover.
    ENFORCE_TENANCY: bool = False
    TENANT_HEADER_WORKSPACE: str = "X-Workspace-Id"
    TENANT_HEADER_ORG: str = "X-Organization-Id"

    # --- Feature flags ---
    ALLOW_SELF_REGISTRATION: bool = True
    REQUIRE_EMAIL_VERIFICATION: bool = False  # if True, unverified users cannot log in
    EMAIL_ENABLED: bool = False  # when False, verification/reset tokens are returned in the API (dev)
    GOOGLE_CLIENT_ID: str = ""  # set to enable Google Sign-In

    # --- SMTP (email delivery; used when EMAIL_ENABLED=true) ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""          # defaults to SMTP_USER if empty
    SMTP_TLS: bool = True        # STARTTLS on port 587
    FRONTEND_URL: str = "http://localhost:5173"  # base URL for reset/verify links
    MAX_AVATAR_BYTES: int = 2 * 1024 * 1024  # 2 MB

    # --- Database ---
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "daily_activity_tracker"

    # --- Security / JWT ---
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_COOKIE_NAME: str = "dat_refresh"
    REFRESH_COOKIE_SECURE: bool = False  # True in production (HTTPS)
    REFRESH_COOKIE_SAMESITE: str = "lax"

    # --- CORS ---
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # --- AWS S3 (attachments) ---
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET: str = "daily-activity-attachments"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_ENDPOINT_URL: str = ""  # set for MinIO local dev; empty for real AWS

    # --- Rate limiting ---
    RATE_LIMIT_DEFAULT: str = "200/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # --- Bootstrap seed (first Super Admin) ---
    # Seeded ONLY when ENVIRONMENT == "development" (see app/db/seed.py).
    FIRST_SUPERADMIN_EMAIL: str = "admin@dailyactivity.local"
    FIRST_SUPERADMIN_PASSWORD: str = "Admin@123"
    FIRST_SUPERADMIN_NAME: str = "Super Admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
