"""Shared schema utilities used across modules."""
from typing import Annotated, Any, Generic, TypeVar

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict

# Pydantic v2 representation of a Mongo ObjectId: validated/serialized as str.
PyObjectId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, ObjectId) else v)]

T = TypeVar("T")


class ORMModel(BaseModel):
    """Base for response models mapping from Mongo documents."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int


class MessageResponse(BaseModel):
    message: str
    details: dict[str, Any] | None = None
