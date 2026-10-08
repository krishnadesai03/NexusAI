from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api.auth_service import AuthenticatedUser, AuthenticationError, AuthTokens, hash_demo_token
from api.conversation_store import (
    Conversation,
    ConversationNotFoundError,
    DemoDelivery,
    DemoSession,
    PendingAction,
    StoredTurn,
)
from api.dependencies import (
    get_auth_client,
    get_conversation_store,
    get_current_session,
    get_shared_resources,
    get_token_verifier,
)
from api.demo_outbox import DemoEmailClient
from api.main import app
from enterprise_ai.bootstrap import SharedResources
from enterprise_ai.core.agent import AgentResult
from enterprise_ai.core.llm_client import ToolCall, ToolResponse
from enterprise_ai.orchestrator.router import Router
from enterprise_ai.orchestrator.schemas import RoutingDecision

client = TestClient(app)
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
SESSION_ID = UUID("33333333-3333-3333-3333-333333333333")
NOW = datetime.now(timezone.utc)


def _parse_sse_events(text: str) -> list[dict]:
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]


class FakeAuthClient:
    def __init__(self) -> None:
        self.logged_out: list[str] = []

    async def login(self, email: str, password: str) -> AuthTokens:
        if password != "correct-horse":
            raise AuthenticationError("Invalid email or password.")
        return AuthTokens("access", "refresh", 3600, "Priya Nair")

    async def refresh(self, refresh_token: str) -> AuthTokens:
        if refresh_token != "refresh":
            raise AuthenticationError("Session is invalid or has expired.")
        return AuthTokens("new-access", "new-refresh", 3600, "Priya Nair")

    async def logout(self, access_token: str) -> None:
        self.logged_out.append(access_token)

    async def close(self) -> None:
        pass


class FakeVerifier:
    async def verify(self, token: str) -> AuthenticatedUser:
        if token != "access":
            raise AuthenticationError("invalid")
        return _user(access_token=token)


class FakeConversationStore:
    def __init__(self) -> None:
        self.conversations: dict[UUID, Conversation] = {}
        self.turns: dict[UUID, list[StoredTurn]] = {}
        self.pending: dict[UUID, PendingAction] = {}
        self.demo_sessions: dict[str, DemoSession] = {}
        self.demo_deliveries: dict[UUID, DemoDelivery] = {}
        self.next_turn_id = 1

    async def create_demo_session(
        self, token_hash: str, persona_slug: str, expires_at: datetime
    ) -> DemoSession:
        session = DemoSession(uuid4(), persona_slug, NOW, NOW, expires_at)
        self.demo_sessions[token_hash] = session
        return session

    async def get_and_extend_demo_session(
        self, token_hash: str, expires_at: datetime
    ) -> DemoSession | None:
        session = self.demo_sessions.get(token_hash)
        if session is None or session.expires_at <= datetime.now(timezone.utc):
            return None
        extended = replace(session, last_seen_at=datetime.now(timezone.utc), expires_at=expires_at)
        self.demo_sessions[token_hash] = extended
        return extended

    async def create_demo_delivery(
        self,
        demo_session_id: UUID,
        persona_slug: str,
        channel: str,
        recipient: str,
        subject: str | None,
        content: str,
    ) -> DemoDelivery:
        delivery = DemoDelivery(
            uuid4(),
            demo_session_id,
            persona_slug,
            channel,
            recipient,
            subject,
            content,
            "captured",
            NOW,
            NOW + timedelta(days=1),
        )
        self.demo_deliveries[delivery.id] = delivery
        return delivery

    async def list_demo_deliveries(self, demo_session_id: UUID) -> list[DemoDelivery]:
        return [
            delivery
            for delivery in self.demo_deliveries.values()
            if delivery.demo_session_id == demo_session_id
            and delivery.expires_at > datetime.now(timezone.utc)
        ]

    async def is_auth_session_active(self, session_id: UUID) -> bool:
        return session_id == SESSION_ID

    async def get_profile(self, user_id: UUID) -> tuple[str, str] | None:
        return ("Priya Nair", "employee") if user_id == USER_ID else None

    async def create_conversation(self, user_id: UUID, title: str = "New conversation") -> Conversation:
        conversation = Conversation(uuid4(), user_id, title, NOW, NOW)
        self.conversations[conversation.id] = conversation
        self.turns[conversation.id] = []
        return conversation

    async def list_conversations(self, user_id: UUID) -> list[Conversation]:
        return [item for item in self.conversations.values() if item.user_id == user_id]

    async def get_conversation(self, user_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = self.conversations.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise ConversationNotFoundError(str(conversation_id))
        return conversation

    async def delete_conversation(self, user_id: UUID, conversation_id: UUID) -> None:
        await self.get_conversation(user_id, conversation_id)
        del self.conversations[conversation_id]
        self.turns.pop(conversation_id, None)
        self.pending.pop(conversation_id, None)

    async def list_turns(self, user_id: UUID, conversation_id: UUID) -> list[StoredTurn]:
        await self.get_conversation(user_id, conversation_id)
        return list(self.turns[conversation_id])

    async def recent_turns(self, user_id: UUID, conversation_id: UUID, limit: int) -> list[StoredTurn]:
        return (await self.list_turns(user_id, conversation_id))[-limit:]

    async def save_turn(
        self,
        user_id: UUID,
        conversation_id: UUID,
        user_request: str,
        routed_to: list[str],
        results: dict,
        pending_agent: str | None = None,
        pending_payload: dict | None = None,
    ) -> StoredTurn:
        conversation = await self.get_conversation(user_id, conversation_id)
        turn = StoredTurn(self.next_turn_id, conversation_id, user_request, routed_to, results, NOW)
        self.next_turn_id += 1
        self.turns[conversation_id].append(turn)
        if conversation.title == "New conversation":
            self.conversations[conversation_id] = replace(conversation, title=user_request[:80])
        if pending_agent and pending_payload:
            self.pending[conversation_id] = PendingAction(
                uuid4(), conversation_id, turn.id, user_id, pending_agent, pending_payload, "pending", NOW + timedelta(days=1)
            )
        return turn

    async def get_pending(self, user_id: UUID, conversation_id: UUID) -> PendingAction | None:
        await self.get_conversation(user_id, conversation_id)
        pending = self.pending.get(conversation_id)
        return pending if pending and pending.status == "pending" else None

    async def claim_pending(self, user_id: UUID, conversation_id: UUID, agent_name: str) -> PendingAction | None:
        pending = await self.get_pending(user_id, conversation_id)
        if pending is None or pending.agent_name != agent_name:
            return None
        claimed = replace(pending, status="executing")
        self.pending[conversation_id] = claimed
        return claimed

    async def replace_pending(self, pending: PendingAction, payload: dict, result: dict | None = None) -> None:
        self.pending[pending.conversation_id] = replace(pending, payload=payload, status="pending")
        if result is not None:
            self._replace_turn_result(pending, result)

    async def resolve_pending(self, pending: PendingAction, status: str, result: dict) -> None:
        self.pending[pending.conversation_id] = replace(pending, status=status)
        self._replace_turn_result(pending, result)

    def _replace_turn_result(self, pending: PendingAction, result: dict) -> None:
        turns = self.turns[pending.conversation_id]
        for index, turn in enumerate(turns):
            if turn.id == pending.turn_id:
                results = {**turn.results, pending.agent_name: result}
                turns[index] = replace(turn, results=results)

    async def close(self) -> None:
        pass


class FakeLLMClient:
    def __init__(self, route_to: list[str]):
        self.route_to = route_to
        self.history_seen: list[str] = []

    async def get_structured_output(self, *, system_prompt, user_prompt, schema):
        self.history_seen.append(user_prompt)
        return RoutingDecision(agents=self.route_to, reasoning="test")


class FakeAgent:
    def __init__(self, name: str):
        self.name = name

    async def handle(self, user_request, history=None, on_event=None, tool_cache=None):
        history_size = len(history or [])
        return AgentResult(agent_name=self.name, content=f"{self.name} handled it with {history_size} history messages")


class CommunicationLLM(FakeLLMClient):
    async def get_tool_response(self, *, messages, tools):
        return ToolResponse(
            content=None,
            tool_calls=[ToolCall(id="call-1", name="send_slack_message", arguments={"text": "Hello team"})],
        )


class FakeSlack:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, text: str) -> dict:
        self.sent.append(text)
        return {"ok": True}


class FakeEmail:
    async def send_email(self, subject: str, body: str, recipient_alias: str | None = None) -> dict:
        return {"ok": True}


def _user(user_id: UUID = USER_ID, access_token: str = "access") -> AuthenticatedUser:
    return AuthenticatedUser(user_id, SESSION_ID, "priya@company.example", "Priya Nair", "employee", access_token)


def _shared(route_to: list[str] | None = None, communication: bool = False) -> SharedResources:
    route_to = route_to or ["knowledge"]
    llm = CommunicationLLM(route_to) if communication else FakeLLMClient(route_to)
    return SharedResources(
        router=Router(llm),
        knowledge_agent=FakeAgent("knowledge"),
        performance_agent=FakeAgent("performance"),
        database_agent=FakeAgent("database"),
        vector_store=None,
        db_query_client=None,
        llm_client=llm,
        communication_clients=(llm, FakeSlack(), FakeEmail()) if communication else None,
        atlassian_mcp_session=None,
    )


@pytest.fixture(autouse=True)
def reset_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def _authenticated(store: FakeConversationStore, shared: SharedResources | None = None) -> None:
    app.dependency_overrides[get_current_session] = _user
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_shared_resources] = lambda: shared or _shared()


def test_login_and_refresh_use_supabase_auth_client():
    auth = FakeAuthClient()
    app.dependency_overrides[get_auth_client] = lambda: auth
    login = client.post("/auth/login", json={"email": "priya@company.example", "password": "correct-horse"})
    refresh = client.post("/auth/refresh", json={"refresh_token": "refresh"})
    assert login.status_code == 200
    assert login.json()["refresh_token"] == "refresh"
    assert refresh.json()["token"] == "new-access"


def test_login_rejects_bad_credentials():
    app.dependency_overrides[get_auth_client] = FakeAuthClient
    response = client.post("/auth/login", json={"email": "priya@company.example", "password": "wrong"})
    assert response.status_code == 401


def test_refresh_rejects_unknown_refresh_token():
    app.dependency_overrides[get_auth_client] = FakeAuthClient
    response = client.post("/auth/refresh", json={"refresh_token": "wrong"})
    assert response.status_code == 401


def test_token_verifier_protects_me():
    store = FakeConversationStore()
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    app.dependency_overrides[get_conversation_store] = lambda: store
    assert client.get("/auth/me").status_code == 401
    response = client.get("/auth/me", headers={"Authorization": "Bearer access"})
    assert response.status_code == 200
    assert response.json()["user_id"] == str(USER_ID)


def test_logout_revokes_supabase_session():
    auth = FakeAuthClient()
    app.dependency_overrides[get_current_session] = _user
    app.dependency_overrides[get_auth_client] = lambda: auth
    assert client.post("/auth/logout").status_code == 204
    assert auth.logged_out == ["access"]


def test_demo_personas_are_publicly_discoverable():
    response = client.get("/demo/personas")
    assert response.status_code == 200
    assert [persona["slug"] for persona in response.json()] == ["sofia-reyes", "matt-davidson"]


def test_demo_session_uses_hashed_token_and_restores_persona():
    store = FakeConversationStore()
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_token_verifier] = FakeVerifier

    created = client.post("/demo/sessions", json={"persona_slug": "sofia-reyes"})
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("demo_")
    assert token not in store.demo_sessions
    assert hash_demo_token(token) in store.demo_sessions

    headers = {"Authorization": f"Bearer {token}"}
    first = client.get("/auth/me", headers=headers)
    second = client.get("/auth/me", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["user_id"] == second.json()["user_id"]
    assert first.json()["persona_slug"] == "sofia-reyes"
    assert first.json()["department"] == "Engineering"
    assert first.json()["employee_id"] == 4
    assert first.json()["is_demo"] is True


def test_demo_sessions_isolate_conversations_between_visitors():
    store = FakeConversationStore()
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_token_verifier] = FakeVerifier

    sofia_token = client.post("/demo/sessions", json={"persona_slug": "sofia-reyes"}).json()["token"]
    matt_token = client.post("/demo/sessions", json={"persona_slug": "matt-davidson"}).json()["token"]
    sofia_headers = {"Authorization": f"Bearer {sofia_token}"}
    matt_headers = {"Authorization": f"Bearer {matt_token}"}

    assert client.post("/conversations", json={"title": "Sofia private"}, headers=sofia_headers).status_code == 201
    assert client.post("/conversations", json={"title": "Matt private"}, headers=matt_headers).status_code == 201

    assert [item["title"] for item in client.get("/conversations", headers=sofia_headers).json()] == ["Sofia private"]
    assert [item["title"] for item in client.get("/conversations", headers=matt_headers).json()] == ["Matt private"]


def test_expired_demo_session_is_rejected():
    store = FakeConversationStore()
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    token = client.post("/demo/sessions", json={"persona_slug": "sofia-reyes"}).json()["token"]
    token_hash = hash_demo_token(token)
    store.demo_sessions[token_hash] = replace(
        store.demo_sessions[token_hash], expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_unknown_demo_persona_is_rejected():
    store = FakeConversationStore()
    app.dependency_overrides[get_conversation_store] = lambda: store
    response = client.post("/demo/sessions", json={"persona_slug": "unknown"})
    assert response.status_code == 404


def test_conversations_are_created_listed_loaded_and_deleted():
    store = FakeConversationStore()
    _authenticated(store)
    created = client.post("/conversations", json={"title": "Benefits"})
    conversation_id = created.json()["id"]
    assert client.get("/conversations").json()[0]["title"] == "Benefits"
    assert client.get(f"/conversations/{conversation_id}").json()["turns"] == []
    assert client.delete(f"/conversations/{conversation_id}").status_code == 204


def test_user_cannot_load_another_users_conversation():
    store = FakeConversationStore()
    conversation = Conversation(uuid4(), OTHER_USER_ID, "Private", NOW, NOW)
    store.conversations[conversation.id] = conversation
    store.turns[conversation.id] = []
    _authenticated(store)
    assert client.get(f"/conversations/{conversation.id}").status_code == 404


def test_conversation_list_only_contains_current_users_rows():
    store = FakeConversationStore()
    own = Conversation(uuid4(), USER_ID, "Mine", NOW, NOW)
    other = Conversation(uuid4(), OTHER_USER_ID, "Not mine", NOW, NOW)
    store.conversations = {own.id: own, other.id: other}
    store.turns = {own.id: [], other.id: []}
    _authenticated(store)
    assert [item["title"] for item in client.get("/conversations").json()] == ["Mine"]


def test_chat_persists_turn_and_rehydrates_memory_on_next_request():
    store = FakeConversationStore()
    _authenticated(store)
    conversation = client.post("/conversations", json={}).json()
    payload = {"conversation_id": conversation["id"], "message": "First question"}
    first = _parse_sse_events(client.post("/chat", json=payload).text)[-1]["result"]
    second_payload = {"conversation_id": conversation["id"], "message": "Follow up"}
    second = _parse_sse_events(client.post("/chat", json=second_payload).text)[-1]["result"]
    assert first["turn_id"] == 1
    assert "0 history messages" in first["results"]["knowledge"]["content"]
    assert "2 history messages" in second["results"]["knowledge"]["content"]
    assert len(store.turns[UUID(conversation["id"])]) == 2


def test_chat_rejects_unknown_conversation():
    store = FakeConversationStore()
    _authenticated(store)
    response = client.post("/chat", json={"conversation_id": str(uuid4()), "message": "Hello"})
    assert response.status_code == 404


def test_chat_rejects_empty_message():
    store = FakeConversationStore()
    _authenticated(store)
    conversation = client.post("/conversations", json={}).json()
    response = client.post("/chat", json={"conversation_id": conversation["id"], "message": "   "})
    assert response.status_code == 400


def test_chat_streams_parallel_agent_branches():
    store = FakeConversationStore()
    _authenticated(store, _shared(["knowledge", "database"]))
    conversation = client.post("/conversations", json={}).json()
    response = client.post(
        "/chat",
        json={"conversation_id": conversation["id"], "message": "Compare policy to company data"},
    )
    events = _parse_sse_events(response.text)
    started = {event["agent"] for event in events if event["type"] == "agent_started"}
    assert started == {"knowledge", "database"}


def test_pending_action_survives_fresh_orchestrators_and_confirms_once():
    store = FakeConversationStore()
    shared = _shared(["communication"], communication=True)
    _authenticated(store, shared)
    conversation = client.post("/conversations", json={}).json()
    request = {"conversation_id": conversation["id"], "message": "Send a Slack message"}
    result = _parse_sse_events(client.post("/chat", json=request).text)[-1]["result"]
    assert result["results"]["communication"]["requires_confirmation"] is True

    action = {"conversation_id": conversation["id"], "agent": "communication"}
    confirmed = client.post("/pending/confirm", json=action)
    duplicate = client.post("/pending/confirm", json=action)
    assert confirmed.status_code == 200
    assert confirmed.json()["requires_confirmation"] is False
    assert duplicate.status_code == 409


def test_demo_confirmation_captures_outbox_without_calling_real_slack():
    store = FakeConversationStore()
    shared = _shared(["communication"], communication=True)
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_shared_resources] = lambda: shared
    app.dependency_overrides[get_token_verifier] = FakeVerifier

    token = client.post("/demo/sessions", json={"persona_slug": "sofia-reyes"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    conversation = client.post("/conversations", json={}, headers=headers).json()
    request = {"conversation_id": conversation["id"], "message": "Send a Slack message"}
    staged = _parse_sse_events(client.post("/chat", json=request, headers=headers).text)[-1]["result"]
    assert staged["results"]["communication"]["requires_confirmation"] is True

    action = {"conversation_id": conversation["id"], "agent": "communication"}
    confirmed = client.post("/pending/confirm", json=action, headers=headers)
    assert confirmed.status_code == 200
    assert "Demo Outbox" in confirmed.json()["content"]
    assert "No external message was sent" in confirmed.json()["content"]

    real_slack = shared.communication_clients[1]
    assert real_slack.sent == []
    outbox = client.get("/demo/outbox", headers=headers)
    assert outbox.status_code == 200
    assert len(outbox.json()) == 1
    assert outbox.json()[0]["channel"] == "slack"
    assert outbox.json()[0]["status"] == "captured"


async def test_demo_outbox_is_isolated_between_sessions():
    store = FakeConversationStore()
    app.dependency_overrides[get_conversation_store] = lambda: store
    app.dependency_overrides[get_token_verifier] = FakeVerifier
    sofia_token = client.post("/demo/sessions", json={"persona_slug": "sofia-reyes"}).json()["token"]
    matt_token = client.post("/demo/sessions", json={"persona_slug": "matt-davidson"}).json()["token"]
    sofia_session = store.demo_sessions[hash_demo_token(sofia_token)]
    await store.create_demo_delivery(
        sofia_session.id,
        "sofia-reyes",
        "email",
        "Priya Nair",
        "Hello",
        "Private demo message",
    )

    sofia = client.get("/demo/outbox", headers={"Authorization": f"Bearer {sofia_token}"})
    matt = client.get("/demo/outbox", headers={"Authorization": f"Bearer {matt_token}"})
    assert len(sofia.json()) == 1
    assert matt.json() == []


async def test_demo_email_client_captures_subject_body_and_friendly_recipient():
    store = FakeConversationStore()
    session_id = uuid4()
    email = DemoEmailClient(store, session_id, "matt-davidson")

    result = await email.send_email("Quarterly update", "Revenue is on plan.", "priyanair")

    delivery = next(iter(store.demo_deliveries.values()))
    assert result["simulated"] is True
    assert delivery.demo_session_id == session_id
    assert delivery.channel == "email"
    assert delivery.recipient == "Priya Nair"
    assert delivery.subject == "Quarterly update"
    assert delivery.content == "Revenue is on plan."


def test_chat_blocks_a_second_message_while_action_is_pending():
    store = FakeConversationStore()
    _authenticated(store, _shared(["communication"], communication=True))
    conversation = client.post("/conversations", json={}).json()
    request = {"conversation_id": conversation["id"], "message": "Send a Slack message"}
    client.post("/chat", json=request)
    blocked = client.post("/chat", json=request)
    assert blocked.status_code == 409
    assert blocked.json()["agent"] == "communication"


def test_pending_cancel_updates_persisted_turn():
    store = FakeConversationStore()
    _authenticated(store, _shared(["communication"], communication=True))
    conversation = client.post("/conversations", json={}).json()
    request = {"conversation_id": conversation["id"], "message": "Send a Slack message"}
    client.post("/chat", json=request)
    client.post("/pending/cancel", json={"conversation_id": conversation["id"], "agent": "communication"})
    detail = client.get(f"/conversations/{conversation['id']}").json()
    assert detail["turns"][0]["results"]["communication"]["content"].startswith("Cancelled")


def test_pending_revision_remains_persisted_after_orchestrator_is_rebuilt():
    store = FakeConversationStore()
    _authenticated(store, _shared(["communication"], communication=True))
    conversation = client.post("/conversations", json={}).json()
    request = {"conversation_id": conversation["id"], "message": "Send a Slack message"}
    client.post("/chat", json=request)
    revised = client.post(
        "/pending/revise",
        json={
            "conversation_id": conversation["id"],
            "agent": "communication",
            "edit_instructions": "Make it shorter",
        },
    )
    assert revised.status_code == 200
    assert revised.json()["requires_confirmation"] is True
    assert (awaitable_pending := store.pending[UUID(conversation["id"])]).status == "pending"
    assert awaitable_pending.payload["description"]
