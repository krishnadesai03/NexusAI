from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.auth_service import AuthenticatedUser
from api.conversation_store import Conversation, ConversationNotFoundError, ConversationStore, StoredTurn
from api.dependencies import get_conversation_store, get_current_session
from api.schemas import (
    AgentResultResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationTurnResponse,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _turn_response(turn: StoredTurn) -> ConversationTurnResponse:
    return ConversationTurnResponse(
        id=turn.id,
        user_message=turn.user_request,
        routed_to=turn.routed_to,
        results={name: AgentResultResponse.model_validate(result) for name, result in turn.results.items()},
        created_at=turn.created_at,
    )


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreateRequest,
    user: AuthenticatedUser = Depends(get_current_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> ConversationResponse:
    title = payload.title.strip() or "New conversation"
    return _conversation_response(await store.create_conversation(user.id, title[:80]))


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    user: AuthenticatedUser = Depends(get_current_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> list[ConversationResponse]:
    conversations = await store.list_conversations(user.id)
    return [_conversation_response(conversation) for conversation in conversations]


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: UUID,
    user: AuthenticatedUser = Depends(get_current_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> ConversationDetailResponse:
    try:
        conversation = await store.get_conversation(user.id, conversation_id)
        turns = await store.list_turns(user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc
    return ConversationDetailResponse(
        **_conversation_response(conversation).model_dump(),
        turns=[_turn_response(turn) for turn in turns],
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    user: AuthenticatedUser = Depends(get_current_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> None:
    try:
        await store.delete_conversation(user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found.") from exc
