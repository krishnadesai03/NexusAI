from __future__ import annotations

import asyncio
import json

from enterprise_ai.core.agent import AgentResult, OnEvent, emit_event
from enterprise_ai.core.llm_client import LLMClient
from enterprise_ai.core.llm_retry import LLMUnavailableError, call_tool_with_retry
from enterprise_ai.core.tool_cache import ToolCache
from enterprise_ai.integrations.sql_db.postgres_client import PostgresQueryClient

MAX_TOOL_ITERATIONS = 8

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql_query",
            "description": "Run a read-only SQL query (SELECT only) against the company database and return the rows.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "A single SELECT (or WITH ... SELECT) statement."},
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    },
]


def _build_system_prompt(schema_description: str) -> str:
    return f"""You are the Database Agent of an internal company assistant. Answer questions
about company data (employees, departments, customers, deals, subscriptions, expenses,
budgets, support tickets) by writing and running real SQL queries — never guess an answer
without actually running a query.

You can only run read-only queries (SELECT / WITH ... SELECT). Any query that tries to modify
data will be rejected before it runs, and the database connection itself only has permission to
read, not write — there is no way to change data through this agent, by design.

Only these tables and columns exist — do not reference anything not listed here, and always
qualify table names with the schema (e.g. company_data.employees). Where a column's actual
values are listed below, use that exact spelling and capitalization in filters — do not guess
at how a value might be written (e.g. "active" vs "Active"), since a wrong guess silently
returns zero rows instead of an error, which looks like "no data" rather than a wrong query:
{schema_description}

If a query fails (wrong column name, syntax error, etc.), read the actual error message and
try again with a corrected query — do not give up or guess after one failure. Likewise, if a
query unexpectedly returns zero rows for something that plausibly should have data, double
check your filter values (especially exact text matches) before concluding the data doesn't
exist.

Call run_sql_query as needed, potentially several times, to gather enough data before
answering. When you have enough information, respond with a plain-text final answer — do not
call further tools once you're ready to answer."""


class DatabaseAgent:
    """Answers questions about structured company data (learnings.md #5) by having the LLM
    write real SQL against a read-only Postgres connection. Deliberately no permission system
    beyond read-only vs. write — this project is about demonstrating the agent's own reasoning
    (picking the right tables/columns among many), not building role-based access control,
    which is a distinct, out-of-scope concern (noted explicitly, not an oversight).

    Uses the same tool-calling loop pattern as PerformanceAgent, with a single tool
    (run_sql_query) instead of several — SQL's own flexibility means one tool is enough,
    unlike Jira/Confluence/Bitbucket needing separate, structured lookups."""

    def __init__(self, llm_client: LLMClient, db_client: PostgresQueryClient, schema_description: str) -> None:
        self._llm_client = llm_client
        self._db_client = db_client
        self._schema_description = schema_description

    async def handle(
        self,
        user_request: str,
        history: list[dict] | None = None,
        on_event: OnEvent | None = None,
        tool_cache: ToolCache | None = None,
    ) -> AgentResult:
        messages = [
            {"role": "system", "content": _build_system_prompt(self._schema_description)},
            *(history or []),
            {"role": "user", "content": user_request},
        ]
        citations: list[str] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = await call_tool_with_retry(self._llm_client, messages, _TOOLS)
            except LLMUnavailableError:
                return AgentResult(
                    agent_name="database",
                    content="The database agent couldn't reach the AI service right now — please try again in a little while.",
                    metadata={"citations": citations},
                )

            if not response.tool_calls:
                content = response.content or "I wasn't able to produce an answer from the available data."
                return AgentResult(
                    agent_name="database",
                    content=content,
                    metadata={"citations": citations},
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

            # Multiple queries requested in one turn are independent, so run them concurrently
            # (Component 12) rather than one-at-a-time. A query's result is cached by its exact
            # SQL text (session-scoped, via ToolCache) so re-asking a question that needs the
            # same query within one conversation — e.g. "how many bugs did X resolve in sprint
            # 12" then "what were they about?" — doesn't re-hit Postgres for data already fetched.
            # Errors are never cached, so a corrected retry always runs for real.
            async def _run_one(tc):
                sql = tc.arguments.get("sql", "")
                cached = tool_cache.get("run_sql_query", {"sql": sql}) if tool_cache is not None else ToolCache.MISSING
                if cached is not ToolCache.MISSING:
                    citations.append(sql)
                    return cached
                try:
                    result = await self._db_client.run_query(sql)
                    citations.append(sql)
                    if tool_cache is not None:
                        tool_cache.set("run_sql_query", {"sql": sql}, result)
                    return result
                except Exception as exc:  # noqa: BLE001 — feed the real error back so the LLM can retry
                    return {"error": str(exc)}

            for tc in response.tool_calls:
                sql = tc.arguments.get("sql", "")
                emit_event(on_event, {"type": "tool_called", "agent": "database", "tool": "run_sql_query", "detail": sql})

            payloads = await asyncio.gather(*(_run_one(tc) for tc in response.tool_calls))

            for tc, payload in zip(response.tool_calls, payloads):
                emit_event(
                    on_event,
                    {"type": "tool_result", "agent": "database", "tool": "run_sql_query", "detail": json.dumps(payload)[:200]},
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(payload)})

        return AgentResult(
            agent_name="database",
            content="I gathered some data but couldn't reach a final answer within the allowed number of steps.",
            metadata={"citations": citations},
        )
