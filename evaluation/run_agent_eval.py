"""Live correctness evaluation for the Performance and Database Agents (learnings.md #11), using
DeepEval's GEval (LLM-as-judge correctness) against the golden datasets in evaluation/datasets/.

Not part of the automated test suite — real OpenAI + real Jira/Confluence/Bitbucket/Postgres
calls, real cost, same bucket as scripts/smoke_test_*.py. Requires the `eval` extra
(`pip install -e ".[dev,eval]"`) and both sandboxes already seeded
(scripts/push_performance_fixtures_*.py, scripts/push_database_fixtures.py).

Usage: .venv/Scripts/python.exe -m evaluation.run_agent_eval

Scope note (learnings.md #11): this uses GEval correctness, not DeepEval's ToolCorrectnessMetric/
TaskCompletionMetric — those need DeepEval's tracing integration (@observe decorators
instrumenting the agent's internal tool-calling loop), a meaningfully bigger, more invasive change
than anything here. Deferred as a documented future upgrade, same pattern as Component 4's MCP
deferral. Performance Agent's citations (real Jira keys/Confluence refs/Bitbucket commit refs,
collected programmatically) are checked deterministically instead, which is cheaper and more
reliable than asking an LLM to judge citation correctness.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# See evaluation/run_knowledge_eval.py's identical block: DeepEval's Rich console output crashes
# on Windows' legacy cp1252 terminal encoding without this.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


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
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    from enterprise_ai.bootstrap import build_shared_resources, close_shared_resources
    from evaluation.datasets.database_golden import DATABASE_GOLDEN_CASES
    from evaluation.datasets.performance_golden import PERFORMANCE_GOLDEN_CASES

    shared = await build_shared_resources()

    correctness = GEval(
        name="Correctness",
        criteria=(
            "Determine whether 'actual output' correctly and factually answers 'input', given the "
            "reference facts in 'expected output'. The wording doesn't need to match — only the "
            "facts (numbers, names, conclusions) need to be correct and not contradicted."
        ),
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT],
    )

    test_cases = []

    print("=== Performance Agent eval: deterministic citation checks ===\n")
    for case in PERFORMANCE_GOLDEN_CASES:
        question = case["question"]
        result = await shared.performance_agent.handle(question)
        citations = result.metadata.get("citations", []) if result.metadata else []

        print(f"Q: {question}")
        print(f"  answer:    {result.content}")
        print(f"  citations: {citations}")

        expected_substring = case["expected_citation_substring"]
        if expected_substring is not None:
            hit = any(expected_substring in c for c in citations)
            print(f"  expected citation containing '{expected_substring}': {'YES' if hit else 'NO (!!)'}")
        print()

        test_cases.append(LLMTestCase(input=question, actual_output=result.content, expected_output=case["expected_output"]))

    print("=== Database Agent eval: deterministic refusal check + GEval correctness ===\n")
    for case in DATABASE_GOLDEN_CASES:
        question = case["question"]
        result = await shared.database_agent.handle(question)
        citations = result.metadata.get("citations", []) if result.metadata else []

        print(f"Q: {question}")
        print(f"  answer:    {result.content}")
        print(f"  citations: {citations}")

        if case["is_refusal_case"]:
            # A refused write attempt should never reach run_sql_query at all — no SQL citation
            # recorded (learnings.md #5: "Try to delete all employees" refused without even
            # calling the tool).
            refused = len(citations) == 0
            print(f"  expected refusal (no SQL executed): {'YES' if refused else 'NO (!!)'}")
            print()
            continue

        print()
        test_cases.append(LLMTestCase(input=question, actual_output=result.content, expected_output=case["expected_output"]))

    await close_shared_resources(shared)

    print("=== Performance + Database Agent eval: DeepEval GEval correctness ===\n")
    evaluate(test_cases=test_cases, metrics=[correctness])


if __name__ == "__main__":
    asyncio.run(main())
