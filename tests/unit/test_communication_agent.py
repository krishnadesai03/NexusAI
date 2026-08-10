from __future__ import annotations

from enterprise_ai.agents.communication.agent import CommunicationAgent
from enterprise_ai.core.llm_client import ToolCall, ToolResponse
from enterprise_ai.core.llm_retry import LLM_CALL_MAX_ATTEMPTS


class FakeLLMClient:
    def __init__(self, responses: list[ToolResponse]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def get_structured_output(self, **kwargs):
        raise NotImplementedError

    async def get_tool_response(self, *, messages, tools):
        self.calls.append(messages)
        return self._responses.pop(0)


class FlakyLLMClient:
    def __init__(self, fail_times: int, then: ToolResponse):
        self._fail_times = fail_times
        self._then = then
        self.attempts = 0

    async def get_structured_output(self, **kwargs):
        raise NotImplementedError

    async def get_tool_response(self, *, messages, tools):
        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise ConnectionError("simulated network failure")
        return self._then


class FakeSlackClient:
    def __init__(self, raise_error: Exception | None = None):
        self._raise_error = raise_error
        self.sent: list[str] = []

    async def send_message(self, text: str) -> dict:
        if self._raise_error:
            raise self._raise_error
        self.sent.append(text)
        return {"channel": "C_TEST", "ts": "123.456"}


class FakeEmailClient:
    def __init__(self, raise_error: Exception | None = None):
        self._raise_error = raise_error
        self.sent: list[tuple[str, str, str | None]] = []

    async def send_email(self, subject: str, body: str, recipient_alias: str | None = None) -> dict:
        if self._raise_error:
            raise self._raise_error
        if recipient_alias is not None and recipient_alias not in {"priyanair", "marcuschen", "jordanlee", "sofiareyes"}:
            raise ValueError(f"{recipient_alias!r} is not a known recipient alias.")
        self.sent.append((subject, body, recipient_alias))
        to = f"test+{recipient_alias}@example.com" if recipient_alias else "test@example.com"
        return {"to": to, "subject": subject}


def _make_agent(llm_client, slack_client=None, email_client=None):
    return CommunicationAgent(
        llm_client=llm_client,
        slack_client=slack_client or FakeSlackClient(),
        email_client=email_client or FakeEmailClient(),
    )


def _slack_tool_response(text: str, call_id: str = "call_1") -> ToolResponse:
    return ToolResponse(content=None, tool_calls=[ToolCall(id=call_id, name="send_slack_message", arguments={"text": text})])


async def test_answers_immediately_when_no_send_needed():
    llm = FakeLLMClient([ToolResponse(content="Sure, what would you like me to send?")])
    agent = _make_agent(llm)

    result = await agent.handle("what can you do?")

    assert result.agent_name == "communication"
    assert result.content == "Sure, what would you like me to send?"
    assert result.metadata == {"citations": []}
    assert agent.has_pending() is False


async def test_stages_slack_send_instead_of_executing_immediately():
    slack = FakeSlackClient()
    llm = FakeLLMClient([_slack_tool_response("Standup at 10am.")])
    agent = _make_agent(llm, slack_client=slack)

    result = await agent.handle("tell the team standup is at 10am")

    assert result.metadata["requires_confirmation"] is True
    assert "Standup at 10am." in result.content
    assert slack.sent == []  # nothing actually sent yet
    assert agent.has_pending() is True


async def test_confirm_pending_executes_the_staged_slack_send():
    slack = FakeSlackClient()
    llm = FakeLLMClient([_slack_tool_response("Standup at 10am.")])
    agent = _make_agent(llm, slack_client=slack)
    await agent.handle("tell the team standup is at 10am")

    result = await agent.confirm_pending()

    assert result.content == "Done — sent as confirmed."
    assert slack.sent == ["Standup at 10am."]
    assert agent.has_pending() is False


async def test_confirm_pending_executes_staged_email_with_alias():
    email = FakeEmailClient()
    llm = FakeLLMClient(
        [
            ToolResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="send_email",
                        arguments={"subject": "Hi", "body": "Quick note.", "recipient_alias": "priyanair"},
                    )
                ],
            )
        ]
    )
    agent = _make_agent(llm, email_client=email)
    staged = await agent.handle("email Priya Nair a quick note")
    assert "priyanair" in staged.content

    result = await agent.confirm_pending()

    assert result.content == "Done — sent as confirmed."
    assert email.sent == [("Hi", "Quick note.", "priyanair")]
    assert result.metadata["citations"] == ['send_email: {"to": "test+priyanair@example.com", "subject": "Hi"}']


async def test_cancel_pending_discards_without_sending():
    slack = FakeSlackClient()
    llm = FakeLLMClient([_slack_tool_response("Standup at 10am.")])
    agent = _make_agent(llm, slack_client=slack)
    await agent.handle("tell the team standup is at 10am")

    result = agent.cancel_pending()

    assert result.content == "Cancelled — nothing was sent."
    assert slack.sent == []
    assert agent.has_pending() is False


async def test_confirm_with_nothing_pending_is_safe():
    agent = _make_agent(FakeLLMClient([]))

    result = await agent.confirm_pending()

    assert result.content == "There's nothing pending to confirm."


async def test_revise_pending_produces_new_staged_draft():
    llm = FakeLLMClient(
        [
            _slack_tool_response("Standup at 10am."),
            _slack_tool_response("Standup moved to 11am.", call_id="call_2"),
        ]
    )
    agent = _make_agent(llm)
    await agent.handle("tell the team standup is at 10am")

    result = await agent.revise_pending("actually make it 11am")

    assert result.metadata["requires_confirmation"] is True
    assert "11am" in result.content
    assert agent.has_pending() is True  # still pending, now with the revised draft


async def test_revise_pending_with_no_tool_call_cancels_and_returns_text():
    llm = FakeLLMClient(
        [
            _slack_tool_response("Standup at 10am."),
            ToolResponse(content="I'm not sure what change you want — nothing was sent."),
        ]
    )
    agent = _make_agent(llm)
    await agent.handle("tell the team standup is at 10am")

    result = await agent.revise_pending("uh, something different I guess")

    assert result.content == "I'm not sure what change you want — nothing was sent."
    assert agent.has_pending() is False


async def test_confirm_reports_send_error_and_clears_pending():
    slack = FakeSlackClient(raise_error=RuntimeError("Slack API rejected the message: channel_not_found"))
    llm = FakeLLMClient([_slack_tool_response("hi")])
    agent = _make_agent(llm, slack_client=slack)
    await agent.handle("message the team")

    result = await agent.confirm_pending()

    assert "channel_not_found" in result.content
    assert agent.has_pending() is False


async def test_recovers_after_transient_llm_failures_within_retry_budget():
    llm = FlakyLLMClient(fail_times=LLM_CALL_MAX_ATTEMPTS - 1, then=ToolResponse(content="Recovered answer."))
    agent = _make_agent(llm)

    result = await agent.handle("what can you do?")

    assert result.content == "Recovered answer."
    assert llm.attempts == LLM_CALL_MAX_ATTEMPTS


async def test_gives_up_with_clean_message_after_persistent_llm_failures():
    llm = FlakyLLMClient(fail_times=LLM_CALL_MAX_ATTEMPTS, then=ToolResponse(content="never reached"))
    agent = _make_agent(llm)

    result = await agent.handle("what can you do?")

    assert "couldn't reach the AI service" in result.content
    assert llm.attempts == LLM_CALL_MAX_ATTEMPTS
