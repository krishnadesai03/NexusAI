from __future__ import annotations

import asyncio

from enterprise_ai.core.llm_client import LLMClient, ToolResponse

# If an LLM call stalls (slow network, flaky API, etc.), each attempt gets more time than the
# last rather than retrying with a fixed timeout — 6s, then 12s, then 24s. After
# LLM_CALL_MAX_ATTEMPTS failures in a row, give up rather than retrying forever. Shared by every
# agent that runs a tool-calling loop (DatabaseAgent, PerformanceAgent) so the policy — and any
# future change to it — lives in exactly one place.
LLM_CALL_INITIAL_TIMEOUT_SECONDS = 6
LLM_CALL_MAX_ATTEMPTS = 3
LLM_CALL_BACKOFF_MULTIPLIER = 2


class LLMUnavailableError(Exception):
    """Raised after LLM_CALL_MAX_ATTEMPTS failed attempts to reach the LLM — callers catch this
    to return a clean user-facing message instead of letting the exception propagate."""


async def call_tool_with_retry(llm_client: LLMClient, messages: list[dict], tools: list[dict]) -> ToolResponse:
    timeout = LLM_CALL_INITIAL_TIMEOUT_SECONDS
    last_error: Exception | None = None
    for _ in range(LLM_CALL_MAX_ATTEMPTS):
        try:
            return await asyncio.wait_for(
                llm_client.get_tool_response(messages=messages, tools=tools), timeout=timeout
            )
        except Exception as exc:  # noqa: BLE001 — timeouts and network/API errors are treated
            # the same here: retry with more time, regardless of the specific cause.
            last_error = exc
            timeout *= LLM_CALL_BACKOFF_MULTIPLIER
    raise LLMUnavailableError from last_error
