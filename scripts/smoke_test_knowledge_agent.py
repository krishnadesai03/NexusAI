"""Live smoke test for the Knowledge Agent against the real OpenAI API and real pgvector
instance (learnings.md #3, decision 9). Not part of the automated test suite (tests/ only ever
uses fakes) — run scripts/seed_knowledge_fixtures.py first so there's something to retrieve.

Usage: .venv/Scripts/python.exe scripts/smoke_test_knowledge_agent.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def main() -> None:
    _load_dotenv(ROOT / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill in your key.")

    dsn = os.environ.get("DATABASE_URL", "postgresql://enterprise_ai:enterprise_ai@localhost:5432/enterprise_ai")

    from enterprise_ai.agents.knowledge.agent import KnowledgeAgent
    from enterprise_ai.core.embedding_client import OpenAIEmbeddingClient
    from enterprise_ai.core.llm_client import OpenAILLMClient
    from enterprise_ai.integrations.vector_store.pgvector_store import PgVectorStore

    store = await PgVectorStore.connect(dsn)
    agent = KnowledgeAgent(
        embedding_client=OpenAIEmbeddingClient(),
        vector_store=store,
        llm_client=OpenAILLMClient(),
    )

    queries = [
        ("How many PTO days do I get in the US?", "pto_policy_us.md"),
        ("How many casual leave days do I get in the India office?", "pto_policy_india.md"),
        ("What's the international travel per diem?", "travel_policy.md"),
        ("What's the weather like on Mars?", None),
    ]

    for question, expected_doc in queries:
        result = await agent.handle(question)
        print(f"Q: {question}")
        print(f"  answer:       {result.content}")
        print(f"  citations:    {result.metadata['citations']}")
        print(f"  answer_found: {result.metadata['answer_found']}")
        if expected_doc:
            hit = any(expected_doc in c for c in result.metadata["citations"])
            print(f"  expected '{expected_doc}' in citations: {'YES' if hit else 'NO (!!)'}")
        print()

    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
