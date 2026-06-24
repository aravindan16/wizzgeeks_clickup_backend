"""Generic async repository over a MongoDB collection (Motor).

Concrete repositories subclass this and set `collection_name`. The repository
layer is the ONLY layer that talks to the database; services depend on
repositories, never on Motor directly.
"""
from typing import Any, Generic, TypeVar

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

T = TypeVar("T")


def to_object_id(value: str | ObjectId) -> ObjectId:
    """Coerce a string to ObjectId, raising InvalidId if malformed."""
    if isinstance(value, ObjectId):
        return value
    return ObjectId(value)


def is_valid_object_id(value: str) -> bool:
    try:
        ObjectId(value)
        return True
    except (InvalidId, TypeError):
        return False


class BaseRepository(Generic[T]):
    collection_name: str

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self.collection: AsyncIOMotorCollection = db[self.collection_name]

    # --- create ---
    async def insert_one(self, document: dict[str, Any]) -> dict[str, Any]:
        result = await self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    # --- read ---
    async def find_by_id(self, doc_id: str | ObjectId) -> dict[str, Any] | None:
        try:
            oid = to_object_id(doc_id)
        except (InvalidId, TypeError):
            return None
        return await self.collection.find_one({"_id": oid})

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return await self.collection.find_one(query)

    async def find_many(
        self,
        query: dict[str, Any] | None = None,
        *,
        skip: int = 0,
        limit: int = 50,
        sort: list[tuple[str, int]] | None = None,
        projection: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self.collection.find(query or {}, projection)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def count(self, query: dict[str, Any] | None = None) -> int:
        return await self.collection.count_documents(query or {})

    # --- update ---
    async def update_by_id(
        self, doc_id: str | ObjectId, update: dict[str, Any]
    ) -> dict[str, Any] | None:
        oid = to_object_id(doc_id)
        return await self.collection.find_one_and_update(
            {"_id": oid}, {"$set": update}, return_document=True
        )

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any]
    ) -> dict[str, Any] | None:
        return await self.collection.find_one_and_update(
            query, update, return_document=True
        )

    # --- delete ---
    async def delete_by_id(self, doc_id: str | ObjectId) -> bool:
        oid = to_object_id(doc_id)
        result = await self.collection.delete_one({"_id": oid})
        return result.deleted_count == 1

    async def soft_delete_by_id(self, doc_id: str | ObjectId, *, when: Any) -> bool:
        oid = to_object_id(doc_id)
        result = await self.collection.update_one(
            {"_id": oid},
            {"$set": {"is_deleted": True, "deleted_at": when}},
        )
        return result.modified_count == 1

    # --- aggregation passthrough ---
    async def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cursor = self.collection.aggregate(pipeline)
        return await cursor.to_list(length=None)
