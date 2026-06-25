"""Custom field DTOs. Only three types are supported: dropdown, relationship, text."""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

FieldType = Literal["dropdown", "relationship", "text"]
FieldScope = Literal["space", "list"]


class DropdownOption(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    color: str = Field(default="#6b7280", max_length=9)
    default: bool = False


class FieldConfig(BaseModel):
    # dropdown
    options: list[DropdownOption] = Field(default_factory=list)
    multiple: bool = False            # allow selecting more than one option
    # text
    multiline: bool = False
    # relationship (Task ↔ Task / Task ↔ Subtask)
    target: str = "task"
    related_to: str = "workspace"     # 'workspace' (any task) | 'list' (tasks from a List)
    list_id: str | None = None        # when related_to == 'list'
    rollup: bool = False              # create rollup fields
    # shared
    fill_method: str = "manual"       # 'manual' | 'ai'


class CustomFieldCreate(BaseModel):
    scope: FieldScope
    space_id: str
    list_id: str | None = None  # required when scope == "list"
    name: str = Field(min_length=1, max_length=80)
    type: FieldType
    config: FieldConfig = Field(default_factory=FieldConfig)


class CustomFieldUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    config: FieldConfig | None = None


class MoveFieldRequest(BaseModel):
    scope: FieldScope
    list_id: str | None = None  # target list when scope == "list"


class DuplicateFieldRequest(BaseModel):
    scope: FieldScope
    space_id: str
    list_id: str | None = None


class ReorderFieldsRequest(BaseModel):
    ids: list[str]  # field ids in their new display order (within one scope)


class ListToggleRequest(BaseModel):
    list_id: str
    enabled: bool  # enable (show) or disable (hide) an inherited field for this List


class CustomFieldResponse(ORMModel):
    id: str = Field(alias="_id")
    scope: str
    space_id: str
    list_id: str | None = None
    name: str
    type: str
    config: dict[str, Any] = {}
    order: int = 0
    inherited: bool = False           # true when shown in a List but owned by the Space
    enabled: bool = True              # for inherited fields: is it active for this List?
    location: str | None = None       # human label: Space or List name
    created_by: str | None = None
    created_by_name: str | None = None
    created_at: Any | None = None
    updated_at: Any | None = None
