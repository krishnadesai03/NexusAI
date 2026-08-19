from __future__ import annotations

from enterprise_ai.agents.database.agent import MAX_TOOL_ITERATIONS, DatabaseAgent
from enterprise_ai.core.llm_client import ToolCall, ToolResponse
from enterprise_ai.core.llm_retry import LLM_CALL_MAX_ATTEMPTS

SCHEMA_DESCRIPTION = "\nTable: company_data.employees\n  id (integer)\n  name (text)\n  salary (numeric)"


class FakeLLMClient:
    def __init__(self, responses: list[ToolResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def get_structured_output(self, **kwargs):
        raise NotImplementedError

    async def get_tool_response(self, *, messages, tools):
        self.calls.append(messages)
        return self._responses.pop(0)


class FlakyLLMClient:
    """Fails the first `fail_times` calls to get_tool_response (simulating network/API errors),
    then returns `then` — used to test _call_llm_with_retry's retry-with-more-time behavior."""

    def __init__(self, fail_times: int, then: ToolResponse):
        self._fail_times = fail_times
        self._then = then
        self.attempts = 0

    async def get_structured_output(self, **kwargs):
        raise NotImplementedError

    async def get_tool_response(self, *, messages, tools):
        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise ConnectionError("simulated network failure")
        return self._then


class FakeDbClient:
    def __init__(self, result=None, raise_error: Exception | None = None):
        self._result = result if result is not None else {"row_count": 0, "truncated": False, "rows": []}
        self._raise_error = raise_error
        self.queries: list[str] = []

    async def run_query(self, sql: str) -> dict:
        self.queries.append(sql)
        if self._raise_error:
            raise self._raise_error
        return self._result


def _make_agent(llm_client, db_client=None):
    return DatabaseAgent(
        llm_client=llm_client,
        db_client=db_client or FakeDbClient(),
        schema_description=SCHEMA_DESCRIPTION,
    )


async def test_answers_immediately_when_no_query_needed():
    llm = FakeLLMClient([ToolResponse(content="No query needed, here's the answer.")])
    agent = _make_agent(llm)

    result = await agent.handle("what tables exist?")

    assert result.agent_name == "database"
    assert result.content == "No query needed, here's the answer."
    assert result.metadata == {"citations": []}


async def test_single_query_then_final_answer_tracks_sql_as_citation():
    db = FakeDbClient(result={"row_count": 1, "truncated": False, "rows": [{"name": "Priya Nair", "salary": 71100.0}]})
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="run_sql_query",
                        arguments={"sql": "SELECT name, salary FROM company_data.employees WHERE name = 'Priya Nair'"},
                    )
                ],
            ),
            ToolResponse(content="Priya Nair's salary is $71,100."),
        ]
    )
    agent = _make_agent(llm, db_client=db)

    result = await agent.handle("what is Priya Nair's salary?")

    assert result.content == "Priya Nair's salary is $71,100."
    assert result.metadata["citations"] == ["SELECT name, salary FROM company_data.employees WHERE name = 'Priya Nair'"]
    assert db.queries == ["SELECT name, salary FROM company_data.employees WHERE name = 'Priya Nair'"]


async def test_query_error_is_fed_back_and_llm_can_retry():
    db = FakeDbClient(raise_error=ValueError("column \"salry\" does not exist"))
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="run_sql_query", arguments={"sql": "SELECT salry FROM company_data.employees"})],
            ),
            ToolResponse(content="I made a typo, let me answer differently instead."),
        ]
    )
    agent = _make_agent(llm, db_client=db)

    result = await agent.handle("bad query test")

    # a failed query still gets recorded as an attempted citation-worthy action isn't required —
    # what matters is the loop didn't crash and the LLM got a chance to respond after the error
    assert result.content == "I made a typo, let me answer differently instead."
    assert len(llm.calls) == 2


async def test_stops_after_max_iterations_if_llm_never_concludes():
    llm = FakeLLMClient(
        [
            ToolResponse(content=None, tool_calls=[ToolCall(id=f"call_{i}", name="run_sql_query", arguments={"sql": "SELECT 1"})])
            for i in range(MAX_TOOL_ITERATIONS)
        ]
    )
    agent = _make_agent(llm)

    result = await agent.handle("keep looping forever")

    assert "couldn't reach a final answer" in result.content
    assert len(llm.calls) == MAX_TOOL_ITERATIONS


async def test_recovers_after_transient_llm_failures_within_retry_budget():
    llm = FlakyLLMClient(fail_times=LLM_CALL_MAX_ATTEMPTS - 1, then=ToolResponse(content="Recovered answer."))
    agent = _make_agent(llm)

    result = await agent.handle("what is Priya Nair's salary?")

    assert result.content == "Recovered answer."
    assert llm.attempts == LLM_CALL_MAX_ATTEMPTS


async def test_gives_up_with_clean_message_after_persistent_llm_failures():
    llm = FlakyLLMClient(fail_times=LLM_CALL_MAX_ATTEMPTS, then=ToolResponse(content="never reached"))
    agent = _make_agent(llm)

    result = await agent.handle("what is Priya Nair's salary?")

    assert "couldn't reach the AI service" in result.content
    assert llm.attempts == LLM_CALL_MAX_ATTEMPTS


async def test_emits_tool_called_and_tool_result_events_for_the_live_trace():
    db = FakeDbClient(result={"row_count": 1, "truncated": False, "rows": [{"name": "Priya Nair", "salary": 71100.0}]})
    sql = "SELECT name, salary FROM company_data.employees WHERE name = 'Priya Nair'"
    llm = FakeLLMClient(
        [
            ToolResponse(content=None, tool_calls=[ToolCall(id="call_1", name="run_sql_query", arguments={"sql": sql})]),
            ToolResponse(content="Priya Nair's salary is $71,100."),
        ]
    )
    agent = _make_agent(llm, db_client=db)
    events: list[dict] = []

    await agent.handle("what is Priya Nair's salary?", on_event=events.append)

    assert events[0] == {"type": "tool_called", "agent": "database", "tool": "run_sql_query", "detail": sql}
    assert events[1]["type"] == "tool_result"
    assert events[1]["agent"] == "database"
    assert events[1]["tool"] == "run_sql_query"
