"""Role-related business logic, including permission aggregation."""
import re
from typing import Any

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.permissions import PERMISSIONS, WILDCARD
from app.repositories.base import is_valid_object_id
from app.repositories.role_repository import RoleRepository
from app.utils.datetime import utcnow


class RoleService:
    def __init__(self, roles: RoleRepository):
        self.roles = roles

    async def list_roles(self) -> list[dict[str, Any]]:
        return await self.roles.list_all()

    # --- role CRUD (role.create / role.update / role.delete) ---
    @staticmethod
    def _valid_perms(perms: list[str]) -> list[str]:
        known = set(PERMISSIONS) | {WILDCARD}
        cleaned = list(dict.fromkeys(perms or []))
        unknown = [p for p in cleaned if p not in known]
        if unknown:
            raise ValidationError(f"Unknown permission(s): {', '.join(unknown)}")
        return cleaned

    async def _get_or_404(self, role_id: str) -> dict[str, Any]:
        if not is_valid_object_id(role_id):
            raise NotFoundError("Role not found")
        role = await self.roles.find_by_id(role_id)
        if not role:
            raise NotFoundError("Role not found")
        return role

    async def create_role(self, data: dict[str, Any]) -> dict[str, Any]:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("Role name is required")
        key = data.get("key") or re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if await self.roles.find_by_key(key):
            raise ConflictError("A role with this key already exists")
        doc = {
            "key": key, "name": name, "level": int(data.get("level") or 10),
            "permissions": self._valid_perms(data.get("permissions") or []),
            "is_system": False, "created_at": utcnow(), "updated_at": utcnow(),
        }
        return await self.roles.insert_one(doc)

    async def update_role(self, role_id: str, data: dict[str, Any]) -> dict[str, Any]:
        role = await self._get_or_404(role_id)
        update: dict[str, Any] = {"updated_at": utcnow()}
        if data.get("name"):
            update["name"] = data["name"].strip()
        if data.get("permissions") is not None:
            if role.get("key") == "super_admin":
                raise PermissionDeniedError("The Super Admin role cannot be modified.")
            update["permissions"] = self._valid_perms(data["permissions"])
        if data.get("level") is not None:
            update["level"] = int(data["level"])
        return await self.roles.update_by_id(role_id, update)

    async def delete_role(self, role_id: str) -> None:
        role = await self._get_or_404(role_id)
        if role.get("is_system"):
            raise PermissionDeniedError("System roles cannot be deleted.")
        await self.roles.delete_by_id(role_id)

    async def resolve_role_ids(self, role_keys: list[str]) -> list[Any]:
        """Map role keys (e.g. ['employee']) to their ObjectIds, validating existence."""
        found = await self.roles.find_by_keys(role_keys)
        found_keys = {r["key"] for r in found}
        missing = set(role_keys) - found_keys
        if missing:
            raise ValueError(f"Unknown role(s): {', '.join(sorted(missing))}")
        return [r["_id"] for r in found]

    async def aggregate_for_user(self, role_ids: list[Any]) -> tuple[list[str], set[str]]:
        """Return (role_keys, permission_set) for a user's role ids."""
        roles = await self.roles.find_by_ids(role_ids)
        keys = [r["key"] for r in roles]
        perms: set[str] = set()
        for r in roles:
            perms.update(r.get("permissions", []))
        return keys, perms
