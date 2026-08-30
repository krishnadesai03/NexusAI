from __future__ import annotations

import asyncio
from dataclasses import dataclass

from enterprise_ai.core.agent import Agent, AgentResult, OnEvent, emit_event
from enterprise_ai.core.tool_cache import ToolCache
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
    different agent than the one before it.

    Also owns a ToolCache (Component 12), same session-only lifetime and rationale as
    ConversationMemory — threaded into every agent's `handle()` call the same way `history` is,
    so PerformanceAgent/DatabaseAgent (the only agents that use it) don't re-fetch the same
    Jira/Confluence/Bitbucket/SQL lookup twice within one conversation."""

    def __init__(
        self,
        router: Router,
        agents: dict[str, Agent],
        memory: ConversationMemory | None = None,
        tool_cache: ToolCache | None = None,
    ) -> None:
        self._router = router
        self._agents = agents
        self._memory = memory or ConversationMemory()
        self._tool_cache = tool_cache or ToolCache()

    async def handle(self, user_request: str, on_event: OnEvent | None = None) -> OrchestratorResult:
        history_messages = self._memory.as_messages()
        history_text = self._memory.as_text_summary()

        decision = await self._router.route(user_request, history_text=history_text)
        emit_event(on_event, {"type": "routing_decided", "agents": list(decision.agents), "reasoning": decision.reasoning})

        unknown = [name for name in decision.agents if name not in self._agents]
        if unknown:
            raise RoutingError(f"Routing decision referenced unregistered agent(s): {unknown}")

        agent_names = decision.agents

        async def _run_agent(name: str) -> AgentResult:
            # agent_started/agent_finished live here rather than inside each agent, so this is
            # the one place that knows about every agent uniformly — an agent implementation
            # only ever needs to report its own tool calls, not its own start/end.
            emit_event(on_event, {"type": "agent_started", "agent": name})
            result = await self._agents[name].handle(user_request, history_messages, on_event, self._tool_cache)
            emit_event(on_event, {"type": "agent_finished", "agent": name})
            return result

        results = await asyncio.gather(*(_run_agent(name) for name in agent_names))
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
