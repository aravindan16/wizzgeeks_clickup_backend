"""Authentication business logic: login, refresh (rotation + reuse detection),
logout, forgot/reset/change password."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    JWTError,
)
from app.repositories.reset_repository import PasswordResetRepository
from app.repositories.token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import send_email
from app.services.role_service import RoleService
from app.utils.datetime import utcnow

ACCESS_TTL_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _public_user(user: dict[str, Any], roles: list[str], perms: set[str]) -> dict[str, Any]:
    return {
        "_id": str(user["_id"]),
        "email": user["email"],
        "full_name": user["full_name"],
        "roles": roles,
        "permissions": sorted(perms),
        "status": user["status"],
        "designation": user.get("designation"),
        "department": user.get("department"),
        "avatar_url": user.get("avatar_url"),
    }


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        roles: RoleService,
        tokens: RefreshTokenRepository,
        resets: PasswordResetRepository,
    ):
        self.users = users
        self.roles = roles
        self.tokens = tokens
        self.resets = resets

    # --- token helpers ---
    async def _issue_refresh(self, user_id: str) -> str:
        jti = uuid.uuid4().hex
        token = create_refresh_token(subject=user_id, extra={"jti": jti})
        payload = decode_token(token)
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        await self.tokens.store(jti=jti, user_id=user_id, expires_at=expires_at, created_at=utcnow())
        return token

    def _issue_access(self, user: dict[str, Any], roles: list[str], perms: set[str]) -> str:
        return create_access_token(
            subject=str(user["_id"]),
            extra={"roles": roles, "permissions": sorted(perms), "email": user["email"]},
        )

    # --- login ---
    async def login(self, email: str, password: str) -> tuple[dict[str, Any], str, str]:
        user = await self.users.find_by_email(email, include_secret=True)
        if not user or not verify_password(password, user.get("password_hash", "")):
            raise AuthenticationError("Invalid email or password")
        if user.get("status") != "active" or user.get("is_deleted"):
            raise AuthenticationError("Account is not active")
        # Optional gate: only blocks explicitly-unverified accounts (legacy users without
        # the field are treated as verified so existing logins keep working).
        if settings.REQUIRE_EMAIL_VERIFICATION and user.get("email_verified") is False:
            raise AuthenticationError("Please verify your email before signing in")

        roles, perms = await self.roles.aggregate_for_user(user.get("role_ids", []))
        access = self._issue_access(user, roles, perms)
        refresh = await self._issue_refresh(str(user["_id"]))
        await self.users.update_by_id(user["_id"], {"last_login_at": utcnow()})
        return _public_user(user, roles, perms), access, refresh

    # --- refresh (rotation + reuse detection) ---
    async def refresh(self, refresh_token: str | None) -> tuple[str, str]:
        if not refresh_token:
            raise AuthenticationError("Missing refresh token")
        try:
            payload = decode_token(refresh_token)
        except JWTError:
            raise AuthenticationError("Invalid refresh token")
        if payload.get("type") != "refresh":
            raise AuthenticationError("Invalid token type")

        jti = payload.get("jti")
        user_id = payload.get("sub")
        record = await self.tokens.get(jti) if jti else None

        # Reuse detection: a validly-signed token whose jti is already revoked/absent
        # means the token family is compromised → revoke everything for that user.
        if record is None or record.get("revoked"):
            if user_id:
                await self.tokens.revoke_all_for_user(user_id)
            raise AuthenticationError("Refresh token reuse detected")

        # Rotate: revoke the presented jti, mint a fresh pair.
        await self.tokens.revoke(jti)
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("status") != "active" or user.get("is_deleted"):
            raise AuthenticationError("Account is not active")

        roles, perms = await self.roles.aggregate_for_user(user.get("role_ids", []))
        access = self._issue_access(user, roles, perms)
        new_refresh = await self._issue_refresh(user_id)
        return access, new_refresh

    # --- logout ---
    async def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            payload = decode_token(refresh_token)
            if payload.get("jti"):
                await self.tokens.revoke(payload["jti"])
        except JWTError:
            return

    # --- forgot / reset / change ---
    async def forgot_password(self, email: str) -> str | None:
        user = await self.users.find_by_email(email)
        if not user:
            return None  # do not reveal account existence
        raw = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES)
        await self.resets.create(
            token_hash=_hash_token(raw),
            user_id=str(user["_id"]),
            expires_at=expires_at,
            created_at=utcnow(),
        )
        # Email the reset link (when SMTP is configured).
        link = f"{settings.FRONTEND_URL}/reset-password?token={raw}"
        mins = settings.RESET_TOKEN_EXPIRE_MINUTES
        await send_email(
            email,
            "Reset your Wizzgeeks password",
            f"Hi {user.get('full_name', '')},\n\nReset your password using this link "
            f"(valid for {mins} minutes):\n{link}\n\nIf you didn't request this, ignore this email.",
            f"<p>Hi {user.get('full_name', '')},</p>"
            f"<p>Reset your password using the link below (valid for {mins} minutes):</p>"
            f"<p><a href=\"{link}\">Reset your password</a></p>"
            f"<p>If you didn't request this, you can ignore this email.</p>",
        )
        return raw

    async def reset_password(self, token: str, new_password: str) -> None:
        record = await self.resets.find_valid(_hash_token(token), utcnow())
        if not record:
            raise AuthenticationError("Invalid or expired reset token")
        await self.users.set_password(record["user_id"], hash_password(new_password), utcnow())
        await self.resets.mark_used(record["token_hash"])
        await self.tokens.revoke_all_for_user(record["user_id"])

    async def change_password(self, user_id: str, current: str, new: str) -> None:
        user = await self.users.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise NotFoundError("User not found")
        if not verify_password(current, user.get("password_hash", "")):
            raise AuthenticationError("Current password is incorrect")
        await self.users.set_password(user_id, hash_password(new), utcnow())
        await self.tokens.revoke_all_for_user(user_id)

    # --- registration / email verification ---
    async def register(self, email: str, password: str, full_name: str) -> tuple[str, str | None]:
        if not settings.ALLOW_SELF_REGISTRATION:
            raise PermissionDeniedError("Self-registration is disabled")
        email = email.lower()
        if await self.users.find_by_email(email):
            raise ConflictError("A user with this email already exists")

        role_ids = await self.roles.resolve_role_ids(["employee"])
        raw_token = secrets.token_urlsafe(32)
        now = utcnow()
        doc = {
            "email": email, "password_hash": hash_password(password), "full_name": full_name,
            "role_ids": role_ids, "manager_id": None, "designation": None, "department": None,
            "timezone": "UTC", "avatar_url": None, "status": "active",
            "email_verified": False, "verification_token_hash": _hash_token(raw_token),
            "notification_prefs": {"in_app": True, "email": False},
            "is_deleted": False, "deleted_at": None, "last_login_at": None,
            "password_changed_at": now, "created_at": now, "updated_at": now,
        }
        created = await self.users.insert_one(doc)
        token = raw_token if not settings.EMAIL_ENABLED else None
        return str(created["_id"]), token

    async def verify_email(self, token: str) -> None:
        user = await self.users.find_one({"verification_token_hash": _hash_token(token)})
        if not user:
            raise AuthenticationError("Invalid or expired verification token")
        await self.users.collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"email_verified": True, "updated_at": utcnow()},
             "$unset": {"verification_token_hash": ""}},
        )

    async def google_sign_in(self, id_token: str) -> tuple[dict, str, str]:
        """Verify a Google ID token and sign the user in, creating their account on
        first sign-in (Google sign-up). Issues our own access + refresh tokens."""
        if not settings.GOOGLE_CLIENT_ID:
            raise PermissionDeniedError(
                "Google Sign-In is not configured. Set GOOGLE_CLIENT_ID in the backend."
            )
        try:
            from google.auth.transport import requests as g_requests
            from google.oauth2 import id_token as g_id_token
        except ImportError:  # pragma: no cover
            raise PermissionDeniedError("google-auth is not installed on the server")

        try:
            info = g_id_token.verify_oauth2_token(
                id_token, g_requests.Request(), settings.GOOGLE_CLIENT_ID, clock_skew_in_seconds=10
            )
        except Exception:  # noqa: BLE001
            raise AuthenticationError("Invalid Google token")

        email = (info.get("email") or "").lower()
        if not email or not info.get("email_verified"):
            raise AuthenticationError("Google account has no verified email")
        full_name = info.get("name") or email.split("@")[0]
        avatar = info.get("picture")

        user = await self.users.find_by_email(email, include_secret=True)
        if not user:
            # First Google sign-in → create the account (sign-up).
            role_ids = await self.roles.resolve_role_ids(["employee"])
            now = utcnow()
            created = await self.users.insert_one({
                "email": email,
                # Random password hash — Google users sign in via Google (or use reset).
                "password_hash": hash_password(secrets.token_urlsafe(24)),
                "full_name": full_name, "role_ids": role_ids, "manager_id": None,
                "designation": None, "department": None, "timezone": "UTC",
                "avatar_url": avatar, "status": "active",
                "email_verified": True, "auth_provider": "google",
                "notification_prefs": {"in_app": True, "email": False},
                "is_deleted": False, "deleted_at": None, "last_login_at": now,
                "password_changed_at": now, "created_at": now, "updated_at": now,
            })
            user = created

        if user.get("status") != "active" or user.get("is_deleted"):
            raise AuthenticationError("Account is not active")

        roles, perms = await self.roles.aggregate_for_user(user.get("role_ids", []))
        access = self._issue_access(user, roles, perms)
        refresh = await self._issue_refresh(str(user["_id"]))
        await self.users.update_by_id(user["_id"], {"last_login_at": utcnow()})
        return _public_user(user, roles, perms), access, refresh
