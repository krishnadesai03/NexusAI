"""Persistent, SSE-streaming chat endpoint."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.auth_service import AuthenticatedUser
from api.conversation_store import ConversationNotFoundError, ConversationStore
from api.dependencies import get_conversation_store, get_current_session, get_shared_resources
from api.orchestration import build_conversation_orchestrator
from api.schemas import ChatRequest, ChatResponse, agent_result_to_response
from enterprise_ai.bootstrap import SharedResources
from enterprise_ai.core.agent import PersistableConfirmableAgent

router = APIRouter(tags=["chat"])

_STREAM_DONE = object()


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    user: AuthenticatedUser = Depends(get_current_session),
    shared: SharedResources = Depends(get_shared_resources),
    store: ConversationStore = Depends(get_conversation_store),
) -> StreamingResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    try:
        pending = await store.get_pending(user.id, payload.conversation_id)
        orchestrator = await build_conversation_orchestrator(
            shared, store, user, payload.conversation_id
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc

    if pending is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "There's already a pending action to resolve first.", "agent": pending.agent_name},
        )

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(event: dict) -> None:
            queue.put_nowait(event)

        async def run() -> None:
            try:
                result = await orchestrator.handle(payload.message, on_event)
                response_results = {
                    name: agent_result_to_response(agent_result)
                    for name, agent_result in result.results.items()
                }

                pending_agent: str | None = None
                pending_payload: dict | None = None
                for name in result.routed_to:
                    agent = orchestrator.get_agent(name)
                    if isinstance(agent, PersistableConfirmableAgent) and agent.has_pending():
                        pending_agent = name
                        pending_payload = agent.export_pending()
                        break

                stored_turn = await store.save_turn(
                    user.id,
                    payload.conversation_id,
                    payload.message,
                    result.routed_to,
                    {name: value.model_dump() for name, value in response_results.items()},
                    pending_agent,
                    pending_payload,
                )
                response = ChatResponse(
                    conversation_id=payload.conversation_id,
                    turn_id=stored_turn.id,
                    routed_to=result.routed_to,
                    results=response_results,
                )
                queue.put_nowait({"type": "done", "result": response.model_dump(mode="json")})
            except Exception as exc:  # noqa: BLE001 - stream errors cannot change HTTP status
                queue.put_nowait({"type": "error", "error": str(exc)})
            finally:
                queue.put_nowait(_STREAM_DONE)

        asyncio.create_task(run())

        while True:
            event = await queue.get()
            if event is _STREAM_DONE:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
