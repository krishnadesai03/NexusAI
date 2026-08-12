from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_session
from api.schemas import ChatRequest, ChatResponse, agent_result_to_response
from api.sessions import SessionState
from enterprise_ai.core.agent import ConfirmableAgent
from enterprise_ai.orchestrator.orchestrator import Orchestrator

router = APIRouter(tags=["chat"])


def _find_pending_agent(orchestrator: Orchestrator) -> str | None:
    """Backstop for the HITL flow: the Communication Agent only ever holds one pending action at
    a time (learnings.md #8), so a second unrelated message arriving before it's resolved could
    silently orphan the first draft. Enforced here, not just by disabling the frontend's input box,
    since the frontend disabling itself is a UX nicety, not something the backend can trust."""
    for name in orchestrator.agent_names():
        agent = orchestrator.get_agent(name)
        if isinstance(agent, ConfirmableAgent) and agent.has_pending():
            return name
    return None


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, session: SessionState = Depends(get_current_session)) -> ChatResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    pending_agent = _find_pending_agent(session.orchestrator)
    if pending_agent is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "There's already a pending action to resolve first.", "agent": pending_agent},
        )

    result = await session.orchestrator.handle(payload.message)
    return ChatResponse(
        routed_to=result.routed_to,
        results={name: agent_result_to_response(agent_result) for name, agent_result in result.results.items()},
    )
