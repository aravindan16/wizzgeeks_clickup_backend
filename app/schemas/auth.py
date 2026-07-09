"""Auth request/response DTOs."""
from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserPublic(ORMModel):
    id: str = Field(alias="_id")
    email: EmailStr
    full_name: str
    roles: list[str] = []
    permissions: list[str] = []
    status: str
    avatar_url: str | None = None
    avatar_color: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)


class RegisterResponse(BaseModel):
    message: str
    user_id: str
    # Returned only when email sending is disabled (dev) so verification can be tested.
    verification_token: str | None = None


class VerifyEmailRequest(BaseModel):
    token: str


class GoogleSignInRequest(BaseModel):
    id_token: str
