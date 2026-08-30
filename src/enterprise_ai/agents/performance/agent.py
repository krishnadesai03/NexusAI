from __future__ import annotations

import asyncio
import json

from enterprise_ai.core.agent import AgentResult, OnEvent, emit_event
from enterprise_ai.core.llm_client import LLMClient
from enterprise_ai.core.llm_retry import LLMUnavailableError, call_tool_with_retry
from enterprise_ai.core.tool_cache import ToolCache
from enterprise_ai.integrations.atlassian.bitbucket_client import BitbucketClient
from enterprise_ai.integrations.atlassian.confluence_client import ConfluenceClient
from enterprise_ai.integrations.atlassian.jira_client import JiraClient

MAX_TOOL_ITERATIONS = 12

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_jira_issues",
            "description": "Search Jira tickets, optionally filtered by sprint, assignee, work type, or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sprint_index": {"type": "integer", "description": "Sprint number, 1-13."},
                    "assignee": {"type": "string", "description": "Full display name, e.g. 'Priya Nair'."},
                    "work_type": {"type": "string", "enum": ["Story", "Task", "Bug"]},
                    "status": {"type": "string", "enum": ["To Do", "In Progress", "In Review", "Done"]},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bitbucket_commits",
            "description": "List git commits to the api-gateway repo, optionally filtered by author name/email substring, date range, and/or commit message substring.",
            "parameters": {
                "type": "object",
                "properties": {
                    "author": {"type": "string", "description": "Substring to match against commit author name/email."},
                    "since": {"type": "string", "description": "ISO date, e.g. '2026-04-01'."},
                    "until": {"type": "string", "description": "ISO date, e.g. '2026-04-30'."},
                    "message_contains": {"type": "string", "description": "Substring to match against the commit message (case-insensitive)."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_confluence_pages",
            "description": "Find sprint retro pages, optionally for a specific sprint. Returns page id + title only — call get_confluence_page_content for the actual text.",
            "parameters": {
                "type": "object",
                "properties": {"sprint_index": {"type": "integer", "description": "Sprint number, 1-13."}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_confluence_page_content",
            "description": "Fetch the full text content of a Confluence page by its id (from search_confluence_pages).",
            "parameters": {
                "type": "object",
                "properties": {"page_id": {"type": "string"}},
                "required": ["page_id"],
                "additionalProperties": False,
            },
        },
    },
]


def _build_system_prompt(sprint_calendar: list[dict]) -> str:
    calendar_lines = "\n".join(f"  Sprint {s['index']}: {s['start_date']} to {s['end_date']}" for s in sprint_calendar)
    return f"""You are the Performance Analyzer Agent of an internal company assistant. Answer
questions about team delivery — sprint velocity, ticket activity, commit history — using ONLY
the provided tools. Do not guess at data you haven't fetched.

The team has 4 people: Priya Nair and Marcus Chen (backend), Jordan Lee (frontend), Sofia Reyes
(QA). Work is tracked in 13 two-week sprints:
{calendar_lines}

Story points are encoded as a "points-N" label on Jira tickets, not a native field — when a
ticket's labels include "points-3", that ticket is worth 3 points. Sprint membership is also a
label ("sprint-6"), not Jira's native Sprint field.

The most recent sprint is still in progress — it will naturally show fewer completed tickets
than finished sprints simply because it isn't over yet. Don't mistake "still in progress" for
"unusually low output"; that's expected, not an anomaly.

When asked a "what happened" / "why" / "explain" style question, or to find something unusual
or worth flagging, don't stop at raw ticket counts — check the sprint retro pages
(search_confluence_pages, then get_confluence_page_content). Retro pages often contain a
human-written explanation (e.g. someone being on leave) that raw Jira counts alone won't show,
and a real anomaly usually has a real reason behind it worth surfacing, not just a number.

search_jira_issues, get_bitbucket_commits, and search_confluence_pages each return a "count"
field alongside the results. When asked "how many", state that count directly — do not count the
items yourself, you will get it wrong on longer lists.

If no available tool parameter directly matches what's being asked, do not assume the answer is
zero or that the data doesn't exist — fetch the broadest relevant data you can (e.g. call a tool
with no filters) and check it yourself before concluding there's nothing there. Only answer
"none" or "zero" after you've actually looked, never as a default when you're unsure how to filter.

Call tools as needed, potentially several times, to gather enough data before answering. When
you have enough information, respond with a plain-text final answer — do not call further tools
once you're ready to answer."""


class PerformanceAgent:
    """Answers team-performance questions via direct Jira/Confluence/Bitbucket REST APIs
    (learnings.md #4 follow-up: genuine MCP access is blocked, likely an EAP gate — this is
    the proven fallback). Unlike KnowledgeAgent's single-shot retrieve-then-generate, this
    uses a multi-turn tool-calling loop (LLMClient.get_tool_response) since performance
    questions often need several data lookups (e.g. comparing velocity across people/sprints)
    that a single retrieval pass can't capture.

    Citations are tracked programmatically from which tools were actually called and with
    what results — not self-reported by the LLM — which is more reliable than the pattern
    KnowledgeAgent uses, since we control tool execution directly."""

    def __init__(
        self,
        llm_client: LLMClient,
        jira_client: JiraClient,
        confluence_client: ConfluenceClient,
        bitbucket_client: BitbucketClient,
        sprint_calendar: list[dict],
    ) -> None:
        self._llm_client = llm_client
        self._jira_client = jira_client
        self._confluence_client = confluence_client
        self._bitbucket_client = bitbucket_client
        self._sprint_calendar = sprint_calendar

    async def _fetch_raw(self, name: str, arguments: dict) -> object:
        if name == "search_jira_issues":
            return await self._jira_client.search_issues(**arguments)
        if name == "get_bitbucket_commits":
            return await self._bitbucket_client.get_commits(**arguments)
        if name == "search_confluence_pages":
            return await self._confluence_client.search_pages(**arguments)
        if name == "get_confluence_page_content":
            return await self._confluence_client.get_page_content(arguments["page_id"])
        raise ValueError(f"Unknown tool: {name}")

    async def _execute_tool(
        self, name: str, arguments: dict, citations: list[str], tool_cache: ToolCache | None
    ) -> object:
        # count is computed here, not left for the model to work out from a raw list — LLMs are
        # unreliable at counting items in text (confirmed live: correctly fetched 25 real
        # commits, then reported "29" in its prose answer despite the data being right there).
        #
        # The raw fetch (cacheable — Component 12) is kept separate from the count/citations
        # wrapping below (always redone, cheap) so a cache hit still produces correct citations,
        # exactly as if the data had been fetched fresh.
        cached = tool_cache.get(name, arguments) if tool_cache is not None else ToolCache.MISSING
        if cached is not ToolCache.MISSING:
            raw = cached
        else:
            raw = await self._fetch_raw(name, arguments)
            if tool_cache is not None:
                tool_cache.set(name, arguments, raw)

        if name == "search_jira_issues":
            citations.extend(r["key"] for r in raw)
            return {"count": len(raw), "results": raw}
        if name == "get_bitbucket_commits":
            citations.extend(f"commit:{c['date']}:{c['author']}" for c in raw)
            return {"count": len(raw), "results": raw}
        if name == "search_confluence_pages":
            citations.extend(f"page:{r['title']}" for r in raw)
            return {"count": len(raw), "results": raw}
        if name == "get_confluence_page_content":
            return {"content": raw}
        raise ValueError(f"Unknown tool: {name}")

    async def handle(
        self,
        user_request: str,
        history: list[dict] | None = None,
        on_event: OnEvent | None = None,
        tool_cache: ToolCache | None = None,
    ) -> AgentResult:
        messages = [
            {"role": "system", "content": _build_system_prompt(self._sprint_calendar)},
            *(history or []),
            {"role": "user", "content": user_request},
        ]
        citations: list[str] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = await call_tool_with_retry(self._llm_client, messages, _TOOLS)
            except LLMUnavailableError:
                return AgentResult(
                    agent_name="performance",
                    content="The performance agent couldn't reach the AI service right now — please try again in a little while.",
                    metadata={"citations": sorted(set(citations))},
                )

            if not response.tool_calls:
                content = response.content or "I wasn't able to produce an answer from the available data."
                return AgentResult(
                    agent_name="performance",
                    content=content,
                    metadata={"citations": sorted(set(citations))},
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in response.tool_calls
                    ],
                }
            )

            # Tool calls within one turn are independent (e.g. "compare velocity across the
            # team" asks for Jira + Bitbucket + Confluence at once) — run them concurrently
            # (Component 12) instead of one-at-a-time, so total wait is the slowest call, not
            # the sum of all of them. Each call catches its own exception (matching the previous
            # sequential behavior) so one failing lookup doesn't cancel the others via gather.
            async def _run_one(tc):
                try:
                    return await self._execute_tool(tc.name, tc.arguments, citations, tool_cache)
                except Exception as exc:  # noqa: BLE001 — feed the real error back so the LLM can retry
                    return {"error": str(exc)}

            for tc in response.tool_calls:
                emit_event(
                    on_event,
                    {"type": "tool_called", "agent": "performance", "tool": tc.name, "detail": json.dumps(tc.arguments)},
                )

            tool_results = await asyncio.gather(*(_run_one(tc) for tc in response.tool_calls))

            for tc, result in zip(response.tool_calls, tool_results):
                emit_event(
                    on_event,
                    {"type": "tool_result", "agent": "performance", "tool": tc.name, "detail": json.dumps(result)[:200]},
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

        return AgentResult(
            agent_name="performance",
            content="I gathered some data but couldn't reach a final answer within the allowed number of steps.",
            metadata={"citations": sorted(set(citations))},
        )
