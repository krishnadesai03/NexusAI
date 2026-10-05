from __future__ import annotations

from uuid import UUID

from api.auth_service import AuthenticatedUser
from api.conversation_store import ConversationStore
from enterprise_ai.bootstrap import SharedResources, build_session_orchestrator
from enterprise_ai.orchestrator.memory import MAX_TURNS, ConversationMemory
from enterprise_ai.orchestrator.orchestrator import Orchestrator


async def build_conversation_orchestrator(
    shared: SharedResources,
    store: ConversationStore,
    user: AuthenticatedUser,
    conversation_id: UUID,
) -> Orchestrator:
    turns = await store.recent_turns(user.id, conversation_id, MAX_TURNS)
    memory = ConversationMemory()
    for turn in turns:
        answers = {name: result["content"] for name, result in turn.results.items()}
        memory.add_stored_turn(turn.user_request, answers)
    return build_session_orchestrator(shared, user_display_name=user.display_name, memory=memory)
