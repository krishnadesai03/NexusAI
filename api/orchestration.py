from __future__ import annotations

from uuid import UUID

from api.auth_service import AuthenticatedUser
from api.conversation_store import ConversationStore
from api.demo_outbox import DemoEmailClient, DemoSlackClient
from enterprise_ai.access_policy import AccessContext, Role
from enterprise_ai.bootstrap import SharedResources, build_session_orchestrator
from enterprise_ai.orchestrator.memory import MAX_TURNS, ConversationMemory
from enterprise_ai.orchestrator.orchestrator import Orchestrator


def build_user_orchestrator(
    shared: SharedResources,
    store: ConversationStore,
    user: AuthenticatedUser,
    memory: ConversationMemory | None = None,
) -> Orchestrator:
    access_context = AccessContext(
        role=Role(user.employee_role),
        department=user.department,
        employee_id=user.employee_id,
    )
    communication_override = None
    if user.is_demo:
        if user.persona_slug is None:
            raise ValueError("Demo user is missing a persona slug")
        communication_override = (
            shared.llm_client,
            DemoSlackClient(store, user.id, user.persona_slug),
            DemoEmailClient(store, user.id, user.persona_slug),
        )
    return build_session_orchestrator(
        shared,
        user_display_name=user.display_name,
        memory=memory,
        access_context=access_context,
        communication_clients_override=communication_override,
    )


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
    return build_user_orchestrator(shared, store, user, memory)
