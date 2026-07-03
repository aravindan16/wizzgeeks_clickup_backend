"""Saved-filter (Filters page) request/response DTOs.

A saved filter persists the ClickUp-style filter builder: `cards` (the AND/OR
rule tree) plus `conj` (the join between cards). Owned by a user and optionally
shared with members (owner ∪ members can view/use it).
"""
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SavedFilterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cards: list[dict[str, Any]] = []
    conj: str = "AND"


class SavedFilterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    cards: list[dict[str, Any]] | None = None
    conj: str | None = None


class SavedFilterResponse(ORMModel):
    id: str
    name: str
    cards: list[dict[str, Any]] = []
    conj: str = "AND"
    owner_id: str | None = None
    owner_name: str | None = None
    member_ids: list[str] = []
    created_at: Any | None = None
    updated_at: Any | None = None


class SavedFilterList(ORMModel):
    items: list[SavedFilterResponse]


class FilterMemberAdd(BaseModel):
    user_id: str


class FilterMember(ORMModel):
    user_id: str
    full_name: str | None = None
    email: str | None = None
    is_owner: bool = False


class FilterMemberList(ORMModel):
    items: list[FilterMember]
