"""Live RAG evaluation for the Knowledge Agent (learnings.md #11), using DeepEval's standard RAG
metrics against the golden dataset in evaluation/datasets/knowledge_golden.py.

Not part of the automated test suite — real OpenAI + real pgvector calls, real cost, same bucket
as scripts/smoke_test_*.py. Requires the `eval` extra (`pip install -e ".[dev,eval]"`) and the
knowledge fixtures already seeded (scripts/seed_knowledge_fixtures.py).

Usage: .venv/Scripts/python.exe -m evaluation.run_knowledge_eval

Design note: KnowledgeAgent.handle() never returns the retrieved chunks' text (only citations and
answer_found — see agents/knowledge/agent.py), so this script queries the vector store directly,
mirroring exactly what the agent does internally, to get chunk text for DeepEval's
`retrieval_context` field. This is additive only — zero production code changes — and has the side
benefit of cleanly separating "did retrieval work" from "did generation work," which is what RAG
eval is supposed to distinguish.

Model-agnostic ranking metrics (Recall@k, MRR): in addition to DeepEval's LLM-judged
ContextualPrecision/ContextualRecall, this script also computes classic retrieval-ranking metrics
directly off the embedding similarity ordering — no LLM judge call involved, pure math over
`vector_store.query()` results. For each golden case with a known `expected_source_doc`, it finds
the rank (1-indexed) of the first retrieved chunk belonging to that doc among the top
RETRIEVAL_K results, then reports Recall@1/@3/@5 (did the expected doc appear in the top 1/3/5)
and MRR (mean of 1/rank across all cases, 0 if not found in top RETRIEVAL_K).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# DeepEval's evaluate() prints Rich console output containing non-ASCII characters (e.g. a
# sparkle emoji); Windows' legacy terminal encoding (cp1252) can't render them and crashes mid-run
# with UnicodeEncodeError. Reconfiguring stdout/stderr to UTF-8 up front avoids that regardless of
# how the script is invoked (no reliance on the caller running `chcp 65001` first).
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent

RETRIEVAL_K = 5


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
    _load_dotenv(ROOT / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill in your key.")

    from deepeval import evaluate
    from deepeval.metrics import AnswerRelevancyMetric, ContextualPrecisionMetric, ContextualRecallMetric, FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    from enterprise_ai.bootstrap import build_shared_resources, close_shared_resources
    from enterprise_ai.core.embedding_client import default_embedding_client
    from evaluation.datasets.knowledge_golden import KNOWLEDGE_GOLDEN_CASES

    shared = await build_shared_resources()
    embedding_client = default_embedding_client()

    test_cases = []
    ranks: list[int | None] = []  # 1-indexed rank of expected doc's first chunk, None if not in top RETRIEVAL_K
    print("=== Knowledge Agent eval: deterministic checks (retrieval/answer_found) ===\n")

    for case in KNOWLEDGE_GOLDEN_CASES:
        question = case["question"]
        result = await shared.knowledge_agent.handle(question)
        citations = result.metadata.get("citations", [])
        answer_found = result.metadata.get("answer_found")

        print(f"Q: {question}")
        print(f"  answer:       {result.content}")
        print(f"  citations:    {citations}")
        print(f"  answer_found: {answer_found}")

        expected_doc = case["expected_source_doc"]
        if expected_doc is not None:
            hit = any(c.startswith(expected_doc) for c in citations)
            print(f"  expected doc '{expected_doc}' cited: {'YES' if hit else 'NO (!!)'}")

        expect_answer_found = case["expect_answer_found"]
        if expect_answer_found is not None:
            match = answer_found == expect_answer_found
            print(f"  expected answer_found={expect_answer_found}: {'YES' if match else 'NO (!!)'}")
        print()

        # DeepEval's RAG metrics need retrieval_context (actual retrieved chunk text) and an
        # expected_output to compare against — skip building a test case for the Mars/out-of-scope
        # question, which has neither by design (nothing should be retrieved for it).
        if expected_doc is None:
            continue

        query_embedding = await embedding_client.embed(question)
        ranked_chunks = await shared.vector_store.query(embedding=query_embedding, top_k=RETRIEVAL_K)

        rank = next(
            (i for i, chunk in enumerate(ranked_chunks, start=1) if chunk.doc_id.startswith(expected_doc)),
            None,
        )
        ranks.append(rank)
        print(f"  expected doc rank in top {RETRIEVAL_K}: {rank if rank is not None else f'not found (> {RETRIEVAL_K})'}")
        print()

        test_cases.append(
            LLMTestCase(
                input=question,
                actual_output=result.content,
                expected_output=case["expected_output"],
                retrieval_context=[chunk.text for chunk in ranked_chunks[:3]],
            )
        )

    await close_shared_resources(shared)

    print("=== Knowledge Agent eval: model-agnostic ranking metrics (embedding similarity only, no LLM judge) ===\n")
    n = len(ranks)
    for k in (1, 3, 5):
        hits = sum(1 for r in ranks if r is not None and r <= k)
        print(f"  Recall@{k}: {hits}/{n} ({hits / n:.0%})")
    mrr = sum((1 / r) if r is not None else 0.0 for r in ranks) / n
    print(f"  MRR:       {mrr:.3f}")
    print()

    print("=== Knowledge Agent eval: DeepEval RAG metrics ===\n")
    evaluate(
        test_cases=test_cases,
        metrics=[
            ContextualPrecisionMetric(),
            ContextualRecallMetric(),
            FaithfulnessMetric(),
            AnswerRelevancyMetric(),
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
