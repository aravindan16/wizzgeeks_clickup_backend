"""Schemas for the global Labels catalog."""
from datetime import datetime

from pydantic import BaseModel, Field


class LabelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str | None = None


class LabelResponse(BaseModel):
    id: str
    name: str
    color: str
    created_at: datetime | None = None


class LabelList(BaseModel):
    items: list[LabelResponse]
