"""Login is deliberately provision-only — no signup endpoint. Employees are handed credentials
the same way a real internal tool would issue them, not self-registered. The allowed list lives
in the APP_USERS_JSON env var (email + bcrypt password hash + display name) rather than a
database table for now — see .env.example and scripts/hash_password.py. Swapping this for a
Postgres `users` table later is a drop-in change to `_load_users()` alone; nothing else here
would need to change."""

from __future__ import annotations

import json
import os

import bcrypt
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_session, get_session_store, get_shared_resources
from api.schemas import LoginRequest, LoginResponse, MeResponse
from api.sessions import SessionState, SessionStore
from enterprise_ai.bootstrap import SharedResources, build_session_orchestrator

router = APIRouter(prefix="/auth", tags=["auth"])


def _load_users() -> dict[str, dict]:
    raw = os.environ.get("APP_USERS_JSON", "[]")
    users = json.loads(raw)
    return {user["email"].lower(): user for user in users}


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    shared: SharedResources = Depends(get_shared_resources),
    session_store: SessionStore = Depends(get_session_store),
) -> LoginResponse:
    users = _load_users()
    user = users.get(payload.email.strip().lower())
    if user is None or not bcrypt.checkpw(
        payload.password.encode("utf-8"), user["password_hash"].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    orchestrator = build_session_orchestrator(shared, user_display_name=user["display_name"])
    session = session_store.create(
        email=user["email"], display_name=user["display_name"], orchestrator=orchestrator
    )
    return LoginResponse(token=session.token, display_name=session.display_name)


@router.get("/me", response_model=MeResponse)
async def me(session: SessionState = Depends(get_current_session)) -> MeResponse:
    return MeResponse(display_name=session.display_name)


@router.post("/logout", status_code=204)
async def logout(
    session: SessionState = Depends(get_current_session),
    session_store: SessionStore = Depends(get_session_store),
) -> None:
    session_store.delete(session.token)
