"""Generic pending-action endpoints — not /communication/* — since ConfirmableAgent
(learnings.md #8) is a protocol any future agent could implement, not something specific to the
Communication Agent. The frontend gets the agent name from /chat's `requires_confirmation` result
and echoes it back here rather than the backend guessing which agent has something staged."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_session
from api.schemas import AgentResultResponse, PendingAgentRequest, PendingReviseRequest, agent_result_to_response
from api.sessions import SessionState
from enterprise_ai.core.agent import ConfirmableAgent

router = APIRouter(prefix="/pending", tags=["pending"])


def _get_confirmable_agent(session: SessionState, agent_name: str) -> ConfirmableAgent:
    if agent_name not in session.orchestrator.agent_names():
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_name}")
    agent = session.orchestrator.get_agent(agent_name)
    if not isinstance(agent, ConfirmableAgent):
        raise HTTPException(status_code=400, detail=f"'{agent_name}' has nothing to confirm.")
    return agent


@router.post("/confirm", response_model=AgentResultResponse)
async def confirm(
    payload: PendingAgentRequest, session: SessionState = Depends(get_current_session)
) -> AgentResultResponse:
    agent = _get_confirmable_agent(session, payload.agent)
    result = await agent.confirm_pending()
    return agent_result_to_response(result)


@router.post("/cancel", response_model=AgentResultResponse)
async def cancel(
    payload: PendingAgentRequest, session: SessionState = Depends(get_current_session)
) -> AgentResultResponse:
    agent = _get_confirmable_agent(session, payload.agent)
    result = agent.cancel_pending()
    return agent_result_to_response(result)


@router.post("/revise", response_model=AgentResultResponse)
async def revise(
    payload: PendingReviseRequest, session: SessionState = Depends(get_current_session)
) -> AgentResultResponse:
    agent = _get_confirmable_agent(session, payload.agent)
    result = await agent.revise_pending(payload.edit_instructions)
    return agent_result_to_response(result)
