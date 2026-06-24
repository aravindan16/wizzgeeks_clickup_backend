"""Tenant-scoped repository base — defense-in-depth so tenant filters can't be
forgotten. Every read/write is automatically constrained to the active
organization (and workspace, when the collection is workspace-scoped), and every
insert is stamped with the tenant keys.

Concrete tenant repositories subclass this and set `collection_name` +
`workspace_scoped`. They receive a TenantContext at construction.
"""
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.tenant import TenantContext
from app.repositories.base import BaseRepository, to_object_id


class TenantScopedRepository(BaseRepository):
    #: set True if the collection carries workspace_id (most tenant data does)
    workspace_scoped: bool = True

    def __init__(self, db: AsyncIOMotorDatabase, tenant: TenantContext):
        super().__init__(db)
        self.tenant = tenant
        self._org_id = to_object_id(tenant.organization_id)
        self._ws_id = to_object_id(tenant.workspace_id) if tenant.workspace_id else None

    # --- filter helpers ---
    def _scope(self, query: dict[str, Any] | None = None) -> dict[str, Any]:
        scoped: dict[str, Any] = dict(query or {})
        scoped["organization_id"] = self._org_id
        if self.workspace_scoped and self._ws_id is not None:
            scoped["workspace_id"] = self._ws_id
        return scoped

    def _stamp(self, document: dict[str, Any]) -> dict[str, Any]:
        document["organization_id"] = self._org_id
        if self.workspace_scoped and self._ws_id is not None:
            document["workspace_id"] = self._ws_id
        return document

    # --- scoped CRUD (override BaseRepository to force tenant filtering) ---
    async def insert_one(self, document: dict[str, Any]) -> dict[str, Any]:
        return await super().insert_one(self._stamp(document))

    async def find_by_id(self, doc_id: str | ObjectId) -> dict[str, Any] | None:
        # Tenant-safe: a doc from another org/workspace is invisible even by _id.
        try:
            oid = to_object_id(doc_id)
        except Exception:  # noqa: BLE001
            return None
        return await self.collection.find_one(self._scope({"_id": oid}))

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return await self.collection.find_one(self._scope(query))

    async def find_many(
        self, query: dict[str, Any] | None = None, *, skip: int = 0, limit: int = 50,
        sort: list[tuple[str, int]] | None = None, projection: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self.collection.find(self._scope(query), projection)
        if sort:
            cursor = cursor.sort(sort)
        return await cursor.skip(skip).limit(limit).to_list(length=limit)

    async def count(self, query: dict[str, Any] | None = None) -> int:
        return await self.collection.count_documents(self._scope(query))

    async def update_by_id(self, doc_id: str | ObjectId, update: dict[str, Any]) -> dict[str, Any] | None:
        return await self.collection.find_one_and_update(
            self._scope({"_id": to_object_id(doc_id)}), {"$set": update}, return_document=True
        )

    async def delete_by_id(self, doc_id: str | ObjectId) -> bool:
        result = await self.collection.delete_one(self._scope({"_id": to_object_id(doc_id)}))
        return result.deleted_count == 1

    async def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Prepend a mandatory tenant $match so aggregations cannot leak across tenants."""
        scoped_pipeline = [{"$match": self._scope()}, *pipeline]
        cursor = self.collection.aggregate(scoped_pipeline)
        return await cursor.to_list(length=None)
