from __future__ import annotations

from enterprise_ai.core.agent import AgentResult
from enterprise_ai.orchestrator.orchestrator import Orchestrator
from enterprise_ai.orchestrator.router import Router
from enterprise_ai.orchestrator.schemas import RoutingDecision


class FakeLLMClient:
    def __init__(self, decision: RoutingDecision):
        self._decision = decision

    async def get_structured_output(self, *, system_prompt, user_prompt, schema):
        return self._decision


class FakeAgent:
    def __init__(self, name: str):
        self._name = name

    async def handle(self, user_request: str) -> AgentResult:
        return AgentResult(agent_name=self._name, content=f"{self._name} handled it")


def _all_stub_agents():
    return {name: FakeAgent(name) for name in ("knowledge", "performance", "database", "communication")}


async def test_orchestrator_routes_to_single_agent():
    decision = RoutingDecision(agents=["knowledge"], reasoning="docs question")
    orchestrator = Orchestrator(router=Router(FakeLLMClient(decision)), agents=_all_stub_agents())

    result = await orchestrator.handle("What's our PTO policy?")

    assert result.routed_to == ["knowledge"]
    assert result.results["knowledge"].content == "knowledge handled it"


async def test_orchestrator_fans_out_to_multiple_agents():
    decision = RoutingDecision(agents=["database", "knowledge"], reasoning="needs both")
    orchestrator = Orchestrator(router=Router(FakeLLMClient(decision)), agents=_all_stub_agents())

    result = await orchestrator.handle("Compare last sprint's velocity to what the docs promised")

    assert set(result.routed_to) == {"database", "knowledge"}
    assert result.results["database"].content == "database handled it"
    assert result.results["knowledge"].content == "knowledge handled it"
