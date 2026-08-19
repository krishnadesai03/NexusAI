from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

# Live orchestration-trace callback (Component 10 / learnings.md): fired synchronously by
# Orchestrator and each agent as routing/tool-call steps actually happen, so a caller (the web
# API's SSE endpoint) can stream them to a client in real time. Plain dicts, not a typed schema —
# shape varies per event `type` and this is a UI/observability concern, not a guardrail boundary
# that needs Pydantic validation. Optional everywhere, defaulting to None, so every existing
# caller (scripts/chat.py, the whole test suite) is unaffected.
OnEvent = Callable[[dict], None]


def emit_event(on_event: OnEvent | None, event: dict) -> None:
    """No-ops when on_event is None so every call site can emit unconditionally instead of
    repeating `if on_event:` at each of the ~15 places this gets called across the agents."""
    if on_event is not None:
        on_event(event)


@dataclass
class AgentResult:
    """Uniform result shape every sub-agent returns to the orchestrator."""

    agent_name: str
    content: str
    metadata: dict | None = None


class Agent(Protocol):
    """Interface all sub-agent nodes (knowledge, performance, database, communication)
    implement, so the orchestrator can invoke any of them identically.

    `history` is prior conversation turns in OpenAI chat-message shape (learnings.md #7),
    supplied by Orchestrator's ConversationMemory — None/empty on a session's first turn.
    Optional so existing single-turn callers/tests keep working unchanged.

    `on_event` is the live-trace callback described above — also optional for the same reason."""

    async def handle(
        self, user_request: str, history: list[dict] | None = None, on_event: OnEvent | None = None
    ) -> AgentResult: ...


@runtime_checkable
class ConfirmableAgent(Protocol):
    """Optional extra interface (learnings.md #8) for agents that can stage an action pending
    human confirmation before it actually executes. Agent.handle() alone can only say "here's
    my answer" — it can't express "I drafted something, don't do it yet." Rather than adding
    these methods to the base Agent protocol (every read-only agent has nothing to confirm and
    would be forced to implement no-op versions), this is checked for separately, at runtime,
    via `isinstance(agent, ConfirmableAgent)` — so Orchestrator/chat.py can support it generically
    without hardcoding which specific agent it applies to, and ordinary agents need zero changes."""

    def has_pending(self) -> bool: ...
    async def confirm_pending(self) -> AgentResult: ...
    def cancel_pending(self) -> AgentResult: ...
    async def revise_pending(self, edit_instructions: str) -> AgentResult: ...
