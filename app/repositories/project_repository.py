"""Data access for the `projects` collection."""
from typing import Any

from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository):
    collection_name = "projects"

    async def find_by_key(self, key: str) -> dict[str, Any] | None:
        return await self.find_one({"key": key.upper()})

    async def list_projects(
        self, query: dict[str, Any], *, skip: int, limit: int
    ) -> list[dict[str, Any]]:
        return await self.find_many(
            query, skip=skip, limit=limit, sort=[("created_at", -1)]
        )

    async def next_task_seq(self, project_id: Any) -> int:
        """Atomically increment and return the project's task counter (for task keys)."""
        from app.repositories.base import to_object_id

        doc = await self.collection.find_one_and_update(
            {"_id": to_object_id(project_id)},
            {"$inc": {"task_counter": 1}},
            return_document=True,
        )
        return int(doc["task_counter"]) if doc else 0
