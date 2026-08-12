"""Pydantic request/response models for the web API, matching the contract in learnings.md's
Component 9 (Web UI) section. Kept separate from enterprise_ai.orchestrator.schemas — these
describe the HTTP wire format, not the LLM-facing routing schema."""

from __future__ import annotations

from pydantic import BaseModel

from enterprise_ai.core.agent import AgentResult


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    display_name: str


class MeResponse(BaseModel):
    display_name: str


class ChatRequest(BaseModel):
    message: str


class AgentResultResponse(BaseModel):
    content: str
    citations: list[str] = []
    requires_confirmation: bool = False


class ChatResponse(BaseModel):
    routed_to: list[str]
    results: dict[str, AgentResultResponse]


class PendingAgentRequest(BaseModel):
    agent: str


class PendingReviseRequest(BaseModel):
    agent: str
    edit_instructions: str


class ErrorResponse(BaseModel):
    error: str
    agent: str | None = None


def agent_result_to_response(result: AgentResult) -> AgentResultResponse:
    """Shared by /chat (per routed agent) and /pending/* (same shape — confirm/cancel/revise all
    resolve to one agent's outcome), so the two endpoint groups don't each define their own
    near-identical response model."""
    metadata = result.metadata or {}
    return AgentResultResponse(
        content=result.content,
        citations=metadata.get("citations", []),
        requires_confirmation=bool(metadata.get("requires_confirmation", False)),
    )
