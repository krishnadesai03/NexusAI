from __future__ import annotations

import os
import re

import httpx

# The 4 synthetic employees reused from Component 4 (learnings.md #4/#6) — each has a real,
# reachable test address of the form "<base-local>+<alias>@<base-domain>", built from the same
# verified sending address. Keeping this as a whitelist (not just a charset check) means a
# hallucinated alias for someone who isn't one of these 4 fails loudly as a tool error instead of
# silently landing on an address nobody was actually asking to reach.
KNOWN_RECIPIENT_ALIASES = frozenset({"priyanair", "marcuschen", "jordanlee", "sofiareyes"})

_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

_RESEND_SEND_URL = "https://api.resend.com/emails"


class EmailSendError(RuntimeError):
    """Raised when Resend's API itself reports failure (non-2xx response) — mirrors
    SlackClient's SlackSendError pattern (learnings.md #6)."""


class InvalidRecipientAliasError(ValueError):
    """Raised when a requested recipient_alias isn't one of KNOWN_RECIPIENT_ALIASES — checked
    before any address is constructed, so this can never be used to reach anyone else."""


class EmailClient:
    """Sends email via Resend's HTTP API (learnings.md #12 follow-up), not raw SMTP.

    SMTP was the original implementation, but live testing on Render surfaced a real bug: the
    outbound SMTP connection to smtp.gmail.com hung indefinitely with no error — Render (like
    many PaaS hosts) restricts/drops outbound SMTP traffic rather than refusing it outright, so
    the connection attempt never completed or failed, it just blocked the request forever. A
    plain HTTPS POST — the same transport SlackClient already uses successfully on this same
    host — sidesteps the problem entirely, since it isn't a restricted port/protocol.

    The LLM never supplies a full address — at most it supplies a `recipient_alias` for one of
    the 4 known synthetic employees, which this class combines with the *verified sending*
    address's local-part/domain to build "<local>+<alias>@<domain>". Every possible resulting
    address is therefore still an alias of the same real mailbox this agent sends as — there is
    no way to construct an address on a different domain or a different base account, preserving
    the original guardrail (can never reach a real external person) while allowing per-person
    addressing among the 4 known synthetic employees."""

    def __init__(
        self,
        api_key: str | None = None,
        from_address: str | None = None,
        recipient: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ["RESEND_API_KEY"]
        self._from_address = from_address or os.environ["EMAIL_FROM_ADDRESS"]
        self._recipient = recipient or os.environ["EMAIL_TEST_RECIPIENT"]

    def _resolve_recipient(self, recipient_alias: str | None) -> str:
        if recipient_alias is None:
            return self._recipient
        if recipient_alias not in KNOWN_RECIPIENT_ALIASES or not _ALIAS_PATTERN.match(recipient_alias):
            raise InvalidRecipientAliasError(
                f"{recipient_alias!r} is not a known recipient alias. Valid aliases: "
                f"{sorted(KNOWN_RECIPIENT_ALIASES)}."
            )
        local, domain = self._from_address.split("@", 1)
        return f"{local}+{recipient_alias}@{domain}"

    async def send_email(self, subject: str, body: str, recipient_alias: str | None = None) -> dict:
        to_address = self._resolve_recipient(recipient_alias)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _RESEND_SEND_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"from": self._from_address, "to": [to_address], "subject": subject, "text": body},
            )
        if resp.is_error:
            raise EmailSendError(f"Resend API rejected the email ({resp.status_code}): {resp.text}")
        payload = resp.json()
        return {"to": to_address, "subject": subject, "id": payload.get("id")}
