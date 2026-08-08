from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class AgentResult:
    """Uniform result shape every sub-agent returns to the orchestrator."""

    agent_name: str
    content: str
    metadata: dict | None = None


class Agent(Protocol):
    """Interface all sub-agent nodes (knowledge, performance, database, communication)
    implement, so the orchestrator can invoke any of them identically."""

    async def handle(self, user_request: str) -> AgentResult: ...
