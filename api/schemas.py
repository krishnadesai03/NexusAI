"""Pydantic request/response models for the web API, matching the contract in learnings.md's
Component 9 (Web UI) section. Kept separate from enterprise_ai.orchestrator.schemas — these
describe the HTTP wire format, not the LLM-facing routing schema."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from enterprise_ai.core.agent import AgentResult


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    refresh_token: str
    expires_in: int
    display_name: str


class RefreshRequest(BaseModel):
    refresh_token: str


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    employee_role: str


class ChatRequest(BaseModel):
    conversation_id: UUID
    message: str


class AgentResultResponse(BaseModel):
    content: str
    citations: list[str] = []
    requires_confirmation: bool = False


class ChatResponse(BaseModel):
    conversation_id: UUID
    turn_id: int
    routed_to: list[str]
    results: dict[str, AgentResultResponse]


class ConversationCreateRequest(BaseModel):
    title: str = "New conversation"


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationTurnResponse(BaseModel):
    id: int
    user_message: str
    routed_to: list[str]
    results: dict[str, AgentResultResponse]
    created_at: datetime


class ConversationDetailResponse(ConversationResponse):
    turns: list[ConversationTurnResponse]


class PendingAgentRequest(BaseModel):
    conversation_id: UUID
    agent: str


class PendingReviseRequest(BaseModel):
    conversation_id: UUID
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
