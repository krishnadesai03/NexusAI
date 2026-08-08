"""One-off smoke test for the real OpenAI API path — not part of the automated
test suite (tests/ only ever uses fakes). Confirms Router + OpenAILLMClient
actually produce a valid, schema-conformant routing decision against a live
model before anything else gets built on top of that assumption.

Usage: copy .env.example to .env, fill in OPENAI_API_KEY, then run
    .venv/Scripts/python.exe scripts/smoke_test_llm.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


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
    _load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill in your key.")

    from enterprise_ai.core.llm_client import OpenAILLMClient
    from enterprise_ai.orchestrator.router import Router

    router = Router(OpenAILLMClient())

    single = await router.route("What's our company's PTO policy?")
    print("Single-agent request:")
    print(f"  agents:    {single.agents}")
    print(f"  reasoning: {single.reasoning}")

    multi = await router.route("Compare last sprint's velocity to what the internal docs promised.")
    print("Multi-agent request:")
    print(f"  agents:    {multi.agents}")
    print(f"  reasoning: {multi.reasoning}")

    print("\nLive call succeeded on both requests.")


if __name__ == "__main__":
    asyncio.run(main())
