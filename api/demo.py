"""Public persona discovery and anonymous demo-session creation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.auth_service import generate_demo_token, hash_demo_token
from api.conversation_store import ConversationStore
from api.dependencies import get_conversation_store
from api.schemas import DemoPersonaResponse, DemoSessionCreateRequest, DemoSessionResponse
from enterprise_ai.access_policy import DEMO_PERSONAS, DemoPersona, get_demo_persona

router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_SESSION_LIFETIME = timedelta(hours=24)


def _persona_response(persona: DemoPersona) -> DemoPersonaResponse:
    return DemoPersonaResponse(
        slug=persona.slug,
        display_name=persona.display_name,
        title=persona.title,
        role=persona.role.value,
        department=persona.department,
    )


@router.get("/personas", response_model=list[DemoPersonaResponse])
async def list_demo_personas() -> list[DemoPersonaResponse]:
    return [_persona_response(persona) for persona in DEMO_PERSONAS.values()]


@router.post("/sessions", response_model=DemoSessionResponse, status_code=201)
async def create_demo_session(
    payload: DemoSessionCreateRequest,
    store: ConversationStore = Depends(get_conversation_store),
) -> DemoSessionResponse:
    try:
        persona = get_demo_persona(payload.persona_slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unknown demo persona.") from exc
    token = generate_demo_token()
    expires_at = datetime.now(timezone.utc) + DEMO_SESSION_LIFETIME
    session = await store.create_demo_session(hash_demo_token(token), persona.slug, expires_at)
    return DemoSessionResponse(
        token=token,
        expires_at=session.expires_at,
        persona=_persona_response(persona),
    )
