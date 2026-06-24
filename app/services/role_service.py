"""Role-related business logic, including permission aggregation."""
from typing import Any

from app.repositories.role_repository import RoleRepository


class RoleService:
    def __init__(self, roles: RoleRepository):
        self.roles = roles

    async def list_roles(self) -> list[dict[str, Any]]:
        return await self.roles.list_all()

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
