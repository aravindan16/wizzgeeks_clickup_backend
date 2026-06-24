"""User management business logic."""
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.role_service import RoleService
from app.utils.datetime import utcnow


@dataclass
class ActorContext:
    """Who performed an action, for audit logging and access checks."""

    user_id: str | None = None
    ip: str | None = None
    permissions: set[str] = field(default_factory=set)
    roles: list[str] = field(default_factory=list)

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions


def _serialize(user: dict[str, Any], role_keys: list[str] | None = None) -> dict[str, Any]:
    """Shape a Mongo user doc for API output."""
    out = dict(user)
    out["_id"] = str(user["_id"])
    if user.get("manager_id"):
        out["manager_id"] = str(user["manager_id"])
    if role_keys is not None:
        out["roles"] = role_keys
    return out


class UserService:
    def __init__(self, users: UserRepository, roles: RoleService, audit: AuditService,
                 notifications: "NotificationService | None" = None):
        self.users = users
        self.roles = roles
        self.audit = audit
        self.notifications = notifications

    async def _role_keys_for(self, role_ids: list[Any]) -> list[str]:
        keys, _ = await self.roles.aggregate_for_user(role_ids)
        return keys

    async def create_user(
        self, data: dict[str, Any], actor: ActorContext | None = None
    ) -> dict[str, Any]:
        email = data["email"].lower()
        if await self.users.find_by_email(email):
            raise ConflictError("A user with this email already exists")

        try:
            role_ids = await self.roles.resolve_role_ids(data.get("role_keys") or ["employee"])
        except ValueError as e:
            raise ValidationError(str(e))

        manager_id = data.get("manager_id")
        if manager_id:
            if not is_valid_object_id(manager_id) or not await self.users.find_by_id(manager_id):
                raise ValidationError("manager_id does not reference an existing user")

        now = utcnow()
        doc = {
            "email": email,
            "password_hash": hash_password(data["password"]),
            "full_name": data["full_name"],
            "role_ids": role_ids,
            "manager_id": to_object_id(manager_id) if manager_id else None,
            "designation": data.get("designation"),
            "department": data.get("department"),
            "timezone": data.get("timezone") or "UTC",
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
        created = await self.users.insert_one(doc)
        created.pop("password_hash", None)
        result = _serialize(created, await self._role_keys_for(role_ids))
        if actor:
            await self.audit.log(
                actor_id=actor.user_id,
                action="user.created",
                entity_type="user",
                entity_id=result["_id"],
                metadata={"email": email, "roles": data.get("role_keys")},
                ip=actor.ip,
            )
        return result

    async def get_user(self, user_id: str) -> dict[str, Any]:
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        return _serialize(user, await self._role_keys_for(user.get("role_ids", [])))

    async def list_users(self, *, skip: int, limit: int, status: str | None,
                         department: str | None, search: str | None) -> tuple[list[dict], int]:
        query: dict[str, Any] = {"is_deleted": {"$ne": True}}
        if status:
            query["status"] = status
        if department:
            query["department"] = department
        if search:
            query["$or"] = [
                {"full_name": {"$regex": search, "$options": "i"}},
                {"email": {"$regex": search, "$options": "i"}},
            ]
        items = await self.users.list_users(query, skip=skip, limit=limit)
        total = await self.users.count(query)
        out = []
        for u in items:
            out.append(_serialize(u, await self._role_keys_for(u.get("role_ids", []))))
        return out, total

    async def update_user(
        self, user_id: str, data: dict[str, Any], actor: ActorContext | None = None
    ) -> dict[str, Any]:
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")

        update: dict[str, Any] = {"updated_at": utcnow()}
        changed_fields: list[str] = []
        for field in ("full_name", "designation", "department", "timezone", "avatar_url"):
            if data.get(field) is not None:
                update[field] = data[field]
                changed_fields.append(field)

        role_change: dict[str, Any] | None = None
        if data.get("role_keys") is not None:
            try:
                update["role_ids"] = await self.roles.resolve_role_ids(data["role_keys"])
            except ValueError as e:
                raise ValidationError(str(e))
            before = await self._role_keys_for(user.get("role_ids", []))
            role_change = {"from": before, "to": data["role_keys"]}
            changed_fields.append("roles")

        if data.get("manager_id") is not None:
            mid = data["manager_id"]
            if mid and (not is_valid_object_id(mid) or not await self.users.find_by_id(mid)):
                raise ValidationError("manager_id does not reference an existing user")
            update["manager_id"] = to_object_id(mid) if mid else None
            changed_fields.append("manager_id")

        updated = await self.users.update_by_id(user_id, update)
        updated.pop("password_hash", None)
        result = _serialize(updated, await self._role_keys_for(updated.get("role_ids", [])))

        if actor:
            meta: dict[str, Any] = {"fields": changed_fields}
            if role_change:
                meta["role_change"] = role_change
            await self.audit.log(
                actor_id=actor.user_id,
                action="user.role_changed" if role_change else "user.updated",
                entity_type="user",
                entity_id=user_id,
                metadata=meta,
                ip=actor.ip,
            )
            # Notify the user their access/roles changed (skip self-edits).
            if role_change and self.notifications and user_id != actor.user_id:
                roles_text = ", ".join(role_change["to"]) or "no roles"
                await self.notifications.notify(
                    recipient_id=user_id, type="user.role_changed",
                    title="Your access was updated",
                    body=f"Your role is now: {roles_text}.",
                    entity_type="user", entity_id=user_id,
                )
        return result

    async def set_status(
        self, user_id: str, status: str, actor: ActorContext | None = None
    ) -> dict[str, Any]:
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        updated = await self.users.update_by_id(user_id, {"status": status, "updated_at": utcnow()})
        updated.pop("password_hash", None)
        if actor:
            await self.audit.log(
                actor_id=actor.user_id,
                action="user.activated" if status == "active" else "user.disabled",
                entity_type="user",
                entity_id=user_id,
                metadata={"status": status},
                ip=actor.ip,
            )
        return _serialize(updated, await self._role_keys_for(updated.get("role_ids", [])))

    async def set_preferences(self, user_id: str, prefs: dict[str, Any]) -> dict[str, Any]:
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        merged = {**(user.get("notification_prefs") or {}), **prefs}
        updated = await self.users.update_by_id(
            user_id, {"notification_prefs": merged, "updated_at": utcnow()})
        updated.pop("password_hash", None)
        return _serialize(updated, await self._role_keys_for(updated.get("role_ids", [])))

    async def set_avatar(self, user_id: str, avatar_url: str) -> dict[str, Any]:
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        updated = await self.users.update_by_id(
            user_id, {"avatar_url": avatar_url, "updated_at": utcnow()})
        updated.pop("password_hash", None)
        return _serialize(updated, await self._role_keys_for(updated.get("role_ids", [])))

    async def soft_delete(self, user_id: str, actor: ActorContext | None = None) -> None:
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        await self.users.soft_delete_by_id(user_id, when=utcnow())
        if actor:
            await self.audit.log(
                actor_id=actor.user_id,
                action="user.deleted",
                entity_type="user",
                entity_id=user_id,
                metadata={"email": user.get("email")},
                ip=actor.ip,
            )
