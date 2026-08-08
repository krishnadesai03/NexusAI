from __future__ import annotations

import pytest

from enterprise_ai.orchestrator.router import Router, RoutingError
from enterprise_ai.orchestrator.schemas import RoutingDecision


class FakeLLMClient:
    """Returns queued responses in order; an Exception in the queue is raised
    instead of returned, simulating a schema-invalid / malformed model response."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def get_structured_output(self, *, system_prompt, user_prompt, schema):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def test_route_single_agent():
    decision = RoutingDecision(agents=["knowledge"], reasoning="docs question")
    router = Router(FakeLLMClient([decision]))

    result = await router.route("What's our PTO policy?")

    assert result.agents == ["knowledge"]


async def test_route_multi_agent_fan_out():
    decision = RoutingDecision(agents=["database", "knowledge"], reasoning="needs both")
    router = Router(FakeLLMClient([decision]))

    result = await router.route("Compare last sprint's velocity to what the docs promised")

    assert set(result.agents) == {"database", "knowledge"}


async def test_route_retries_on_invalid_output_then_succeeds():
    good_decision = RoutingDecision(agents=["performance"], reasoning="jira question")
    router = Router(FakeLLMClient([ValueError("malformed tool call"), good_decision]), max_retries=2)

    result = await router.route("How's the current sprint going?")

    assert result.agents == ["performance"]


async def test_route_raises_after_exhausting_retries():
    router = Router(
        FakeLLMClient([ValueError("bad"), ValueError("bad"), ValueError("bad")]),
        max_retries=2,
    )

    with pytest.raises(RoutingError):
        await router.route("anything")
