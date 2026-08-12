from __future__ import annotations

import asyncio
from dataclasses import dataclass

from enterprise_ai.core.agent import Agent, AgentResult
from enterprise_ai.orchestrator.memory import ConversationMemory
from enterprise_ai.orchestrator.router import Router, RoutingError


@dataclass
class OrchestratorResult:
    routed_to: list[str]
    results: dict[str, AgentResult]


class Orchestrator:
    """Top-level entry point: routes a request (Router), then fans it out to every
    selected agent concurrently and fans the results back in (learnings.md #0).

    Owns a ConversationMemory (learnings.md #7) — session-only, in-process history, shared
    across all agents rather than kept per-agent, since a follow-up question can route to a
    different agent than the one before it."""

    def __init__(self, router: Router, agents: dict[str, Agent], memory: ConversationMemory | None = None) -> None:
        self._router = router
        self._agents = agents
        self._memory = memory or ConversationMemory()

    async def handle(self, user_request: str) -> OrchestratorResult:
        history_messages = self._memory.as_messages()
        history_text = self._memory.as_text_summary()

        decision = await self._router.route(user_request, history_text=history_text)

        unknown = [name for name in decision.agents if name not in self._agents]
        if unknown:
            raise RoutingError(f"Routing decision referenced unregistered agent(s): {unknown}")

        agent_names = decision.agents
        results = await asyncio.gather(
            *(self._agents[name].handle(user_request, history_messages) for name in agent_names)
        )
        results_by_name = dict(zip(agent_names, results))

        self._memory.add_turn(user_request, results_by_name)

        return OrchestratorResult(routed_to=list(agent_names), results=results_by_name)

    def get_agent(self, name: str) -> Agent:
        """Lets a caller (e.g. chat.py driving a ConfirmableAgent's confirm/cancel/revise menu)
        reach a specific agent instance directly, outside the normal route-and-fan-out path."""
        return self._agents[name]

    def agent_names(self) -> list[str]:
        """Lets a caller (e.g. the web API's 409 pending-conflict guard) check every registered
        agent for a staged ConfirmableAgent action without hardcoding which agent names exist."""
        return list(self._agents.keys())
