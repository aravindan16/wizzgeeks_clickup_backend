"""Authentication endpoints."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import CurrentUserDep, get_auth_service
from app.core.config import settings
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleSignInRequest,
    LoginRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserPublic,
    VerifyEmailRequest,
)
from app.schemas.common import MessageResponse
from app.services.auth_service import ACCESS_TTL_SECONDS, AuthService
from app.utils.cookies import clear_refresh_cookie, set_refresh_cookie

router = APIRouter()

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, response: Response, service: AuthServiceDep):
    user, access, refresh = await service.login(payload.email, payload.password)
    set_refresh_cookie(response, refresh)
    return TokenResponse(access_token=access, expires_in=ACCESS_TTL_SECONDS, user=user)


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(payload: RegisterRequest, service: AuthServiceDep):
    user_id, token = await service.register(payload.email, payload.password, payload.full_name)
    return RegisterResponse(
        message="Registration successful. Please verify your email.",
        user_id=user_id, verification_token=token,
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(payload: VerifyEmailRequest, service: AuthServiceDep):
    await service.verify_email(payload.token)
    return MessageResponse(message="Email verified")


@router.post("/google", response_model=TokenResponse)
async def google_sign_in(payload: GoogleSignInRequest, response: Response, service: AuthServiceDep):
    user, access, refresh = await service.google_sign_in(payload.id_token)
    set_refresh_cookie(response, refresh)
    return TokenResponse(access_token=access, expires_in=ACCESS_TTL_SECONDS, user=user)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(request: Request, response: Response, service: AuthServiceDep):
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    access, new_refresh = await service.refresh(token)
    set_refresh_cookie(response, new_refresh)
    return RefreshResponse(access_token=access, expires_in=ACCESS_TTL_SECONDS)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response, service: AuthServiceDep):
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    await service.logout(token)
    clear_refresh_cookie(response)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=UserPublic)
async def me(current: CurrentUserDep):
    return UserPublic(
        _id=current.id,
        email=current.email,
        full_name=current.full_name,
        roles=current.roles,
        permissions=sorted(current.permissions),
        status=current.status,
        designation=current.raw.get("designation"),
        department=current.raw.get("department"),
        avatar_url=current.raw.get("avatar_url"),
    )


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(payload: ForgotPasswordRequest, service: AuthServiceDep):
    raw_token = await service.forgot_password(payload.email)
    # When email is enabled, the link is emailed and the token is NOT returned.
    # Otherwise (dev) the token is returned inline to ease testing.
    expose = raw_token if not settings.EMAIL_ENABLED else None
    return ForgotPasswordResponse(
        message="If the account exists, a reset link has been sent",
        reset_token=expose,
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(payload: ResetPasswordRequest, service: AuthServiceDep):
    await service.reset_password(payload.token, payload.new_password)
    return MessageResponse(message="Password has been reset")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest, current: CurrentUserDep, service: AuthServiceDep
):
    await service.change_password(current.id, payload.current_password, payload.new_password)
    return MessageResponse(message="Password changed")
