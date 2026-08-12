"""Unit tests for the web API (learnings.md #9), using FastAPI's TestClient with fakes — same
"no network calls, no real Postgres/OpenAI" convention as every other agent's test suite.

get_shared_resources/get_session_store are Depends()-injected (api/dependencies.py) specifically
so they can be swapped via app.dependency_overrides here without running the real lifespan (which
would otherwise try to open a real Postgres/pgvector connection). /chat and /pending tests build
their session directly via SessionStore.create() with a hand-built Orchestrator, bypassing login,
since those routes only care about an already-authenticated session — login itself (the
bcrypt-check + build_session_orchestrator wiring) is covered separately below.
"""

from __future__ import annotations

import json

import bcrypt
import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_session_store, get_shared_resources
from api.main import app
from api.sessions import SessionStore
from enterprise_ai.bootstrap import SharedResources
from enterprise_ai.core.agent import AgentResult
from enterprise_ai.orchestrator.orchestrator import Orchestrator
from enterprise_ai.orchestrator.router import Router
from enterprise_ai.orchestrator.schemas import RoutingDecision

client = TestClient(app)  # no `with` — lifespan never runs, so no real DB/API connections needed


@pytest.fixture(autouse=True)
def _reset_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


class FakeLLMClient:
    def __init__(self, decision: RoutingDecision):
        self._decision = decision

    async def get_structured_output(self, *, system_prompt, user_prompt, schema):
        return self._decision


class FakeAgent:
    def __init__(self, name: str):
        self._name = name

    async def handle(self, user_request: str, history: list[dict] | None = None) -> AgentResult:
        return AgentResult(agent_name=self._name, content=f"{self._name} handled it")


class FakeConfirmableAgent:
    """Stands in for CommunicationAgent — implements ConfirmableAgent without needing real
    Slack/email clients."""

    def __init__(self):
        self._pending = False

    async def handle(self, user_request: str, history: list[dict] | None = None) -> AgentResult:
        self._pending = True
        return AgentResult(
            agent_name="communication",
            content="Draft ready: a message.",
            metadata={"citations": [], "requires_confirmation": True},
        )

    def has_pending(self) -> bool:
        return self._pending

    async def confirm_pending(self) -> AgentResult:
        self._pending = False
        return AgentResult(
            agent_name="communication",
            content="Done — sent as confirmed.",
            metadata={"citations": ["send_slack_message: ok"]},
        )

    def cancel_pending(self) -> AgentResult:
        self._pending = False
        return AgentResult(agent_name="communication", content="Cancelled — nothing was sent.")

    async def revise_pending(self, edit_instructions: str) -> AgentResult:
        return AgentResult(
            agent_name="communication",
            content=f"Draft ready: revised ({edit_instructions}).",
            metadata={"citations": [], "requires_confirmation": True},
        )


def _fake_shared(*, communication_configured: bool = False) -> SharedResources:
    decision = RoutingDecision(agents=["knowledge"], reasoning="test")
    return SharedResources(
        router=Router(FakeLLMClient(decision)),
        knowledge_agent=FakeAgent("knowledge"),
        performance_agent=FakeAgent("performance"),
        database_agent=FakeAgent("database"),
        vector_store=None,
        db_query_client=None,
        llm_client=FakeLLMClient(decision),
        communication_clients=(None, None, None) if communication_configured else None,
    )


def _session_with_agents(agents: dict) -> tuple[SessionStore, str]:
    store = SessionStore()
    # The routing decision only matters for the one test that actually calls /chat with a
    # non-empty agents dict — pick an arbitrary registered name so RoutingDecision's non-empty
    # constraint is satisfied either way.
    placeholder_decision = RoutingDecision(agents=[next(iter(agents), "knowledge")], reasoning="n/a")
    orchestrator = Orchestrator(router=Router(FakeLLMClient(placeholder_decision)), agents=agents)
    session = store.create(email="priya@company.example", display_name="Priya Nair", orchestrator=orchestrator)
    return store, session.token


# ---- auth -------------------------------------------------------------------------------------


def test_login_succeeds_with_correct_credentials(monkeypatch):
    password_hash = bcrypt.hashpw(b"correct-horse", bcrypt.gensalt()).decode("utf-8")
    monkeypatch.setenv(
        "APP_USERS_JSON",
        json.dumps([{"email": "priya@company.example", "password_hash": password_hash, "display_name": "Priya Nair"}]),
    )
    app.dependency_overrides[get_shared_resources] = _fake_shared
    app.dependency_overrides[get_session_store] = SessionStore

    response = client.post("/auth/login", json={"email": "priya@company.example", "password": "correct-horse"})

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Priya Nair"
    assert body["token"]


def test_login_rejects_wrong_password(monkeypatch):
    password_hash = bcrypt.hashpw(b"correct-horse", bcrypt.gensalt()).decode("utf-8")
    monkeypatch.setenv(
        "APP_USERS_JSON",
        json.dumps([{"email": "priya@company.example", "password_hash": password_hash, "display_name": "Priya Nair"}]),
    )
    app.dependency_overrides[get_shared_resources] = _fake_shared
    app.dependency_overrides[get_session_store] = SessionStore

    response = client.post("/auth/login", json={"email": "priya@company.example", "password": "wrong"})

    assert response.status_code == 401
    assert response.json() == {"error": "Invalid email or password."}


def test_login_rejects_unknown_email(monkeypatch):
    monkeypatch.setenv("APP_USERS_JSON", "[]")
    app.dependency_overrides[get_shared_resources] = _fake_shared
    app.dependency_overrides[get_session_store] = SessionStore

    response = client.post("/auth/login", json={"email": "nobody@company.example", "password": "anything"})

    assert response.status_code == 401


def test_me_requires_a_token():
    app.dependency_overrides[get_session_store] = SessionStore

    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_rejects_unknown_token():
    store = SessionStore()
    app.dependency_overrides[get_session_store] = lambda: store

    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401


def test_logout_invalidates_the_token():
    store, token = _session_with_agents({"knowledge": FakeAgent("knowledge")})
    app.dependency_overrides[get_session_store] = lambda: store

    logout_response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_response.status_code == 204

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 401


# ---- chat ---------------------------------------------------------------------------------------


def test_chat_routes_and_returns_expected_shape():
    store, token = _session_with_agents({"knowledge": FakeAgent("knowledge")})
    app.dependency_overrides[get_session_store] = lambda: store

    response = client.post(
        "/chat", json={"message": "What's our PTO policy?"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    # this test only verifies the HTTP wiring and response shape, not routing logic itself
    # (Orchestrator's own test suite covers that) — the fake router always picks "knowledge" here.
    assert body == {
        "routed_to": ["knowledge"],
        "results": {"knowledge": {"content": "knowledge handled it", "citations": [], "requires_confirmation": False}},
    }


def test_chat_rejects_empty_message():
    store, token = _session_with_agents({"knowledge": FakeAgent("knowledge")})
    app.dependency_overrides[get_session_store] = lambda: store

    response = client.post("/chat", json={"message": "   "}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 400


def test_chat_requires_auth():
    app.dependency_overrides[get_session_store] = SessionStore

    response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 401


def test_chat_returns_409_when_a_confirmation_is_already_pending():
    confirmable = FakeConfirmableAgent()
    store, token = _session_with_agents({"communication": confirmable})
    app.dependency_overrides[get_session_store] = lambda: store
    confirmable._pending = True  # simulate an unresolved staged draft from a prior /chat call

    response = client.post(
        "/chat", json={"message": "send another message"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["agent"] == "communication"


# ---- pending ------------------------------------------------------------------------------------


def test_pending_confirm_executes_and_returns_result():
    confirmable = FakeConfirmableAgent()
    store, token = _session_with_agents({"communication": confirmable})
    app.dependency_overrides[get_session_store] = lambda: store
    confirmable._pending = True

    response = client.post(
        "/pending/confirm", json={"agent": "communication"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "Done — sent as confirmed."
    assert body["requires_confirmation"] is False
    assert confirmable.has_pending() is False


def test_pending_cancel_clears_the_draft():
    confirmable = FakeConfirmableAgent()
    store, token = _session_with_agents({"communication": confirmable})
    app.dependency_overrides[get_session_store] = lambda: store
    confirmable._pending = True

    response = client.post(
        "/pending/cancel", json={"agent": "communication"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Cancelled — nothing was sent."
    assert confirmable.has_pending() is False


def test_pending_revise_stages_a_new_draft():
    confirmable = FakeConfirmableAgent()
    store, token = _session_with_agents({"communication": confirmable})
    app.dependency_overrides[get_session_store] = lambda: store
    confirmable._pending = True

    response = client.post(
        "/pending/revise",
        json={"agent": "communication", "edit_instructions": "make it shorter"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "make it shorter" in body["content"]
    assert body["requires_confirmation"] is True


def test_pending_rejects_unknown_agent_name():
    store, token = _session_with_agents({"knowledge": FakeAgent("knowledge")})
    app.dependency_overrides[get_session_store] = lambda: store

    response = client.post(
        "/pending/confirm", json={"agent": "not-a-real-agent"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


def test_pending_rejects_a_non_confirmable_agent():
    store, token = _session_with_agents({"knowledge": FakeAgent("knowledge")})
    app.dependency_overrides[get_session_store] = lambda: store

    response = client.post(
        "/pending/confirm", json={"agent": "knowledge"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 400
