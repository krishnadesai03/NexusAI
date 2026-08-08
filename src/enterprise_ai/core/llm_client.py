from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResponse:
    """One turn of a tool-calling loop: either a final answer (content set, no tool_calls)
    or a request to execute tools (tool_calls set, content usually None). The caller owns
    the conversation/message-history state across turns — this stays a thin, stateless
    per-call adapter, consistent with get_structured_output."""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    """Abstract seam between orchestrator/agents and any specific LLM vendor SDK
    (ports-and-adapters, see learnings.md #0.5). Nothing outside this file and its
    concrete implementations should import a vendor SDK directly."""

    async def get_structured_output(
        self, *, system_prompt: str, user_prompt: str, schema: type[SchemaT]
    ) -> SchemaT: ...

    async def get_tool_response(self, *, messages: list[dict], tools: list[dict]) -> ToolResponse:
        """Multi-turn tool-calling, used by agents whose questions need several data lookups
        (e.g. PerformanceAgent) rather than a single retrieve-then-generate pass. `messages`
        and `tools` use the OpenAI chat-completions shape directly — this project has only one
        LLM adapter (see learnings.md #1), so there's no abstraction cost to that today."""
        ...


class OpenAILLMClient:
    """Concrete LLMClient backed by OpenAI's Structured Outputs: the SDK validates the model's
    response against `schema` before handing back a parsed object, so a malformed response never
    silently passes — the hard schema guardrail from learnings.md #1. OpenAI is the only adapter
    implemented (this project has OpenAI credits, never Anthropic ones — see
    learnings.md #1's note); `LLMClient` stays a Protocol so a different adapter could be added
    later without touching any calling code."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4.1-mini") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self._model = model

    async def get_structured_output(
        self, *, system_prompt: str, user_prompt: str, schema: type[SchemaT]
    ) -> SchemaT:
        completion = await self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=schema,
        )

        message = completion.choices[0].message
        if message.refusal:
            raise ValueError(f"Model refused to produce structured output: {message.refusal}")
        if message.parsed is None:
            raise ValueError("Model response did not parse against the required schema")

        return message.parsed

    async def get_tool_response(self, *, messages: list[dict], tools: list[dict]) -> ToolResponse:
        import json

        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
        )
        message = completion.choices[0].message

        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments))
            for tc in (message.tool_calls or [])
        ]
        return ToolResponse(content=message.content, tool_calls=tool_calls)


def default_llm_client() -> LLMClient:
    """The LLMClient to use for real (non-test) calls in this environment."""

    return OpenAILLMClient()
