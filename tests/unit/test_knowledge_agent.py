from __future__ import annotations

from enterprise_ai.agents.knowledge.agent import KnowledgeAgent
from enterprise_ai.agents.knowledge.schemas import KnowledgeAnswer
from enterprise_ai.integrations.vector_store.pgvector_store import RetrievedChunk


class FakeEmbeddingClient:
    def __init__(self, vector: list[float] | None = None):
        self._vector = vector or [0.1, 0.2, 0.3]

    async def embed(self, text: str) -> list[float]:
        return self._vector


class FakeVectorStore:
    def __init__(self, chunks: list[RetrievedChunk]):
        self._chunks = chunks
        self.last_top_k: int | None = None

    async def query(self, *, embedding, top_k):
        self.last_top_k = top_k
        return self._chunks[:top_k]

    async def upsert(self, **kwargs):
        raise NotImplementedError


class FakeLLMClient:
    def __init__(self, response: KnowledgeAnswer):
        self._response = response
        self.last_user_prompt: str | None = None

    async def get_structured_output(self, *, system_prompt, user_prompt, schema):
        self.last_user_prompt = user_prompt
        return self._response


class ExplodingLLMClient:
    async def get_structured_output(self, **kwargs):
        raise AssertionError("LLM should not be called when nothing clears the retrieval floor")


async def test_returns_grounded_answer_when_relevant_chunk_found():
    chunks = [RetrievedChunk(doc_id="pto_policy_us.md::0", text="15 days PTO per year.", metadata={}, similarity=0.9)]
    answer = KnowledgeAnswer(answer="15 days per year.", citations=["pto_policy_us.md::0"], answer_found=True)
    agent = KnowledgeAgent(
        embedding_client=FakeEmbeddingClient(),
        vector_store=FakeVectorStore(chunks),
        llm_client=FakeLLMClient(answer),
    )

    result = await agent.handle("How many PTO days do I get in the US?")

    assert result.agent_name == "knowledge"
    assert result.content == "15 days per year."
    assert result.metadata == {"citations": ["pto_policy_us.md::0"], "answer_found": True}


async def test_returns_not_found_when_nothing_clears_retrieval_floor():
    chunks = [RetrievedChunk(doc_id="unrelated.md::0", text="unrelated content", metadata={}, similarity=0.1)]
    agent = KnowledgeAgent(
        embedding_client=FakeEmbeddingClient(),
        vector_store=FakeVectorStore(chunks),
        llm_client=ExplodingLLMClient(),
        retrieval_floor=0.2,
    )

    result = await agent.handle("What's the weather on Mars?")

    assert result.metadata["answer_found"] is False
    assert result.metadata["citations"] == []


async def test_low_but_real_similarity_chunk_still_reaches_llm():
    """Regression test for the retrieval-floor bug (learnings.md #3 follow-up): a genuinely
    correct chunk scored 0.4791 against a strict 0.5 per-chunk floor and got silently dropped
    before the LLM ever saw it. The floor is now a low sanity check only — any chunk should
    reach the LLM as long as *something* in the batch clears it."""

    chunks = [
        RetrievedChunk(doc_id="travel_policy.md::0", text="$60/day domestic per diem.", metadata={}, similarity=0.66),
        RetrievedChunk(doc_id="expense_policy.md::0", text="client meals up to $75/person.", metadata={}, similarity=0.4791),
    ]
    answer = KnowledgeAnswer(
        answer="$75/person for client meals specifically.",
        citations=["expense_policy.md::0"],
        answer_found=True,
    )
    llm_client = FakeLLMClient(answer)
    agent = KnowledgeAgent(
        embedding_client=FakeEmbeddingClient(),
        vector_store=FakeVectorStore(chunks),
        llm_client=llm_client,
        top_k=2,
    )

    result = await agent.handle("What's the per-day rate for client meals when traveling domestically?")

    assert "expense_policy.md::0" in llm_client.last_user_prompt
    assert "travel_policy.md::0" in llm_client.last_user_prompt
    assert result.metadata["citations"] == ["expense_policy.md::0"]


async def test_trusts_llm_to_disambiguate_near_duplicate_topics():
    chunks = [
        RetrievedChunk(doc_id="pto_policy_us.md::0", text="US PTO: 15 days/year.", metadata={}, similarity=0.92),
        RetrievedChunk(doc_id="pto_policy_india.md::0", text="India leave: 18 EL days.", metadata={}, similarity=0.4),
    ]
    answer = KnowledgeAnswer(answer="15 days per year.", citations=["pto_policy_us.md::0"], answer_found=True)
    vector_store = FakeVectorStore(chunks)
    llm_client = FakeLLMClient(answer)
    agent = KnowledgeAgent(
        embedding_client=FakeEmbeddingClient(),
        vector_store=vector_store,
        llm_client=llm_client,
        top_k=2,
    )

    result = await agent.handle("How many PTO days do I get in the US?")

    assert vector_store.last_top_k == 2
    # both candidates reach the LLM — disambiguation is the LLM's job, not a pre-filter's
    assert "pto_policy_us.md::0" in llm_client.last_user_prompt
    assert "pto_policy_india.md::0" in llm_client.last_user_prompt
    assert result.metadata["citations"] == ["pto_policy_us.md::0"]


async def test_respects_configured_top_k():
    chunks = [
        RetrievedChunk(doc_id=f"doc.md::{i}", text="text", metadata={}, similarity=0.9) for i in range(5)
    ]
    answer = KnowledgeAnswer(answer="answer", citations=["doc.md::0"], answer_found=True)
    vector_store = FakeVectorStore(chunks)
    agent = KnowledgeAgent(
        embedding_client=FakeEmbeddingClient(),
        vector_store=vector_store,
        llm_client=FakeLLMClient(answer),
        top_k=3,
    )

    await agent.handle("some question")

    assert vector_store.last_top_k == 3
