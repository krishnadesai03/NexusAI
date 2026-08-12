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


async def build_orchestrator():
    """Thin wrapper around enterprise_ai.bootstrap — chat.py is a single-session CLI, so it just
    builds the shared resources and one session's worth of agents/memory back to back. The same
    two functions back api/'s multi-session backend, which calls build_session_orchestrator()
    once per login instead of once per process."""
    from enterprise_ai.bootstrap import build_session_orchestrator, build_shared_resources

    shared = await build_shared_resources()
    orchestrator = build_session_orchestrator(shared)
    return orchestrator, shared


async def _drive_confirmation_menu(orchestrator, agent_name: str, agent_result) -> None:
    """Drives the Send it / Edit / Cancel menu for a ConfirmableAgent's staged action
    (learnings.md #8). Deterministic, local, no LLM call for Send/Cancel — only Edit re-invokes
    the LLM (to redraft), which may stage another round requiring this same menu again."""
    from enterprise_ai.core.agent import ConfirmableAgent

    agent = orchestrator.get_agent(agent_name)
    if not isinstance(agent, ConfirmableAgent):
        return  # shouldn't happen — requires_confirmation only ever comes from a ConfirmableAgent

    while agent_result.metadata and agent_result.metadata.get("requires_confirmation"):
        print(f"\n{agent_name}: {agent_result.content}")
        choice = input("  [1] Send it   [2] Edit   [3] Cancel\n  > ").strip().lower()

        if choice in {"1", "send", "send it"}:
            agent_result = await agent.confirm_pending()
            print(f"\n{agent_name}: {agent_result.content}")
            return
        if choice in {"3", "cancel"}:
            agent_result = agent.cancel_pending()
            print(f"\n{agent_name}: {agent_result.content}")
            return
        if choice in {"2", "edit"}:
            edit_text = input("  Type your revision: ").strip()
            agent_result = await agent.revise_pending(edit_text)
            continue
        print("  Please choose 1, 2, or 3.")


async def main() -> None:
    _load_dotenv(ROOT / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill in your key.")

    orchestrator, shared = await build_orchestrator()
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
                if agent_result.metadata and agent_result.metadata.get("requires_confirmation"):
                    await _drive_confirmation_menu(orchestrator, agent_name, agent_result)
                    continue
                print(f"\n{agent_name}: {agent_result.content}")
                if show_citations and agent_result.metadata:
                    print(f"  metadata: {agent_result.metadata}")
            print()
    finally:
        from enterprise_ai.bootstrap import close_shared_resources

        await close_shared_resources(shared)
        print("\nGoodbye.")


if __name__ == "__main__":
    asyncio.run(main())
