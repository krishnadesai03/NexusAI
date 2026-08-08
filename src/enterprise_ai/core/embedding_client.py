from __future__ import annotations

import os
from typing import Protocol


class EmbeddingClient(Protocol):
    """Abstract seam between agents and any specific embedding-model vendor SDK — a separate
    Protocol from LLMClient (learnings.md #3, decision 1) since embedding and chat completion
    are different capabilities, often backed by different models even within one provider."""

    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbeddingClient:
    """Concrete EmbeddingClient backed by OpenAI's embeddings API. text-embedding-3-small is the
    default model (learnings.md #3, decision 2): cheap and sufficient for this project's corpus
    size, consistent with OpenAI already being the default LLM provider here."""

    def __init__(self, api_key: str | None = None, model: str = "text-embedding-3-small") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(model=self._model, input=text)
        return response.data[0].embedding


def default_embedding_client() -> EmbeddingClient:
    """The EmbeddingClient to use for real (non-test) calls in this environment — see
    core/llm_client.py's default_llm_client() for the same reasoning (OpenAI credits, not
    Anthropic)."""

    return OpenAIEmbeddingClient()
