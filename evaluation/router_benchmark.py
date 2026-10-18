"""Live benchmark for the production orchestrator routing path.

This intentionally stubs the downstream agents: it exercises the real Router, RoutingDecision
schema, ConversationMemory, and Orchestrator fan-out code without allowing an eval prompt to send
Slack/email or touch external Jira/database systems.

Usage:
    .venv/Scripts/python.exe -m evaluation.router_benchmark --repeats 3 --stream-samples 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.lib._pydantic import to_strict_json_schema

from enterprise_ai.core.agent import AgentResult
from enterprise_ai.orchestrator.orchestrator import Orchestrator
from enterprise_ai.orchestrator.router import Router
from enterprise_ai.orchestrator.schemas import RoutingDecision


MODELS = {
    "gpt-4o-mini-2024-07-18": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-4.1-mini-2025-04-14": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
}
LABELS = ("knowledge", "performance", "database", "communication")


@dataclass(frozen=True)
class Case:
    id: str
    prompt: str
    expected: tuple[str, ...]
    history: str = ""


CASES = (
    Case("k01", "What is our US PTO policy?", ("knowledge",)),
    Case("k02", "Can employees work from home on Fridays?", ("knowledge",)),
    Case("k03", "What does the incident runbook say about postmortems?", ("knowledge",)),
    Case("k04", "What's the domestic travel per diem in the expense policy?", ("knowledge",)),
    Case("k05", "Summarize the onboarding guide for a new engineer.", ("knowledge",)),
    Case("p01", "How is the current sprint going?", ("performance",)),
    Case("p02", "How many Jira bugs did Sofia close?", ("performance",)),
    Case("p03", "How many Bitbucket commits mention billing?", ("performance",)),
    Case("p04", "What did the Confluence Sprint 6 retro say about Marcus?", ("performance",)),
    Case("p05", "Show our velocity trend over the last four sprints.", ("performance",)),
    Case("d01", "What is Priya Nair's salary?", ("database",)),
    Case("d02", "What's our revenue from active subscriptions?", ("database",)),
    Case("d03", "How many Enterprise-tier customers do we have?", ("database",)),
    Case("d04", "How many customer support tickets are still open?", ("database",)),
    Case("d05", "Which department is over its 2026 budget?", ("database",)),
    Case("c01", "Send the engineering team a Slack reminder about standup.", ("communication",)),
    Case("c02", "Email Alex that I will be ten minutes late.", ("communication",)),
    Case("c03", "Draft and send a Slack message saying the deployment is complete.", ("communication",)),
    Case("c04", "Notify the finance team by email that the meeting moved to 3 PM.", ("communication",)),
    Case("c05", "Post 'great work this sprint' in our team Slack channel.", ("communication",)),
    Case("m01", "Compare last sprint's velocity with what our delivery playbook promises.", ("performance", "knowledge")),
    Case("m02", "Look up our PTO carryover rule and email it to Alex.", ("knowledge", "communication")),
    Case("m03", "Find our Enterprise customers and send finance a Slack summary.", ("database", "communication")),
    Case("m04", "Check the current sprint blockers and message the engineering channel about them.", ("performance", "communication")),
    Case("m05", "Compare employee travel expenses with the limits in the expense policy.", ("database", "knowledge")),
    Case("m06", "Compare open customer support tickets with open Jira bugs.", ("database", "performance")),
    Case("m07", "Check Jira delivery data and employee overtime expenses for the release.", ("performance", "database")),
    Case("m08", "Find the 401k vesting rule and compare it with employee salary records.", ("knowledge", "database")),
    Case("m09", "Compare sprint velocity and department budgets, then email the result to leadership.", ("performance", "database", "communication")),
    Case("m10", "Check the incident runbook, current Jira incident work, and related support-ticket volume.", ("knowledge", "performance", "database")),
    Case("m11", "Compare policy, sprint delivery, and customer data, then send an executive Slack summary.", LABELS),
    Case(
        "h01",
        "What about sick leave?",
        ("knowledge",),
        "User: What is our PTO policy?\nAssistant: knowledge: US employees receive 15 PTO days.",
    ),
    Case(
        "h02",
        "Send that summary to the engineering channel.",
        ("communication",),
        "User: How is the current sprint going?\nAssistant: performance: Sprint 8 is on track with two blockers.",
    ),
    Case(
        "h03",
        "How many of those are still open?",
        ("database",),
        "User: Show me our customer support tickets.\nAssistant: database: There are 42 support tickets.",
    ),
    Case(
        "h04",
        "And what did the retro say about it?",
        ("performance",),
        "User: Why was Sprint 6 velocity low?\nAssistant: performance: Sprint 6 had unusually low throughput.",
    ),
)


@dataclass
class CallMeasurement:
    latency_ms: float
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int


class MeasuredOpenAIClient:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model
        self.calls: list[CallMeasurement] = []

    async def get_structured_output(self, *, system_prompt: str, user_prompt: str, schema: type[RoutingDecision]):
        started = time.perf_counter()
        completion = await self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=schema,
            temperature=0,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        usage = completion.usage
        cached = 0
        if usage and usage.prompt_tokens_details:
            cached = usage.prompt_tokens_details.cached_tokens or 0
        self.calls.append(
            CallMeasurement(
                latency_ms=elapsed_ms,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                cached_tokens=cached,
                completion_tokens=usage.completion_tokens if usage else 0,
            )
        )
        message = completion.choices[0].message
        if message.refusal:
            raise ValueError(f"Model refused: {message.refusal}")
        if message.parsed is None:
            raise ValueError("Response did not parse against RoutingDecision")
        return message.parsed

    async def get_tool_response(self, *, messages: list[dict], tools: list[dict]):
        raise AssertionError("The router benchmark must not invoke downstream tool loops")


class StubAgent:
    def __init__(self, name: str) -> None:
        self.name = name

    async def handle(self, user_request: str, history=None, on_event=None, tool_cache=None) -> AgentResult:
        return AgentResult(agent_name=self.name, content=f"{self.name} benchmark stub")


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def price(model: str, calls: list[CallMeasurement]) -> float:
    rates = MODELS[model]
    uncached = sum(call.prompt_tokens - call.cached_tokens for call in calls)
    cached = sum(call.cached_tokens for call in calls)
    output = sum(call.completion_tokens for call in calls)
    return (uncached * rates["input"] + cached * rates["cached_input"] + output * rates["output"]) / 1_000_000


async def stream_measurement(client: AsyncOpenAI, model: str, case: Case) -> dict[str, float | int | None]:
    from enterprise_ai.orchestrator.router import _SYSTEM_PROMPT

    user_prompt = case.prompt
    if case.history:
        user_prompt = f"Conversation so far:\n{case.history}\n\nCurrent request: {case.prompt}"
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "RoutingDecision",
            "strict": True,
            "schema": to_strict_json_schema(RoutingDecision),
        },
    }
    started = time.perf_counter()
    first_token_at: float | None = None
    last_token_at: float | None = None
    usage = None
    stream = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=response_format,
        temperature=0,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if chunk.choices and chunk.choices[0].delta.content:
            now = time.perf_counter()
            first_token_at = first_token_at or now
            last_token_at = now
    ended = time.perf_counter()
    completion_tokens = usage.completion_tokens if usage else 0
    generation_seconds = (last_token_at - first_token_at) if first_token_at and last_token_at else 0
    return {
        "ttft_ms": (first_token_at - started) * 1000 if first_token_at else None,
        "stream_e2e_ms": (ended - started) * 1000,
        "completion_tokens": completion_tokens,
        "tpot_ms": generation_seconds * 1000 / max(completion_tokens - 1, 1),
        "tokens_per_second": max(completion_tokens - 1, 1) / generation_seconds if generation_seconds else None,
    }


async def benchmark_model(client: AsyncOpenAI, model: str, repeats: int, stream_samples: int) -> dict[str, Any]:
    measured = MeasuredOpenAIClient(client, model)
    predictions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for repeat in range(repeats):
        for case in CASES:
            router = Router(measured, max_retries=0)
            try:
                # Preserve the application's exact history formatting while keeping every case independent.
                decision = await router.route(case.prompt, history_text=case.history)
                predicted = tuple(decision.agents)
                # Exercise Orchestrator dispatch without making a second paid router call.
                dispatch_router = Router(_FixedClient(decision), max_retries=0)
                dispatch = Orchestrator(dispatch_router, {label: StubAgent(label) for label in LABELS})
                dispatched = await dispatch.handle(case.prompt)
                if set(dispatched.routed_to) != set(predicted):
                    raise AssertionError("Orchestrator dispatch changed the router decision")
                predictions.append(
                    {
                        "repeat": repeat + 1,
                        "case": case.id,
                        "expected": list(case.expected),
                        "predicted": list(predicted),
                        "exact": set(predicted) == set(case.expected),
                    }
                )
            except Exception as exc:
                failures.append({"repeat": str(repeat + 1), "case": case.id, "error": f"{type(exc).__name__}: {exc}"})

    tp = fp = fn = 0
    by_label = {label: {"tp": 0, "fp": 0, "fn": 0} for label in LABELS}
    over_routed_cases = under_routed_cases = 0
    for row in predictions:
        expected, predicted = set(row["expected"]), set(row["predicted"])
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        over_routed_cases += bool(predicted - expected)
        under_routed_cases += bool(expected - predicted)
        for label in LABELS:
            if label in expected and label in predicted:
                by_label[label]["tp"] += 1
            elif label not in expected and label in predicted:
                by_label[label]["fp"] += 1
            elif label in expected and label not in predicted:
                by_label[label]["fn"] += 1

    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    label_metrics = {}
    for label, counts in by_label.items():
        label_precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0
        label_recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0
        label_f1 = (
            2 * label_precision * label_recall / (label_precision + label_recall)
            if label_precision + label_recall
            else 0
        )
        label_metrics[label] = {"precision": label_precision, "recall": label_recall, "f1": label_f1, **counts}

    stream_results = []
    if stream_samples:
        sample_indices = [round(i * (len(CASES) - 1) / max(stream_samples - 1, 1)) for i in range(stream_samples)]
        for index in sample_indices:
            stream_results.append(await stream_measurement(client, model, CASES[index]))

    latencies = [call.latency_ms for call in measured.calls]
    total_tasks = len(predictions) + len(failures)
    total_cost = price(model, measured.calls)
    valid_streams = [row for row in stream_results if row["ttft_ms"] is not None]
    return {
        "model": model,
        "cases": len(CASES),
        "repeats": repeats,
        "tasks": total_tasks,
        "task_accuracy": sum(row["exact"] for row in predictions) / total_tasks if total_tasks else 0,
        "completion_rate": len(predictions) / total_tasks if total_tasks else 0,
        "schema_failure_rate": len(failures) / total_tasks if total_tasks else 0,
        "micro_precision": precision,
        "micro_recall": recall,
        "micro_f1": f1,
        "macro_f1": statistics.mean(row["f1"] for row in label_metrics.values()),
        "over_routing_case_rate": over_routed_cases / total_tasks if total_tasks else 0,
        "under_routing_case_rate": under_routed_cases / total_tasks if total_tasks else 0,
        "label_metrics": label_metrics,
        "latency_ms": {
            "mean": statistics.mean(latencies),
            "p50": statistics.median(latencies),
            "p95": percentile(latencies, 0.95),
        },
        "streaming": {
            "samples": len(valid_streams),
            "ttft_ms_mean": statistics.mean(row["ttft_ms"] for row in valid_streams) if valid_streams else None,
            "ttft_ms_p50": statistics.median(row["ttft_ms"] for row in valid_streams) if valid_streams else None,
            "ttft_ms_p95": percentile([row["ttft_ms"] for row in valid_streams], 0.95) if valid_streams else None,
            "tpot_ms_mean": statistics.mean(row["tpot_ms"] for row in valid_streams) if valid_streams else None,
            "tokens_per_second_mean": statistics.mean(row["tokens_per_second"] for row in valid_streams) if valid_streams else None,
        },
        "tokens": {
            "input": sum(call.prompt_tokens for call in measured.calls),
            "cached_input": sum(call.cached_tokens for call in measured.calls),
            "output": sum(call.completion_tokens for call in measured.calls),
            "mean_per_task": (sum(call.prompt_tokens + call.completion_tokens for call in measured.calls) / total_tasks),
        },
        "cost_usd": total_cost,
        "cost_per_task_usd": total_cost / total_tasks if total_tasks else 0,
        "cost_per_1000_tasks_usd": total_cost / total_tasks * 1000 if total_tasks else 0,
        "failures": failures,
        "errors": [row for row in predictions if not row["exact"]],
    }


class _FixedClient:
    def __init__(self, decision: RoutingDecision) -> None:
        self.decision = decision

    async def get_structured_output(self, **kwargs):
        return self.decision

    async def get_tool_response(self, **kwargs):
        raise AssertionError


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--stream-samples", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("evaluation/results/router_benchmark.json"))
    args = parser.parse_args()
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    client = AsyncOpenAI()
    results = []
    for model in MODELS:
        print(f"Benchmarking {model}...", flush=True)
        result = await benchmark_model(client, model, args.repeats, args.stream_samples)
        results.append(result)
        print(
            f"  accuracy={result['task_accuracy']:.1%} f1={result['micro_f1']:.3f} "
            f"p50={result['latency_ms']['p50']:.0f}ms cost/1k=${result['cost_per_1000_tasks_usd']:.4f}",
            flush=True,
        )

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "Production Router + RoutingDecision schema; downstream agents stubbed; temperature=0",
        "models": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
