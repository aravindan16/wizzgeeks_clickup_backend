"""Password-reset token store. Stores only a SHA-256 hash of the token."""
from typing import Any

from app.repositories.base import BaseRepository


class PasswordResetRepository(BaseRepository):
    collection_name = "password_resets"

    async def create(self, *, token_hash: str, user_id: str, expires_at: Any, created_at: Any) -> None:
        await self.insert_one(
            {
                "token_hash": token_hash,
                "user_id": user_id,
                "used": False,
                "expires_at": expires_at,
                "created_at": created_at,
            }
        )

    async def find_valid(self, token_hash: str, now: Any) -> dict[str, Any] | None:
        return await self.find_one(
            {"token_hash": token_hash, "used": False, "expires_at": {"$gt": now}}
        )

    async def mark_used(self, token_hash: str) -> None:
        await self.collection.update_one({"token_hash": token_hash}, {"$set": {"used": True}})
