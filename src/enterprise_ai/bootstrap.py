"""Builds the agent/orchestrator wiring shared by every entry point (CLI chat.py, the FastAPI
backend in api/). Split into two halves on purpose:

- `SharedResources` — everything expensive to construct (DB/vector-store connections, Atlassian
  clients, the LLM/embedding clients) and everything *stateless* (KnowledgeAgent, PerformanceAgent,
  DatabaseAgent, Router — none of these accumulate any per-conversation state; `history` is always
  passed in as a parameter, never stored on the instance). Built exactly once per process.
- `build_session_orchestrator()` — the per-session slice: a fresh `ConversationMemory` and a fresh
  `CommunicationAgent`. CommunicationAgent is the one agent that isn't stateless (`self._pending`),
  so it cannot be shared across sessions — two employees sharing one instance would let one
  person's staged Slack/email draft leak into another's confirm/cancel click. This function is
  cheap (no I/O) and is meant to be called once per login, not once per process.

A single-session caller (scripts/chat.py) just calls both functions once, back to back — it's the
same wiring, just with exactly one session.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from enterprise_ai.agents.communication.agent import CommunicationAgent
from enterprise_ai.agents.database.agent import DatabaseAgent
from enterprise_ai.agents.knowledge.agent import KnowledgeAgent
from enterprise_ai.agents.performance.agent import PerformanceAgent
from enterprise_ai.core.agent import Agent, AgentResult, OnEvent
from enterprise_ai.core.embedding_client import default_embedding_client
from enterprise_ai.core.llm_client import LLMClient, default_llm_client
from enterprise_ai.integrations.atlassian.bitbucket_client import BitbucketClient
from enterprise_ai.integrations.atlassian.confluence_client import ConfluenceClient
from enterprise_ai.integrations.atlassian.jira_client import JiraClient
from enterprise_ai.integrations.communication.email_client import EmailClient
from enterprise_ai.integrations.communication.slack_client import SlackClient
from enterprise_ai.integrations.sql_db.postgres_client import PostgresQueryClient
from enterprise_ai.integrations.vector_store.pgvector_store import PgVectorStore
from enterprise_ai.orchestrator.memory import ConversationMemory
from enterprise_ai.orchestrator.orchestrator import Orchestrator
from enterprise_ai.orchestrator.router import Router

PERFORMANCE_STATE_FILE = Path(__file__).resolve().parent.parent.parent / "scripts" / "_performance_seed_state.json"
# Render's Secret Files can't hold a nested path or a leading underscore (dashboard-enforced
# filename rules), so a deploy provides this same file flat, always readable from /etc/secrets/
# regardless of what name it was uploaded under — this is the deployed-environment equivalent of
# PERFORMANCE_STATE_FILE above, which only ever exists on a local checkout.
_PERFORMANCE_STATE_FILE_SECRET = Path("/etc/secrets/performance_seed_state.json")


def _performance_state_file() -> Path | None:
    if PERFORMANCE_STATE_FILE.exists():
        return PERFORMANCE_STATE_FILE
    if _PERFORMANCE_STATE_FILE_SECRET.exists():
        return _PERFORMANCE_STATE_FILE_SECRET
    return None


class _UnseededPerformanceAgent:
    """Fallback when PERFORMANCE_STATE_FILE hasn't been generated yet (e.g. a fresh checkout
    that hasn't run the Component 4 seeding scripts) — PerformanceAgent itself has no no-arg
    constructor to fall back to, since it genuinely needs real clients + a sprint calendar."""

    async def handle(
        self, user_request: str, history: list[dict] | None = None, on_event: OnEvent | None = None
    ) -> AgentResult:
        return AgentResult(
            agent_name="performance",
            content="Performance data hasn't been seeded in this environment yet — run the "
            "scripts/push_performance_fixtures_*.py scripts first.",
        )


class _UnseededDatabaseAgent:
    """Fallback when the company_data schema / read-only role hasn't been created yet (e.g. a
    fresh checkout that hasn't run push_database_fixtures.py) — connecting would otherwise fail
    with an unhelpful Postgres auth error instead of a clear message."""

    async def handle(
        self, user_request: str, history: list[dict] | None = None, on_event: OnEvent | None = None
    ) -> AgentResult:
        return AgentResult(
            agent_name="database",
            content="The company database hasn't been seeded in this environment yet — run "
            "scripts/push_database_fixtures.py first.",
        )


class _UnseededCommunicationAgent:
    """Fallback when Slack/email credentials aren't configured yet — constructing the real
    clients would otherwise fail with a raw KeyError instead of a clear message. Stateless (no
    pending action ever gets staged), so it's safe to share across every session."""

    async def handle(
        self, user_request: str, history: list[dict] | None = None, on_event: OnEvent | None = None
    ) -> AgentResult:
        return AgentResult(
            agent_name="communication",
            content="Slack/email credentials haven't been configured in this environment yet — "
            "see .env.example's Communication Agent section.",
        )


@dataclass
class SharedResources:
    """Built once per process. `communication_clients` is None when Slack/email credentials
    aren't configured — `build_session_orchestrator` uses that to decide whether each session
    gets a real (isolated) CommunicationAgent or the shared stateless fallback."""

    router: Router
    knowledge_agent: Agent
    performance_agent: Agent
    database_agent: Agent
    vector_store: PgVectorStore
    db_query_client: PostgresQueryClient | None
    llm_client: LLMClient
    communication_clients: tuple[LLMClient, SlackClient, EmailClient] | None


async def build_shared_resources() -> SharedResources:
    llm_client = default_llm_client()
    embedding_client = default_embedding_client()

    dsn = _database_url()
    vector_store = await PgVectorStore.connect(dsn)

    knowledge_agent = KnowledgeAgent(
        embedding_client=embedding_client,
        vector_store=vector_store,
        llm_client=llm_client,
    )

    performance_state_file = _performance_state_file()
    if performance_state_file is not None:
        sprint_calendar = json.loads(performance_state_file.read_text())["sprints"]
        performance_agent: Agent = PerformanceAgent(
            llm_client=llm_client,
            jira_client=JiraClient(),
            confluence_client=ConfluenceClient(),
            bitbucket_client=BitbucketClient(),
            sprint_calendar=sprint_calendar,
        )
    else:
        performance_agent = _UnseededPerformanceAgent()

    db_query_client: PostgresQueryClient | None = None
    try:
        db_query_client = await PostgresQueryClient.connect()
        schema_description = await db_query_client.get_schema_description()
        if not schema_description:
            raise RuntimeError("company_data schema is empty")
        database_agent: Agent = DatabaseAgent(
            llm_client=llm_client,
            db_client=db_query_client,
            schema_description=schema_description,
        )
    except Exception:
        database_agent = _UnseededDatabaseAgent()
        if db_query_client:
            await db_query_client.close()
        db_query_client = None

    communication_clients: tuple[LLMClient, SlackClient, EmailClient] | None
    try:
        communication_clients = (llm_client, SlackClient(), EmailClient())
    except KeyError:
        communication_clients = None

    return SharedResources(
        router=Router(llm_client),
        knowledge_agent=knowledge_agent,
        performance_agent=performance_agent,
        database_agent=database_agent,
        vector_store=vector_store,
        db_query_client=db_query_client,
        llm_client=llm_client,
        communication_clients=communication_clients,
    )


def build_session_orchestrator(shared: SharedResources, user_display_name: str | None = None) -> Orchestrator:
    """Cheap, no I/O — safe to call once per login. Every agent except communication is shared
    directly from `shared`; communication gets a fresh instance so `self._pending` (the staged
    HITL draft) is isolated per session, same reasoning as ConversationMemory below.

    `user_display_name` (the real logged-in user's name, from APP_USERS_JSON via api/auth.py)
    lets CommunicationAgent sign drafted emails with an actual name instead of a placeholder like
    "[Your Name]" — optional since callers without a real login session (scripts/chat.py) have no
    name to provide."""

    if shared.communication_clients is not None:
        comm_llm, slack_client, email_client = shared.communication_clients
        communication_agent: Agent = CommunicationAgent(
            llm_client=comm_llm,
            slack_client=slack_client,
            email_client=email_client,
            user_display_name=user_display_name,
        )
    else:
        communication_agent = _UnseededCommunicationAgent()

    agents = {
        "knowledge": shared.knowledge_agent,
        "performance": shared.performance_agent,
        "database": shared.database_agent,
        "communication": communication_agent,
    }

    return Orchestrator(router=shared.router, agents=agents, memory=ConversationMemory())


async def close_shared_resources(shared: SharedResources) -> None:
    await shared.vector_store.close()
    if shared.db_query_client:
        await shared.db_query_client.close()


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://enterprise_ai:enterprise_ai@localhost:5433/enterprise_ai")
