"""Supabase-backed authentication for provisioned internal users."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth_service import AuthClient, AuthenticatedUser, AuthenticationError, AuthTokens
from api.dependencies import get_auth_client, get_current_session
from api.schemas import LoginRequest, LoginResponse, MeResponse, RefreshRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def _login_response(tokens: AuthTokens) -> LoginResponse:
    return LoginResponse(
        token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        display_name=tokens.display_name,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    auth_client: AuthClient = Depends(get_auth_client),
) -> LoginResponse:
    try:
        tokens = await auth_client.login(payload.email.strip().lower(), payload.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _login_response(tokens)


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    payload: RefreshRequest,
    auth_client: AuthClient = Depends(get_auth_client),
) -> LoginResponse:
    try:
        tokens = await auth_client.refresh(payload.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return _login_response(tokens)


@router.get("/me", response_model=MeResponse)
async def me(user: AuthenticatedUser = Depends(get_current_session)) -> MeResponse:
    return MeResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        employee_role=user.employee_role,
        persona_slug=user.persona_slug,
        title=user.title,
        department=user.department,
        employee_id=user.employee_id,
        is_demo=user.is_demo,
    )


@router.post("/logout", status_code=204)
async def logout(
    user: AuthenticatedUser = Depends(get_current_session),
    auth_client: AuthClient = Depends(get_auth_client),
) -> None:
    if user.is_demo:
        return
    await auth_client.logout(user.access_token)
