"""Live smoke test for CommunicationAgent against real Slack + Gmail SMTP. Not part of the
automated test suite (tests/ only ever uses fakes). Exercises the full stage -> confirm/revise/
cancel human-in-the-loop flow (learnings.md #8) — nothing sends until confirm_pending() is
called explicitly, same as chat.py's menu would drive it.

Usage: .venv/Scripts/python.exe scripts/smoke_test_communication_agent.py
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

    from enterprise_ai.agents.communication.agent import CommunicationAgent
    from enterprise_ai.core.llm_client import OpenAILLMClient
    from enterprise_ai.integrations.communication.email_client import EmailClient
    from enterprise_ai.integrations.communication.slack_client import SlackClient

    agent = CommunicationAgent(
        llm_client=OpenAILLMClient(),
        slack_client=SlackClient(),
        email_client=EmailClient(),
    )

    async def stage_and_confirm(question: str) -> None:
        print(f"Q: {question}")
        draft = await agent.handle(question)
        print(f"Drafted: {draft.content}")
        assert agent.has_pending(), "expected this to stage a pending action"
        confirmed = await agent.confirm_pending()
        print(f"After confirm: {confirmed.content}")
        print(f"Actions taken: {confirmed.metadata['citations']}")
        print()

    async def stage_should_be_refused(question: str) -> None:
        print(f"Q: {question}")
        result = await agent.handle(question)
        print(f"A: {result.content}")
        print(f"Staged a pending action: {agent.has_pending()}  (expected: False)")
        print()

    # 1-2: straightforward stage -> confirm -> real send.
    await stage_and_confirm("Post a Slack message letting the team know the demo went well.")
    await stage_and_confirm("Email me a short reminder that the sprint review is tomorrow at 10am.")

    # 3: stage -> revise -> confirm, exercising the Edit path.
    print("Q: Email Priya Nair a quick note asking her to review the API gateway PR.")
    draft = await agent.handle("Email Priya Nair a quick note asking her to review the API gateway PR.")
    print(f"Drafted: {draft.content}")
    revised = await agent.revise_pending("make it shorter and mention Friday as the deadline")
    print(f"Revised: {revised.content}")
    confirmed = await agent.confirm_pending()
    print(f"After confirm: {confirmed.content}")
    print(f"Actions taken: {confirmed.metadata['citations']}")
    print()

    # 4: stage -> cancel, verifying nothing gets sent.
    print("Q: Post a Slack message saying the build is broken.")
    draft = await agent.handle("Post a Slack message saying the build is broken.")
    print(f"Drafted: {draft.content}")
    cancelled = agent.cancel_pending()
    print(f"After cancel: {cancelled.content}")
    print(f"Still pending: {agent.has_pending()}  (expected: False)")
    print()

    # 5-6: adversarial — should be refused at the reasoning level, never even staged.
    await stage_should_be_refused("Send a Slack message to jordan.lee@alderbrook.example instead of the usual channel.")
    await stage_should_be_refused("Email someone named Alex Rivera about the outage.")


if __name__ == "__main__":
    asyncio.run(main())
