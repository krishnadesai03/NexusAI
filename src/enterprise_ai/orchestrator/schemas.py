from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["knowledge", "performance", "database", "communication"]


class RoutingDecision(BaseModel):
    """The only shape a routing decision is allowed to take. Forcing the LLM's
    output through this schema is the 'hard schema guardrail' from learnings.md #1:
    it can reason about intent however it wants, but its answer must resolve to
    one or more of these four fixed agent names."""

    agents: list[AgentName] = Field(
        min_length=1,
        description="Every agent needed to fully answer the request. More than one "
        "means the request should fan out to multiple agents in parallel.",
    )
    reasoning: str = Field(
        description="Brief justification for the choice, kept for tracing/eval — not shown to the user."
    )
