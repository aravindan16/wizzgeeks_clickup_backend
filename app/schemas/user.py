"""User request/response DTOs."""
from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    role_keys: list[str] = Field(default_factory=lambda: ["employee"])
    manager_id: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    role_keys: list[str] | None = None
    manager_id: str | None = None
    avatar_url: str | None = None
    avatar_color: str | None = Field(default=None, max_length=9)


class AdminPasswordReset(BaseModel):
    """Admin sets a new password for a user who forgot theirs."""

    new_password: str = Field(min_length=8, max_length=128)


class UserResponse(ORMModel):
    id: str = Field(alias="_id")
    email: EmailStr
    full_name: str
    roles: list[str] = []
    status: str
    manager_id: str | None = None
    avatar_url: str | None = None
    avatar_color: str | None = None
    created_at: object | None = None
    updated_at: object | None = None
