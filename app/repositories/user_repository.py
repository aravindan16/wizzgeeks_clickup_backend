"""Data access for the `users` collection."""
from typing import Any

from app.repositories.base import BaseRepository

# Never expose the password hash to upper layers by default.
SAFE_PROJECTION = {"password_hash": 0}


class UserRepository(BaseRepository):
    collection_name = "users"

    async def find_by_email(self, email: str, *, include_secret: bool = False) -> dict[str, Any] | None:
        projection = None if include_secret else SAFE_PROJECTION
        return await self.collection.find_one({"email": email.strip().lower()}, projection)

    async def find_safe_by_id(self, user_id: str) -> dict[str, Any] | None:
        from app.repositories.base import to_object_id, is_valid_object_id

        if not is_valid_object_id(str(user_id)):
            return None
        return await self.collection.find_one(
            {"_id": to_object_id(user_id)}, SAFE_PROJECTION
        )

    async def list_users(
        self, query: dict[str, Any], *, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            query, skip=skip, limit=limit, sort=[("created_at", -1)], projection=SAFE_PROJECTION
        )

    async def set_password(self, user_id: Any, password_hash: str, when: Any) -> None:
        from app.repositories.base import to_object_id

        await self.collection.update_one(
            {"_id": to_object_id(user_id)},
            {"$set": {"password_hash": password_hash, "password_changed_at": when, "updated_at": when}},
        )
