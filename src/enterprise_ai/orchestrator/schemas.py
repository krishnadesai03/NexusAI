from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

AgentName = Literal["knowledge", "performance", "database", "communication"]
Intent = Literal["business", "greeting", "system_help", "unsupported", "unsafe"]


class RoutingDecision(BaseModel):
    """One-call routing result with strict business/direct-response invariants."""

    intent: Intent
    agents: list[AgentName] = Field(description="Business agents to call; empty for non-business intents.")
    answer: str | None = Field(description="Direct answer for non-business intents; null for business requests.")

    @model_validator(mode="after")
    def validate_decision(self) -> RoutingDecision:
        if self.intent == "business":
            if not self.agents or self.answer is not None:
                raise ValueError("business decisions require agents and answer=null")
        elif self.agents or not self.answer or not self.answer.strip():
            raise ValueError("non-business decisions require agents=[] and a non-empty answer")
        return self
