"""FastAPI dependency seams, kept overrideable for network-free unit tests."""

from __future__ import annotations

from dataclasses import replace

from fastapi import Depends, Header, HTTPException, Request

from api.auth_service import AuthClient, AuthenticatedUser, AuthenticationError, TokenVerifier
from api.conversation_store import ConversationStore
from enterprise_ai.bootstrap import SharedResources


def get_shared_resources(request: Request) -> SharedResources:
    return request.app.state.shared


def get_conversation_store(request: Request) -> ConversationStore:
    return request.app.state.conversations


def get_auth_client(request: Request) -> AuthClient:
    return request.app.state.auth_client


def get_token_verifier(request: Request) -> TokenVerifier:
    return request.app.state.token_verifier


async def get_current_session(
    authorization: str | None = Header(default=None),
    verifier: TokenVerifier = Depends(get_token_verifier),
    store: ConversationStore = Depends(get_conversation_store),
) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header.")

    token = authorization.split(" ", 1)[1].strip()
    try:
        user = await verifier.verify(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="Session is invalid or has expired.") from exc
    if not await store.is_auth_session_active(user.session_id):
        raise HTTPException(status_code=401, detail="Session is invalid or has expired.")
    profile = await store.get_profile(user.id)
    if profile is None:
        raise HTTPException(status_code=403, detail="This account has no employee profile.")
    display_name, employee_role = profile
    return replace(user, display_name=display_name, employee_role=employee_role)
