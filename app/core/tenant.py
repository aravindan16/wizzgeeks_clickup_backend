"""Tenant context — the resolved active organization/workspace for a request.

Produced by `get_tenant_context` (see app/api/deps.py) after verifying the current
user's membership. Carries the effective permission set for the active tenant.
"""
from dataclasses import dataclass, field


@dataclass
class TenantContext:
    organization_id: str
    workspace_id: str | None
    org_role: str | None = None
    workspace_role: str | None = None
    permissions: set[str] = field(default_factory=set)

    def has(self, permission: str) -> bool:
        return "*" in self.permissions or permission in self.permissions
