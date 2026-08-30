from __future__ import annotations

import json

_MISSING = object()


class ToolCache:
    """Session-scoped memoization of read-only tool calls (Jira/Confluence/Bitbucket search,
    SQL queries), keyed by tool name + exact arguments (Component 12). Lives exactly as long as
    one Orchestrator session (see bootstrap.build_session_orchestrator constructing a fresh
    instance per login) — no separate TTL on top of that, since a session is short-lived enough
    that a fresh cache per session already keeps staleness bounded, and this project's source
    data (fixture-seeded Jira/Confluence/Bitbucket/Postgres) barely changes minute-to-minute
    anyway.

    A hit means the same agent doesn't re-fetch data it already has within one conversation —
    e.g. asking "how many bugs did X resolve in sprint 12" and then "what were they about?" reuses
    the first call's search_jira_issues result instead of hitting Jira again, since
    ConversationMemory only carries forward the final answer text, not raw tool results."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def get(self, tool_name: str, arguments: dict) -> object:
        """Returns the cached value, or the sentinel `_MISSING` (importable as
        ToolCache.MISSING) if there is no entry — a plain `None` return would be ambiguous with
        a tool legitimately having cached a `None`/empty result."""
        return self._store.get(self._key(tool_name, arguments), _MISSING)

    def set(self, tool_name: str, arguments: dict, value: object) -> None:
        self._store[self._key(tool_name, arguments)] = value

    @staticmethod
    def _key(tool_name: str, arguments: dict) -> str:
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"

    MISSING = _MISSING
