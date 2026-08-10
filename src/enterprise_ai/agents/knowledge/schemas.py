from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeAnswer(BaseModel):
    """Forced structured output for the Knowledge Agent's generation step (learnings.md #3,
    decision 6) — reuses Component 1's hard-schema-guardrail mechanism, extended here to also
    guard against ungroundedness: answer_found lets the model honestly say "not found" instead
    of being forced into a confident-sounding answer when the retrieved context doesn't help."""

    answer: str = Field(
        description="The answer to the user's question, using only the provided context. If "
        "the context doesn't contain enough information, briefly say so here instead of guessing."
    )
    citations: list[str] = Field(
        default_factory=list,
        description="doc_ids of the context chunks actually used to produce the answer.",
    )
    answer_found: bool = Field(
        description="Whether the provided context actually contained enough information to answer the question."
    )
