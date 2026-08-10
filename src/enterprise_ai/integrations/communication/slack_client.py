from __future__ import annotations

import os

import httpx

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


class SlackSendError(RuntimeError):
    """Raised when Slack's API itself reports failure — it returns HTTP 200 even on error, with
    the real result in a JSON "ok" field, so a status-code check alone wouldn't catch this."""


class SlackClient:
    """Sends messages to a single, fixed, pre-approved test channel (learnings.md #6). The
    channel is set here from config, never passed in from a caller/LLM argument — this is what
    makes it structurally impossible for the agent to be directed to post anywhere else."""

    def __init__(self, bot_token: str | None = None, channel_id: str | None = None) -> None:
        self._bot_token = bot_token or os.environ["SLACK_BOT_TOKEN"]
        self._channel_id = channel_id or os.environ["SLACK_TEST_CHANNEL_ID"]

    async def send_message(self, text: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _SLACK_POST_MESSAGE_URL,
                headers={"Authorization": f"Bearer {self._bot_token}"},
                json={"channel": self._channel_id, "text": text},
            )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise SlackSendError(f"Slack API rejected the message: {payload.get('error')}")
        return {"channel": self._channel_id, "ts": payload.get("ts")}
