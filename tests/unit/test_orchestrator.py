from __future__ import annotations

from enterprise_ai.core.agent import AgentResult
from enterprise_ai.orchestrator.orchestrator import Orchestrator
from enterprise_ai.orchestrator.router import Router
from enterprise_ai.orchestrator.schemas import RoutingDecision


class FakeLLMClient:
    def __init__(self, decision: RoutingDecision):
        self._decision = decision
        self.user_prompts: list[str] = []

    async def get_structured_output(self, *, system_prompt, user_prompt, schema):
        self.user_prompts.append(user_prompt)
        return self._decision


class FakeAgent:
    def __init__(self, name: str):
        self._name = name
        self.received_history: list[list[dict] | None] = []

    async def handle(self, user_request: str, history: list[dict] | None = None, on_event=None) -> AgentResult:
        self.received_history.append(history)
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


async def test_second_turn_receives_first_turns_history():
    decision = RoutingDecision(agents=["knowledge"], reasoning="docs question")
    llm = FakeLLMClient(decision)
    agents = _all_stub_agents()
    orchestrator = Orchestrator(router=Router(llm), agents=agents)

    await orchestrator.handle("What's our PTO policy?")
    await orchestrator.handle("And what about sick leave?")

    knowledge_agent = agents["knowledge"]
    assert knowledge_agent.received_history[0] in (None, [])
    second_call_history = knowledge_agent.received_history[1]
    assert second_call_history == [
        {"role": "user", "content": "What's our PTO policy?"},
        {"role": "assistant", "content": "knowledge: knowledge handled it"},
    ]
    # the router's second call should also have seen the first turn's summary
    assert "What's our PTO policy?" in llm.user_prompts[1]


async def test_memory_window_keeps_only_last_five_turns():
    decision = RoutingDecision(agents=["knowledge"], reasoning="docs question")
    llm = FakeLLMClient(decision)
    agents = _all_stub_agents()
    orchestrator = Orchestrator(router=Router(llm), agents=agents)

    for i in range(7):
        await orchestrator.handle(f"question {i}")

    # The 7th call (i=6) receives history built from the 6 turns recorded so far (q0..q5),
    # trimmed to the last 5 — so q0 is dropped, leaving q1..q5.
    last_history = agents["knowledge"].received_history[-1]
    assert len(last_history) == 5 * 2  # 5 turns, user+assistant each
    assert last_history[0]["content"] == "question 1"  # turn 0 dropped


async def test_emits_routing_and_agent_lifecycle_events_for_single_agent():
    decision = RoutingDecision(agents=["knowledge"], reasoning="docs question")
    orchestrator = Orchestrator(router=Router(FakeLLMClient(decision)), agents=_all_stub_agents())
    events: list[dict] = []

    await orchestrator.handle("What's our PTO policy?", on_event=events.append)

    assert events[0] == {"type": "routing_decided", "agents": ["knowledge"], "reasoning": "docs question"}
    assert {"type": "agent_started", "agent": "knowledge"} in events
    assert {"type": "agent_finished", "agent": "knowledge"} in events
    # started must precede finished for the same agent
    assert events.index({"type": "agent_started", "agent": "knowledge"}) < events.index(
        {"type": "agent_finished", "agent": "knowledge"}
    )


async def test_emits_agent_lifecycle_events_for_every_agent_in_a_fan_out():
    decision = RoutingDecision(agents=["database", "knowledge"], reasoning="needs both")
    orchestrator = Orchestrator(router=Router(FakeLLMClient(decision)), agents=_all_stub_agents())
    events: list[dict] = []

    await orchestrator.handle("Compare last sprint's velocity to what the docs promised", on_event=events.append)

    started = {e["agent"] for e in events if e["type"] == "agent_started"}
    finished = {e["agent"] for e in events if e["type"] == "agent_finished"}
    assert started == {"database", "knowledge"}
    assert finished == {"database", "knowledge"}


async def test_no_events_emitted_when_on_event_is_omitted():
    decision = RoutingDecision(agents=["knowledge"], reasoning="docs question")
    orchestrator = Orchestrator(router=Router(FakeLLMClient(decision)), agents=_all_stub_agents())

    # must not raise just because on_event wasn't passed — matches every existing caller
    result = await orchestrator.handle("What's our PTO policy?")

    assert result.routed_to == ["knowledge"]
