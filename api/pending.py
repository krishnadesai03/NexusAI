"""Durable human-in-the-loop action endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth_service import AuthenticatedUser
from api.conversation_store import ConversationStore, PendingAction
from api.dependencies import get_conversation_store, get_current_session, get_shared_resources
from api.orchestration import build_user_orchestrator
from api.schemas import AgentResultResponse, PendingAgentRequest, PendingReviseRequest, agent_result_to_response
from enterprise_ai.bootstrap import SharedResources
from enterprise_ai.core.agent import AgentResult, PersistableConfirmableAgent

router = APIRouter(prefix="/pending", tags=["pending"])


def _restore_agent(
    shared: SharedResources,
    store: ConversationStore,
    user: AuthenticatedUser,
    pending: PendingAction,
) -> PersistableConfirmableAgent:
    orchestrator = build_user_orchestrator(shared, store, user)
    if pending.agent_name not in orchestrator.agent_names():
        raise HTTPException(status_code=404, detail=f"Unknown agent: {pending.agent_name}")
    agent = orchestrator.get_agent(pending.agent_name)
    if not isinstance(agent, PersistableConfirmableAgent):
        raise HTTPException(status_code=400, detail=f"'{pending.agent_name}' cannot restore pending actions.")
    agent.restore_pending(pending.payload)
    return agent


async def _claim(
    payload: PendingAgentRequest,
    user: AuthenticatedUser,
    store: ConversationStore,
) -> PendingAction:
    pending = await store.claim_pending(user.id, payload.conversation_id, payload.agent)
    if pending is None:
        raise HTTPException(status_code=409, detail="There is no pending action to resolve.")
    return pending


@router.post("/confirm", response_model=AgentResultResponse)
async def confirm(
    payload: PendingAgentRequest,
    user: AuthenticatedUser = Depends(get_current_session),
    shared: SharedResources = Depends(get_shared_resources),
    store: ConversationStore = Depends(get_conversation_store),
) -> AgentResultResponse:
    pending = await _claim(payload, user, store)
    try:
        agent = _restore_agent(shared, store, user, pending)
        response = agent_result_to_response(await agent.confirm_pending())
    except Exception:
        await store.replace_pending(pending, pending.payload)
        raise
    await store.resolve_pending(pending, "completed", response.model_dump())
    return response


@router.post("/cancel", response_model=AgentResultResponse)
async def cancel(
    payload: PendingAgentRequest,
    user: AuthenticatedUser = Depends(get_current_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> AgentResultResponse:
    pending = await _claim(payload, user, store)
    response = agent_result_to_response(
        AgentResult(agent_name=pending.agent_name, content="Cancelled — nothing was sent.", metadata={"citations": []})
    )
    await store.resolve_pending(pending, "cancelled", response.model_dump())
    return response


@router.post("/revise", response_model=AgentResultResponse)
async def revise(
    payload: PendingReviseRequest,
    user: AuthenticatedUser = Depends(get_current_session),
    shared: SharedResources = Depends(get_shared_resources),
    store: ConversationStore = Depends(get_conversation_store),
) -> AgentResultResponse:
    pending = await _claim(payload, user, store)
    try:
        agent = _restore_agent(shared, store, user, pending)
        response = agent_result_to_response(await agent.revise_pending(payload.edit_instructions))
        replacement = agent.export_pending()
    except Exception:
        await store.replace_pending(pending, pending.payload)
        raise

    if response.requires_confirmation and replacement is not None:
        await store.replace_pending(pending, replacement, response.model_dump())
    else:
        await store.resolve_pending(pending, "completed", response.model_dump())
    return response
