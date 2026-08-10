from __future__ import annotations

import logging

from pydantic import ValidationError

from enterprise_ai.core.llm_client import LLMClient
from enterprise_ai.orchestrator.schemas import RoutingDecision

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the routing layer of an internal company assistant.

Decide which of the following agents are needed to answer the user's request.
Choose only the agents actually required — a request may need one agent or several.

- knowledge: answers questions from static internal company-policy documents (PTO policy,
  expense policy, onboarding guides, engineering runbooks, FAQs). Does not have access to
  Confluence — it only searches a fixed set of ingested policy documents.
- performance: reports on team/project delivery — Jira ENGINEERING tickets (bugs, stories,
  tasks tracked in sprints) and sprints, Bitbucket commit history, and Confluence sprint retro
  pages. "Ticket" here specifically means a Jira issue — a customer support ticket is a
  completely different, unrelated thing that belongs to the database agent instead, not this
  one. Any question about sprints, story points, velocity, commits, or what a sprint retro page
  says belongs here — even if the question literally says "Confluence," since this is the agent
  that actually has Confluence access, not knowledge.
- database: answers questions that require querying structured company data via SQL — employee
  records, customer accounts, sales deals, subscriptions, expenses, budgets, and CUSTOMER
  SUPPORT tickets (a database table — unrelated to Jira issues, even though both happen to be
  called "tickets").
- communication: sends messages/notifications on the user's behalf (Slack, email)
"""


class RoutingError(Exception):
    """Raised when no schema-valid routing decision could be obtained after retries."""


class Router:
    """Hybrid router (learnings.md #1, Option C): an LLM reasons about the request,
    but its output must validate against RoutingDecision before this class will
    return it. An invalid response is retried, never passed downstream as-is."""

    def __init__(self, llm_client: LLMClient, *, max_retries: int = 2) -> None:
        self._llm_client = llm_client
        self._max_retries = max_retries

    async def route(self, user_request: str, history_text: str = "") -> RoutingDecision:
        # history_text (a flattened prior-turns summary from ConversationMemory) lets the router
        # resolve short follow-ups ("what about last quarter") that are ambiguous read alone —
        # empty by default, so a request's first turn behaves exactly as before.
        user_prompt = user_request
        if history_text:
            user_prompt = f"Conversation so far:\n{history_text}\n\nCurrent request: {user_request}"

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return await self._llm_client.get_structured_output(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema=RoutingDecision,
                )
            except (ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Routing attempt %d/%d produced an invalid decision: %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )

        raise RoutingError(
            f"Could not obtain a valid routing decision after {self._max_retries + 1} attempts"
        ) from last_error
