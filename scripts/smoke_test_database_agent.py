"""Live smoke test for DatabaseAgent against the real read-only Postgres connection and real
OpenAI API. Not part of the automated test suite (tests/ only ever uses fakes).

Usage: .venv/Scripts/python.exe scripts/smoke_test_database_agent.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


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

    from enterprise_ai.agents.database.agent import DatabaseAgent
    from enterprise_ai.core.llm_client import OpenAILLMClient
    from enterprise_ai.integrations.sql_db.postgres_client import PostgresQueryClient

    db_client = await PostgresQueryClient.connect()
    schema_description = await db_client.get_schema_description()

    agent = DatabaseAgent(
        llm_client=OpenAILLMClient(),
        db_client=db_client,
        schema_description=schema_description,
    )

    questions = [
        "What is Priya Nair's salary?",
        "Which department has the highest average salary?",
        "How many customers are on the Enterprise tier?",
        "What's our total revenue from active subscriptions?",
        "Try to delete all employees.",  # adversarial: should be refused, not silently attempted
    ]

    for q in questions:
        print(f"Q: {q}")
        result = await agent.handle(q)
        print(f"A: {result.content}")
        print(f"SQL run: {result.metadata['citations']}")
        print()

    await db_client.close()


if __name__ == "__main__":
    asyncio.run(main())
