"""Declared as Depends()-injectable functions, not called directly inside route bodies, so
tests can swap them out via app.dependency_overrides without needing the real lifespan (real
Postgres/OpenAI/Atlassian connections) to run at all — see tests/unit/test_api.py."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from api.sessions import SessionState, SessionStore
from enterprise_ai.bootstrap import SharedResources


def get_shared_resources(request: Request) -> SharedResources:
    return request.app.state.shared


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


async def get_current_session(
    authorization: str | None = Header(default=None),
    session_store: SessionStore = Depends(get_session_store),
) -> SessionState:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")

    token = authorization.split(" ", 1)[1].strip()
    session = session_store.get(token)
    if session is None:
        raise HTTPException(status_code=401, detail="Session is invalid or has expired.")
    return session
