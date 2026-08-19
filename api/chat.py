"""POST /chat streams over Server-Sent Events rather than returning one JSON blob — this is what
lets the frontend's "Working" trace panel show routing/agent/tool-call steps live, as they
actually happen inside Orchestrator.handle(), instead of only after the whole request finishes.
Every event is a JSON object on its own `data: ...` line; the stream always ends with either a
`done` event (carrying the same ChatResponse shape /chat always returned) or an `error` event.

Validation that needs to change the HTTP status code (empty message, the 409 pending-conflict
guard) happens *before* the stream starts, since headers can't change once streaming begins.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.dependencies import get_current_session
from api.schemas import ChatRequest, ChatResponse, agent_result_to_response
from api.sessions import SessionState
from enterprise_ai.core.agent import ConfirmableAgent
from enterprise_ai.orchestrator.orchestrator import Orchestrator

router = APIRouter(tags=["chat"])

_STREAM_DONE = object()  # internal sentinel — never serialized, just tells the generator to stop


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


@router.post("/chat")
async def chat(payload: ChatRequest, session: SessionState = Depends(get_current_session)) -> StreamingResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    pending_agent = _find_pending_agent(session.orchestrator)
    if pending_agent is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "There's already a pending action to resolve first.", "agent": pending_agent},
        )

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(event: dict) -> None:
            queue.put_nowait(event)

        async def run() -> None:
            try:
                result = await session.orchestrator.handle(payload.message, on_event)
                response = ChatResponse(
                    routed_to=result.routed_to,
                    results={
                        name: agent_result_to_response(agent_result) for name, agent_result in result.results.items()
                    },
                )
                queue.put_nowait({"type": "done", "result": response.model_dump()})
            except Exception as exc:  # noqa: BLE001 — reported as a stream event; an HTTP status
                # code can no longer change at this point, headers were already sent.
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
