"""Interactive CLI chat with the orchestrator — routes to the real Knowledge Agent and stubs
for the other three (performance, database, communication), same as everything built so far.

This is a manual testing tool, not part of the automated test suite. `build_orchestrator()` is
kept separate from the input/output loop so it can be reused later behind a real API (e.g.
FastAPI) instead of stdin/stdout, without rewriting the wiring logic.

Usage:
    docker compose up -d postgres
    .venv/Scripts/python.exe scripts/seed_knowledge_fixtures.py   # once, if not already seeded
    .venv/Scripts/python.exe scripts/chat.py
Type 'exit' or Ctrl+C to quit. Type '/citations' to toggle the metadata/citations line on or
off — a session-level display preference, not something inferred per-question, since guessing
"does this phrasing mean skip citations" from natural language would be fragile."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERFORMANCE_STATE_FILE = ROOT / "scripts" / "_performance_seed_state.json"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


class _UnseededPerformanceAgent:
    """Fallback when PERFORMANCE_STATE_FILE hasn't been generated yet (e.g. a fresh checkout
    that hasn't run the Component 4 seeding scripts) — PerformanceAgent itself has no no-arg
    constructor to fall back to, since it genuinely needs real clients + a sprint calendar."""

    async def handle(self, user_request: str):
        from enterprise_ai.core.agent import AgentResult

        return AgentResult(
            agent_name="performance",
            content="Performance data hasn't been seeded in this environment yet — run the "
            "scripts/push_performance_fixtures_*.py scripts first.",
        )


class _UnseededDatabaseAgent:
    """Fallback when the company_data schema / read-only role hasn't been created yet (e.g. a
    fresh checkout that hasn't run push_database_fixtures.py) — connecting would otherwise fail
    with an unhelpful Postgres auth error instead of a clear message."""

    async def handle(self, user_request: str):
        from enterprise_ai.core.agent import AgentResult

        return AgentResult(
            agent_name="database",
            content="The company database hasn't been seeded in this environment yet — run "
            "scripts/push_database_fixtures.py first.",
        )


async def build_orchestrator():
    from enterprise_ai.agents.communication.agent import CommunicationAgent
    from enterprise_ai.agents.database.agent import DatabaseAgent
    from enterprise_ai.agents.knowledge.agent import KnowledgeAgent
    from enterprise_ai.agents.performance.agent import PerformanceAgent
    from enterprise_ai.core.embedding_client import default_embedding_client
    from enterprise_ai.core.llm_client import default_llm_client
    from enterprise_ai.integrations.atlassian.bitbucket_client import BitbucketClient
    from enterprise_ai.integrations.atlassian.confluence_client import ConfluenceClient
    from enterprise_ai.integrations.atlassian.jira_client import JiraClient
    from enterprise_ai.integrations.sql_db.postgres_client import PostgresQueryClient
    from enterprise_ai.integrations.vector_store.pgvector_store import PgVectorStore
    from enterprise_ai.orchestrator.orchestrator import Orchestrator
    from enterprise_ai.orchestrator.router import Router

    dsn = os.environ.get("DATABASE_URL", "postgresql://enterprise_ai:enterprise_ai@localhost:5433/enterprise_ai")
    vector_store = await PgVectorStore.connect(dsn)

    if PERFORMANCE_STATE_FILE.exists():
        sprint_calendar = json.loads(PERFORMANCE_STATE_FILE.read_text())["sprints"]
        performance_agent = PerformanceAgent(
            llm_client=default_llm_client(),
            jira_client=JiraClient(),
            confluence_client=ConfluenceClient(),
            bitbucket_client=BitbucketClient(),
            sprint_calendar=sprint_calendar,
        )
    else:
        performance_agent = _UnseededPerformanceAgent()

    db_query_client = None
    try:
        db_query_client = await PostgresQueryClient.connect()
        schema_description = await db_query_client.get_schema_description()
        if not schema_description:
            raise RuntimeError("company_data schema is empty")
        database_agent = DatabaseAgent(
            llm_client=default_llm_client(),
            db_client=db_query_client,
            schema_description=schema_description,
        )
    except Exception:
        database_agent = _UnseededDatabaseAgent()
        if db_query_client:
            await db_query_client.close()
        db_query_client = None

    agents = {
        "knowledge": KnowledgeAgent(
            embedding_client=default_embedding_client(),
            vector_store=vector_store,
            llm_client=default_llm_client(),
        ),
        "performance": performance_agent,
        "database": database_agent,
        "communication": CommunicationAgent(),
    }

    orchestrator = Orchestrator(router=Router(default_llm_client()), agents=agents)
    return orchestrator, vector_store, db_query_client


async def main() -> None:
    _load_dotenv(ROOT / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill in your key.")

    orchestrator, vector_store, db_query_client = await build_orchestrator()
    show_citations = False
    print("Enterprise AI Assistant — type a question ('exit' or Ctrl+C to quit, '/citations' to toggle metadata)\n")

    try:
        while True:
            try:
                user_input = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break
            if user_input.lower() == "/citations":
                show_citations = not show_citations
                print(f"  citations display: {'on' if show_citations else 'off'}\n")
                continue

            result = await orchestrator.handle(user_input)
            print(f"  [routed to: {', '.join(result.routed_to)}]")
            for agent_name, agent_result in result.results.items():
                print(f"\n{agent_name}: {agent_result.content}")
                if show_citations and agent_result.metadata:
                    print(f"  metadata: {agent_result.metadata}")
            print()
    finally:
        await vector_store.close()
        if db_query_client:
            await db_query_client.close()
        print("\nGoodbye.")


if __name__ == "__main__":
    asyncio.run(main())
