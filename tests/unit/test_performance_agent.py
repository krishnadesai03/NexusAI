from __future__ import annotations

import asyncio
import time

from enterprise_ai.agents.performance.agent import MAX_TOOL_ITERATIONS, PerformanceAgent
from enterprise_ai.core.llm_client import ToolCall, ToolResponse
from enterprise_ai.core.llm_retry import LLM_CALL_MAX_ATTEMPTS
from enterprise_ai.core.tool_cache import ToolCache

SPRINT_CALENDAR = [{"index": 1, "name": "Sprint 1", "start_date": "2026-02-05", "end_date": "2026-02-18"}]


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
    then returns `then` — used to test call_tool_with_retry's retry-with-more-time behavior."""

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


class FailingJiraClient:
    async def search_issues(self, **kwargs):
        raise ValueError("simulated Jira API failure (e.g. a stale/404 lookup)")


class FakeJiraClient:
    def __init__(self, results=None):
        self._results = results if results is not None else []
        self.calls: list[dict] = []

    async def search_issues(self, **kwargs):
        self.calls.append(kwargs)
        return self._results


class FakeConfluenceClient:
    def __init__(self, pages=None, content=""):
        self._pages = pages if pages is not None else []
        self._content = content

    async def search_pages(self, **kwargs):
        return self._pages

    async def get_page_content(self, page_id):
        return self._content


class FakeBitbucketClient:
    def __init__(self, commits=None):
        self._commits = commits if commits is not None else []

    async def get_commits(self, **kwargs):
        return self._commits


class SlowJiraClient:
    """Sleeps before returning, so tests can prove tool calls run concurrently rather than
    one-at-a-time — see test_independent_tool_calls_in_one_turn_run_concurrently."""

    def __init__(self, delay: float, results=None):
        self._delay = delay
        self._results = results if results is not None else []

    async def search_issues(self, **kwargs):
        await asyncio.sleep(self._delay)
        return self._results


class SlowBitbucketClient:
    def __init__(self, delay: float, commits=None):
        self._delay = delay
        self._commits = commits if commits is not None else []

    async def get_commits(self, **kwargs):
        await asyncio.sleep(self._delay)
        return self._commits


def _make_agent(llm_client, jira=None, confluence=None, bitbucket=None):
    return PerformanceAgent(
        llm_client=llm_client,
        jira_client=jira or FakeJiraClient(),
        confluence_client=confluence or FakeConfluenceClient(),
        bitbucket_client=bitbucket or FakeBitbucketClient(),
        sprint_calendar=SPRINT_CALENDAR,
    )


async def test_answers_immediately_when_no_tool_calls_needed():
    llm = FakeLLMClient([ToolResponse(content="No tools needed, here's the answer.")])
    agent = _make_agent(llm)

    result = await agent.handle("what's the team size?")

    assert result.agent_name == "performance"
    assert result.content == "No tools needed, here's the answer."
    assert result.metadata == {"citations": []}


async def test_single_tool_call_then_final_answer_tracks_citations():
    jira = FakeJiraClient(results=[{"key": "KAN-7", "summary": "x", "status": "Done"}])
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="search_jira_issues", arguments={"sprint_index": 1})],
            ),
            ToolResponse(content="Sprint 1 had 1 completed ticket."),
        ]
    )
    agent = _make_agent(llm, jira=jira)

    result = await agent.handle("how many tickets in sprint 1?")

    assert result.content == "Sprint 1 had 1 completed ticket."
    assert result.metadata["citations"] == ["KAN-7"]
    assert jira.calls == [{"sprint_index": 1}]


async def test_multiple_tool_calls_across_turns_accumulate_citations():
    jira = FakeJiraClient(results=[{"key": "KAN-1", "summary": "x", "status": "Done"}])
    bitbucket = FakeBitbucketClient(commits=[{"author": "Marcus Chen <m@x.com>", "date": "2026-02-10", "message": "x"}])
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="search_jira_issues", arguments={})],
            ),
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_2", name="get_bitbucket_commits", arguments={"author": "Marcus"})],
            ),
            ToolResponse(content="Combined answer using both sources."),
        ]
    )
    agent = _make_agent(llm, jira=jira, bitbucket=bitbucket)

    result = await agent.handle("compare Marcus's tickets and commits")

    assert result.content == "Combined answer using both sources."
    assert "KAN-1" in result.metadata["citations"]
    assert any(c.startswith("commit:") for c in result.metadata["citations"])


async def test_stops_after_max_iterations_if_llm_never_concludes():
    llm = FakeLLMClient(
        [
            ToolResponse(content=None, tool_calls=[ToolCall(id=f"call_{i}", name="search_jira_issues", arguments={})])
            for i in range(MAX_TOOL_ITERATIONS)
        ]
    )
    agent = _make_agent(llm)

    result = await agent.handle("keep looping forever")

    assert "couldn't reach a final answer" in result.content
    assert len(llm.calls) == MAX_TOOL_ITERATIONS


async def test_confluence_page_content_tool_does_not_pollute_citations_twice():
    confluence = FakeConfluenceClient(
        pages=[{"id": "123", "title": "Sprint 1 Retro"}], content="Full retro text"
    )
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="search_confluence_pages", arguments={"sprint_index": 1})],
            ),
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_2", name="get_confluence_page_content", arguments={"page_id": "123"})],
            ),
            ToolResponse(content="Sprint 1 retro summary."),
        ]
    )
    agent = _make_agent(llm, confluence=confluence)

    result = await agent.handle("summarize sprint 1 retro")

    assert result.metadata["citations"] == ["page:Sprint 1 Retro"]


async def test_tool_execution_error_is_fed_back_and_llm_can_recover():
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="search_jira_issues", arguments={"sprint_index": 1})],
            ),
            ToolResponse(content="Ran into an issue fetching that, here's what I know instead."),
        ]
    )
    agent = _make_agent(llm, jira=FailingJiraClient())

    result = await agent.handle("how many tickets in sprint 1?")

    assert result.content == "Ran into an issue fetching that, here's what I know instead."
    assert len(llm.calls) == 2


async def test_recovers_after_transient_llm_failures_within_retry_budget():
    llm = FlakyLLMClient(fail_times=LLM_CALL_MAX_ATTEMPTS - 1, then=ToolResponse(content="Recovered answer."))
    agent = _make_agent(llm)

    result = await agent.handle("what's the team size?")

    assert result.content == "Recovered answer."
    assert llm.attempts == LLM_CALL_MAX_ATTEMPTS


async def test_gives_up_with_clean_message_after_persistent_llm_failures():
    llm = FlakyLLMClient(fail_times=LLM_CALL_MAX_ATTEMPTS, then=ToolResponse(content="never reached"))
    agent = _make_agent(llm)

    result = await agent.handle("what's the team size?")

    assert "couldn't reach the AI service" in result.content
    assert llm.attempts == LLM_CALL_MAX_ATTEMPTS


async def test_emits_tool_called_and_tool_result_events_for_the_live_trace():
    jira = FakeJiraClient(results=[{"key": "KAN-7", "summary": "x", "status": "Done"}])
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="search_jira_issues", arguments={"sprint_index": 1})],
            ),
            ToolResponse(content="Sprint 1 had 1 completed ticket."),
        ]
    )
    agent = _make_agent(llm, jira=jira)
    events: list[dict] = []

    await agent.handle("how many tickets in sprint 1?", on_event=events.append)

    assert events[0]["type"] == "tool_called"
    assert events[0]["agent"] == "performance"
    assert events[0]["tool"] == "search_jira_issues"
    assert events[1]["type"] == "tool_result"
    assert events[1]["agent"] == "performance"
    assert events[1]["tool"] == "search_jira_issues"


async def test_independent_tool_calls_in_one_turn_run_concurrently():
    delay = 0.05
    jira = SlowJiraClient(delay=delay, results=[{"key": "KAN-1", "summary": "x", "status": "Done"}])
    bitbucket = SlowBitbucketClient(delay=delay, commits=[{"author": "Marcus Chen", "date": "2026-02-10", "message": "x"}])
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="call_1", name="search_jira_issues", arguments={}),
                    ToolCall(id="call_2", name="get_bitbucket_commits", arguments={}),
                ],
            ),
            ToolResponse(content="Combined answer."),
        ]
    )
    agent = _make_agent(llm, jira=jira, bitbucket=bitbucket)

    start = time.monotonic()
    await agent.handle("compare tickets and commits")
    elapsed = time.monotonic() - start

    # Sequential execution would take >= 2 * delay; concurrent execution takes ~1 * delay.
    assert elapsed < delay * 1.5


async def test_tool_cache_avoids_refetching_an_identical_call_within_a_session():
    jira = FakeJiraClient(results=[{"key": "KAN-7", "summary": "x", "status": "Done"}])
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="search_jira_issues", arguments={"sprint_index": 1})],
            ),
            ToolResponse(content="First answer."),
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_2", name="search_jira_issues", arguments={"sprint_index": 1})],
            ),
            ToolResponse(content="Second answer, reusing the cached lookup."),
        ]
    )
    agent = _make_agent(llm, jira=jira)
    tool_cache = ToolCache()

    first = await agent.handle("how many tickets in sprint 1?", tool_cache=tool_cache)
    second = await agent.handle("what were they about?", tool_cache=tool_cache)

    assert first.content == "First answer."
    assert second.content == "Second answer, reusing the cached lookup."
    # only one real call reached the Jira client — the second was served from the session cache
    assert jira.calls == [{"sprint_index": 1}]
    # citations are still correct on the cache-hit path, not lost
    assert second.metadata["citations"] == ["KAN-7"]


async def test_no_tool_cache_means_every_call_refetches():
    jira = FakeJiraClient(results=[{"key": "KAN-7", "summary": "x", "status": "Done"}])
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_1", name="search_jira_issues", arguments={"sprint_index": 1})],
            ),
            ToolResponse(content="First answer."),
            ToolResponse(
                content=None,
                tool_calls=[ToolCall(id="call_2", name="search_jira_issues", arguments={"sprint_index": 1})],
            ),
            ToolResponse(content="Second answer."),
        ]
    )
    agent = _make_agent(llm, jira=jira)

    await agent.handle("how many tickets in sprint 1?")
    await agent.handle("what were they about?")

    assert jira.calls == [{"sprint_index": 1}, {"sprint_index": 1}]
