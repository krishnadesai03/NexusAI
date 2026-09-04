"""Live smoke test for PerformanceAgent against real Jira/Confluence (via Atlassian's Remote
MCP Server — learnings.md #4/#12 follow-up), real Bitbucket (still direct REST — not exposed via
MCP yet), and the real OpenAI API. Not part of the automated test suite (tests/ only ever uses
fakes).

Usage: .venv/Scripts/python.exe scripts/smoke_test_performance_agent.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

STATE_FILE = ROOT / "scripts" / "_performance_seed_state.json"


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

    if not STATE_FILE.exists():
        raise SystemExit(f"{STATE_FILE} not found — run the seeding scripts first.")

    from enterprise_ai.agents.performance.agent import PerformanceAgent
    from enterprise_ai.core.llm_client import OpenAILLMClient
    from enterprise_ai.integrations.atlassian.bitbucket_client import BitbucketClient
    from enterprise_ai.integrations.atlassian.mcp_client import (
        AtlassianMCPSession,
        ConfluenceMCPClient,
        JiraMCPClient,
    )

    sprint_calendar = json.loads(STATE_FILE.read_text())["sprints"]

    mcp_session = await AtlassianMCPSession.connect()
    agent = PerformanceAgent(
        llm_client=OpenAILLMClient(),
        jira_client=JiraMCPClient(mcp_session),
        confluence_client=ConfluenceMCPClient(mcp_session),
        bitbucket_client=BitbucketClient(),
        sprint_calendar=sprint_calendar,
    )

    questions = [
        "How many tickets did Priya Nair complete in sprint 1?",
        "Did anyone have an unusually quiet sprint, and if so what happened?",
    ]

    try:
        for q in questions:
            print(f"Q: {q}")
            result = await agent.handle(q)
            print(f"A: {result.content}")
            print(f"citations ({len(result.metadata['citations'])}): {result.metadata['citations'][:10]}")
            print()
    finally:
        await mcp_session.close()


if __name__ == "__main__":
    asyncio.run(main())
