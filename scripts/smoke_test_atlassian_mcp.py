"""Connectivity check for Atlassian's official Remote MCP Server (Component 4) — confirms
the API-token auth mechanics work and lists available tools (including checking whether
Bitbucket tools are actually enabled, since Atlassian requires an org admin to turn those on
separately). Read-only: lists tools, does not call any of them.

Usage: .venv/Scripts/python.exe scripts/smoke_test_atlassian_mcp.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent
MCP_URL = "https://mcp.atlassian.com/v1/mcp"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def _try_connect(label: str, http_client: httpx2.AsyncClient) -> bool:
    print(f"--- Trying: {label} ---")
    try:
        async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"SUCCESS. {len(tools.tools)} tool(s) available:")
                bitbucket_tools = []
                for t in tools.tools:
                    print(f"  {t.name}")
                    if "bitbucket" in t.name.lower():
                        bitbucket_tools.append(t.name)
                print(f"\nBitbucket-related tools found: {len(bitbucket_tools)}")
                if not bitbucket_tools:
                    print("  (none — may need an org admin to enable Bitbucket Cloud tools for MCP)")
                return True
    except Exception as exc:  # noqa: BLE001 — this is a diagnostic script, report and move to next candidate
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return False


async def main() -> None:
    _load_dotenv(ROOT / ".env")

    email = os.environ["ATLASSIAN_EMAIL"]
    token = os.environ["ATLASSIAN_API_TOKEN"]

    candidates = [
        ("Bearer token", httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)),
        ("Basic auth (email:token)", httpx2.AsyncClient(auth=(email, token), timeout=30)),
    ]

    for label, client in candidates:
        async with client:
            if await _try_connect(label, client):
                return

    print("\nAll auth methods failed — see errors above.")


if __name__ == "__main__":
    asyncio.run(main())
