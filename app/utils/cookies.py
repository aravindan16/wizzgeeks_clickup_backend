"""Helpers for the httpOnly refresh-token cookie."""
from fastapi import Response

from app.core.config import settings

# Cookie path "/" so the browser sends it regardless of the frontend's API-base
# prefix (e.g. /api/v1 locally vs /api/api/v1 behind a deployed reverse proxy).
# Scoping it to /api/v1/auth broke refresh in production when the path differed.
REFRESH_PATH = "/"


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path=REFRESH_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=REFRESH_PATH,
        httponly=True,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )
