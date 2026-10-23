from __future__ import annotations

import logging

from pydantic import ValidationError

from enterprise_ai.core.llm_client import LLMClient
from enterprise_ai.orchestrator.schemas import RoutingDecision

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the routing and direct-response layer of an internal company assistant.

Return intent, agents, and answer together in this single response.

- business: company information or an action requiring one or more business agents. Set answer=null.
- greeting: a standalone greeting, thanks, or farewell. Set agents=[] and answer directly.
- system_help: what this assistant or an agent can do. Set agents=[] and answer briefly using only
  the capabilities below.
- unsupported: outside the capabilities below. Set agents=[] and explain briefly.
- unsafe: harmful or disallowed. Set agents=[] and refuse briefly.

For EVERY non-business intent, agents MUST be []. For business, agents must be non-empty and
answer MUST be null. A greeting combined with a substantive business request is business. A
follow-up that requires company data is business even when phrased as a clarification.

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

Examples:

User: Hi, show me the Sprint 6 results.
Output: {"intent":"business","agents":["performance"],"answer":null}

User: Before I go, what is our PTO carryover policy?
Output: {"intent":"business","agents":["knowledge"],"answer":null}

User: Compare Sprint 6 delivery with the engineering runbook.
Output: {"intent":"business","agents":["performance","knowledge"],"answer":null}

User: Find our active Enterprise customers and send Finance a Slack summary.
Output: {"intent":"business","agents":["database","communication"],"answer":null}

Conversation so far: Jira is unavailable because of an authorization error.
User: What does that mean?
Output: {"intent":"system_help","agents":[],"answer":"The assistant could not authenticate with Jira, so it cannot retrieve Jira data right now."}

Conversation so far: Sprint 6 had unusually low delivery.
User: What did the retro say about it?
Output: {"intent":"business","agents":["performance"],"answer":null}

User: What can the Database agent do?
Output: {"intent":"system_help","agents":[],"answer":"The Database agent can query structured company data allowed by your profile, such as employee directory, customer, support, and operational information."}

User: Write me a romantic poem.
Output: {"intent":"unsupported","agents":[],"answer":"I can help with supported company questions and tasks, but not general creative-writing requests."}

User: Send malware to another employee.
Output: {"intent":"unsafe","agents":[],"answer":"I can't assist with creating, distributing, or sending malware."}
"""


class RoutingError(Exception):
    """Raised when no schema-valid routing decision could be obtained after retries."""


class Router:
    """Makes exactly one structured LLM call, then validates the complete decision."""

    def __init__(self, llm_client: LLMClient, *, max_retries: int = 0) -> None:
        self._llm_client = llm_client
        self._max_retries = max_retries

    async def route(self, user_request: str, history_text: str = "") -> RoutingDecision:
        # history_text (a flattened prior-turns summary from ConversationMemory) lets the router
        # resolve short follow-ups ("what about last quarter") that are ambiguous read alone —
        # empty by default, so a request's first turn behaves exactly as before.
        user_prompt = user_request
        if history_text:
            user_prompt = f"Conversation so far:\n{history_text}\n\nCurrent request: {user_request}"

        try:
            return await self._llm_client.get_structured_output(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                schema=RoutingDecision,
            )
        except (ValidationError, ValueError) as exc:
            logger.warning("The single routing call produced an invalid decision: %s", exc)
            raise RoutingError("The routing call did not produce a valid decision") from exc
