from __future__ import annotations

import asyncio
from dataclasses import dataclass

from enterprise_ai.core.agent import Agent, AgentResult
from enterprise_ai.orchestrator.router import Router, RoutingError


@dataclass
class OrchestratorResult:
    routed_to: list[str]
    results: dict[str, AgentResult]


class Orchestrator:
    """Top-level entry point: routes a request (Router), then fans it out to every
    selected agent concurrently and fans the results back in (learnings.md #0)."""

    def __init__(self, router: Router, agents: dict[str, Agent]) -> None:
        self._router = router
        self._agents = agents

    async def handle(self, user_request: str) -> OrchestratorResult:
        decision = await self._router.route(user_request)

        unknown = [name for name in decision.agents if name not in self._agents]
        if unknown:
            raise RoutingError(f"Routing decision referenced unregistered agent(s): {unknown}")

        agent_names = decision.agents
        results = await asyncio.gather(*(self._agents[name].handle(user_request) for name in agent_names))

        return OrchestratorResult(routed_to=list(agent_names), results=dict(zip(agent_names, results)))
