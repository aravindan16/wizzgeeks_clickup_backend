"""Refresh-token store for rotation + revocation + reuse detection.

We store only the JWT `jti` (token id), never the token itself. A refresh is
valid only if its jti exists, is not revoked, and is not expired. On rotation
the old jti is revoked; presenting an already-revoked jti triggers a
family-wide revoke (reuse detection).
"""
from typing import Any

from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository):
    collection_name = "refresh_tokens"

    async def store(self, *, jti: str, user_id: str, expires_at: Any, created_at: Any) -> None:
        await self.insert_one(
            {
                "jti": jti,
                "user_id": user_id,
                "revoked": False,
                "expires_at": expires_at,
                "created_at": created_at,
            }
        )

    async def find_active(self, jti: str) -> dict[str, Any] | None:
        return await self.find_one({"jti": jti, "revoked": False})

    async def get(self, jti: str) -> dict[str, Any] | None:
        return await self.find_one({"jti": jti})

    async def revoke(self, jti: str) -> None:
        await self.collection.update_one({"jti": jti}, {"$set": {"revoked": True}})

    async def revoke_all_for_user(self, user_id: str) -> None:
        await self.collection.update_many(
            {"user_id": user_id, "revoked": False}, {"$set": {"revoked": True}}
        )
