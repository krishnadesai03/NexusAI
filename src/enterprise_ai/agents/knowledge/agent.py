from __future__ import annotations

from enterprise_ai.agents.knowledge.schemas import KnowledgeAnswer
from enterprise_ai.core.agent import AgentResult, OnEvent, emit_event
from enterprise_ai.core.embedding_client import EmbeddingClient
from enterprise_ai.core.llm_client import LLMClient
from enterprise_ai.core.tool_cache import ToolCache
from enterprise_ai.integrations.vector_store.pgvector_store import VectorStore

_SYSTEM_PROMPT = """You are the Knowledge Agent of an internal company assistant. Answer the
user's question using ONLY the provided context below — do not use outside knowledge.

Read every context chunk carefully before answering, even ones that don't look directly on topic
at first glance — company policies often split one subject across multiple documents, with a
specific rule in one place and a general default elsewhere. Pay close attention to qualifying or
exclusionary phrases (e.g. "not otherwise covered by...", "except...", "unless..."): they often
signal that a different, more specific rule elsewhere in the context overrides a general one.
When more than one chunk could apply, prefer the most specific rule that matches the question
over a general default, and briefly note why the general rule doesn't apply if it's relevant to
the answer.

If the context does not contain enough information to answer, set answer_found to false and
briefly say so in the answer field instead of guessing. Always list the doc_ids of the context
chunks you actually used as citations."""


def _history_as_text(history: list[dict] | None) -> str:
    # KnowledgeAgent calls get_structured_output with a single prompt string, not a messages
    # list, so prior turns (already in OpenAI message shape from ConversationMemory) get
    # flattened to text here rather than ConversationMemory exposing a second shape.
    if not history:
        return ""
    lines = [f"{m['role']}: {m['content']}" for m in history]
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


class KnowledgeAgent:
    """Retrieval-Augmented Generation over company-policy-style documents (learnings.md #3).
    Only ever reads from the vector store — never touches Confluence or any ingestion source
    directly; sourcing documents into the store is a separate, deferred concern (Component 4)."""

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        vector_store: VectorStore,
        llm_client: LLMClient,
        *,
        top_k: int = 3,
        retrieval_floor: float = 0.2,
    ) -> None:
        self._embedding_client = embedding_client
        self._vector_store = vector_store
        self._llm_client = llm_client
        self._top_k = top_k
        self._retrieval_floor = retrieval_floor

    async def handle(
        self,
        user_request: str,
        history: list[dict] | None = None,
        on_event: OnEvent | None = None,
        tool_cache: ToolCache | None = None,
    ) -> AgentResult:
        # tool_cache accepted for Agent protocol conformance but unused — Component 12's caching
        # targets PerformanceAgent/DatabaseAgent's external reads, not embedding+retrieval.
        emit_event(on_event, {"type": "tool_called", "agent": "knowledge", "tool": "embed_query"})
        query_embedding = await self._embedding_client.embed(user_request)
        emit_event(on_event, {"type": "tool_result", "agent": "knowledge", "tool": "embed_query"})

        emit_event(on_event, {"type": "tool_called", "agent": "knowledge", "tool": "search_documents"})
        chunks = await self._vector_store.query(embedding=query_embedding, top_k=self._top_k)
        emit_event(
            on_event,
            {"type": "tool_result", "agent": "knowledge", "tool": "search_documents", "detail": f"{len(chunks)} chunk(s) found"},
        )

        # retrieval_floor is a cheap sanity check only — "is there any real signal at all" —
        # not a per-chunk relevance filter (learnings.md #3 follow-up: a strict per-chunk floor
        # silently dropped genuinely correct chunks that scored just under it, e.g. a $75/person
        # client-meals figure at 0.4791 vs. a 0.5 floor). Once there's any real signal, every
        # retrieved chunk goes to the LLM, and KnowledgeAnswer.answer_found — which the LLM has
        # shown it sets correctly, including on partial/borderline context — is the real
        # groundedness gate, not a cosine-similarity number.
        if not chunks or max(chunk.similarity for chunk in chunks) < self._retrieval_floor:
            return AgentResult(
                agent_name="knowledge",
                content="I couldn't find anything in the knowledge base relevant to that question.",
                metadata={"citations": [], "answer_found": False},
            )

        context = "\n\n".join(f"[{chunk.doc_id}]\n{chunk.text}" for chunk in chunks)
        history_text = _history_as_text(history)
        user_prompt = f"{history_text}Question: {user_request}\n\nContext:\n{context}"

        emit_event(on_event, {"type": "tool_called", "agent": "knowledge", "tool": "generate_answer"})
        answer = await self._llm_client.get_structured_output(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=KnowledgeAnswer,
        )
        emit_event(on_event, {"type": "tool_result", "agent": "knowledge", "tool": "generate_answer"})

        return AgentResult(
            agent_name="knowledge",
            content=answer.answer,
            metadata={"citations": answer.citations, "answer_found": answer.answer_found},
        )
