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
    decision = RoutingDecision(intent="business", agents=["knowledge"], answer=None)
    router = Router(FakeLLMClient([decision]))

    result = await router.route("What's our PTO policy?")

    assert result.agents == ["knowledge"]


async def test_route_multi_agent_fan_out():
    decision = RoutingDecision(intent="business", agents=["database", "knowledge"], answer=None)
    router = Router(FakeLLMClient([decision]))

    result = await router.route("Compare last sprint's velocity to what the docs promised")

    assert set(result.agents) == {"database", "knowledge"}


async def test_route_raises_after_one_invalid_output_without_retrying():
    client = FakeLLMClient([ValueError("bad"), ValueError("must not be consumed")])
    router = Router(client, max_retries=2)

    with pytest.raises(RoutingError):
        await router.route("anything")

    assert len(client._responses) == 1


def test_non_business_intent_strictly_rejects_agents():
    with pytest.raises(ValueError, match="agents=\\[\\]"):
        RoutingDecision(intent="greeting", agents=["knowledge"], answer="Hello!")


def test_business_intent_requires_agents_and_blank_answer():
    with pytest.raises(ValueError, match="require agents"):
        RoutingDecision(intent="business", agents=[], answer="I'll answer directly")
