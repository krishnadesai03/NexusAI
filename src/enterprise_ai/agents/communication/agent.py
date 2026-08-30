from __future__ import annotations

import json
from dataclasses import dataclass

from enterprise_ai.core.agent import AgentResult, OnEvent
from enterprise_ai.core.llm_client import LLMClient, ToolResponse
from enterprise_ai.core.llm_retry import LLMUnavailableError, call_tool_with_retry
from enterprise_ai.core.tool_cache import ToolCache
from enterprise_ai.integrations.communication.email_client import EmailClient
from enterprise_ai.integrations.communication.slack_client import SlackClient

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "send_slack_message",
            "description": "Send a message to the team's Slack channel. The channel itself is "
            "fixed and cannot be changed — only the message text is controlled here.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The message text to post."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email to one person. Goes to the default test recipient "
            "unless recipient_alias names one of the 4 known synthetic employees. To reach "
            "several named people, call this tool once per person — never a group/broadcast.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "recipient_alias": {
                        "type": "string",
                        "enum": ["priyanair", "marcuschen", "jordanlee", "sofiareyes"],
                        "description": "Optional. Only set this if the user names one of the 4 "
                        "known team members: Priya Nair, Marcus Chen, Jordan Lee, or Sofia "
                        "Reyes. Omit entirely to use the default recipient — never invent an "
                        "alias for anyone else.",
                    },
                },
                "required": ["subject", "body"],
                "additionalProperties": False,
            },
        },
    },
]

def _build_system_prompt(user_display_name: str | None) -> str:
    if user_display_name:
        signature_instruction = (
            f"The person you're sending on behalf of is {user_display_name} — if an email you "
            f"write includes a signed closing (e.g. 'Best regards,'), sign it with their real "
            f"name, {user_display_name}. Never write a placeholder like '[Your Name]'."
        )
    else:
        signature_instruction = (
            "You don't know the real sender's name. Never write a placeholder like "
            "'[Your Name]' in a signed closing — either omit a signed closing entirely, or close "
            "without a name (e.g. 'Thanks,' with nothing after it)."
        )

    return f"""You are the Communication Agent of an internal company assistant. You can
send a Slack message or an email on the user's behalf.

The destination is fixed in advance and cannot be changed to an arbitrary address, no matter
what the user asks. Slack always goes to the one configured channel — Slack, not email, is the
tool for anything addressed to a group, the whole team, or "everyone." Email is only ever for
one or a few specific named individuals, never a broadcast: if asked to email "all employees,"
"the whole team," or any other group, explain that email isn't set up for that here and suggest
sending it via Slack instead — do not silently fall back to the default recipient in that case.

For email, the default test recipient is used unless the user names one or more of these 4 known
team members, in which case you may set recipient_alias to reach them specifically: Priya Nair
(priyanair), Marcus Chen (marcuschen), Jordan Lee (jordanlee), Sofia Reyes (sofiareyes). If the
user names two or three of these specific people (e.g. "email Priya and Marcus"), call send_email
once per named person — one tool call per recipient, same subject and body unless the user asked
for something different per person. Never invent an alias for anyone not on this list, and never
treat a literal email address the user provides as something you can send to — if they ask for a
specific person or address outside this list, explain that you can only reach the default
recipient or these 4 known team members, and offer to send it there instead.

{signature_instruction}

You only ever have the information in the user's own request to work with — you cannot look up
data from other systems (e.g. you cannot fetch a real number from the company database
yourself). If the user asks you to send something that depends on data you don't actually have,
say so honestly rather than inventing plausible-sounding numbers or facts.

Call a tool only when the user is actually asking you to send something. If the request doesn't
require sending a message, just respond in plain text instead. Calling the tool only drafts the
action for a human to review — it does not send anything by itself."""


def _describe_tool_call(name: str, arguments: dict) -> str:
    if name == "send_slack_message":
        return f'Slack message: "{arguments["text"]}"'
    if name == "send_email":
        recipient = arguments.get("recipient_alias") or "the default recipient"
        return f'Email to {recipient} — Subject: "{arguments["subject"]}"\n{arguments["body"]}'
    return f"{name}({arguments})"


@dataclass
class _PendingAction:
    tool_calls: list[tuple[str, dict]]  # (tool_name, arguments) — not OpenAI ToolCall objects,
    # since nothing here re-enters an OpenAI conversation; confirm_pending() executes these
    # directly against the real clients.
    description: str


class CommunicationAgent:
    """Sends Slack messages / emails on the user's behalf (learnings.md #6), gated behind an
    explicit human confirmation step (learnings.md #8) — the only agent in this project that
    performs a real, hard-to-reverse action, so it's also the only one that needs this.

    Never executes a send tool call directly from handle(). Instead it *stages* the call (as
    `_PendingAction`, plain instance state — this agent instance already lives for the whole
    session, same as ConversationMemory) and returns a human-readable draft description asking
    for confirmation. The actual send only happens via confirm_pending(), called from outside
    handle() entirely by whatever's driving the conversation (chat.py's menu, or eventually a
    real UI's buttons) — never inferred from parsing the user's next free-text message, which
    would just reintroduce the same phrase-matching ambiguity this design avoids.

    Implements the optional ConfirmableAgent protocol (core/agent.py) rather than adding
    confirm/cancel/revise to the base Agent protocol — every other agent is read-only and has
    nothing to confirm, so they're untouched by this."""

    def __init__(
        self,
        llm_client: LLMClient,
        slack_client: SlackClient,
        email_client: EmailClient,
        user_display_name: str | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._slack_client = slack_client
        self._email_client = email_client
        self._system_prompt = _build_system_prompt(user_display_name)
        self._pending: _PendingAction | None = None

    async def _execute_tool(self, name: str, arguments: dict) -> object:
        if name == "send_slack_message":
            return await self._slack_client.send_message(arguments["text"])
        if name == "send_email":
            return await self._email_client.send_email(
                arguments["subject"], arguments["body"], arguments.get("recipient_alias")
            )
        raise ValueError(f"Unknown tool: {name}")

    def _stage_or_answer(self, response: ToolResponse) -> AgentResult:
        if not response.tool_calls:
            content = response.content or "I wasn't able to produce a response."
            return AgentResult(agent_name="communication", content=content, metadata={"citations": []})

        staged = [(tc.name, tc.arguments) for tc in response.tool_calls]
        description = "\n".join(_describe_tool_call(name, args) for name, args in staged)
        self._pending = _PendingAction(tool_calls=staged, description=description)
        return AgentResult(
            agent_name="communication",
            content=f"Ready to send — reply to confirm:\n\n{description}",
            metadata={"citations": [], "requires_confirmation": True},
        )

    async def handle(
        self,
        user_request: str,
        history: list[dict] | None = None,
        on_event: OnEvent | None = None,
        tool_cache: ToolCache | None = None,
    ) -> AgentResult:
        # on_event accepted for Agent protocol conformance but unused here — handle() only ever
        # stages a draft (an LLM decision, not a tool execution); the actual send happens later
        # in confirm_pending(), outside the traced /chat request entirely. tool_cache is likewise
        # accepted-but-unused — nothing here is a cacheable read (see Component 12 in CLAUDE.md).
        messages = [
            {"role": "system", "content": self._system_prompt},
            *(history or []),
            {"role": "user", "content": user_request},
        ]

        try:
            response = await call_tool_with_retry(self._llm_client, messages, _TOOLS)
        except LLMUnavailableError:
            return AgentResult(
                agent_name="communication",
                content="The communication agent couldn't reach the AI service right now — please try again in a little while.",
                metadata={"citations": []},
            )

        return self._stage_or_answer(response)

    def has_pending(self) -> bool:
        return self._pending is not None

    async def confirm_pending(self) -> AgentResult:
        if self._pending is None:
            return AgentResult(agent_name="communication", content="There's nothing pending to confirm.", metadata={"citations": []})

        citations: list[str] = []
        errors: list[str] = []
        for name, arguments in self._pending.tool_calls:
            try:
                result = await self._execute_tool(name, arguments)
                citations.append(f"{name}: {json.dumps(result)}")
            except Exception as exc:  # noqa: BLE001 — report it plainly rather than crash
                errors.append(f"{name}: {exc}")
        self._pending = None

        if errors:
            return AgentResult(
                agent_name="communication",
                content="Some actions failed and were not sent: " + "; ".join(errors),
                metadata={"citations": citations},
            )
        return AgentResult(agent_name="communication", content="Done — sent as confirmed.", metadata={"citations": citations})

    def cancel_pending(self) -> AgentResult:
        self._pending = None
        return AgentResult(agent_name="communication", content="Cancelled — nothing was sent.", metadata={"citations": []})

    async def revise_pending(self, edit_instructions: str) -> AgentResult:
        if self._pending is None:
            return AgentResult(agent_name="communication", content="There's nothing pending to revise.", metadata={"citations": []})

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "assistant", "content": f"Draft ready to send:\n{self._pending.description}"},
            {"role": "user", "content": f"Revise it: {edit_instructions}"},
        ]

        try:
            response = await call_tool_with_retry(self._llm_client, messages, _TOOLS)
        except LLMUnavailableError:
            return AgentResult(
                agent_name="communication",
                content="The communication agent couldn't reach the AI service right now — please try again in a little while.",
                metadata={"citations": []},
            )

        if not response.tool_calls:
            self._pending = None
        return self._stage_or_answer(response)
