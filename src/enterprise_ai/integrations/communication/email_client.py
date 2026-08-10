from __future__ import annotations

import asyncio
import os
import re
import smtplib
from email.message import EmailMessage

# The 4 synthetic employees reused from Component 4 (learnings.md #4/#6) — each has a real,
# reachable test address of the form "<base-local>+<alias>@<base-domain>", built from the same
# authenticated account that sends the mail. Keeping this as a whitelist (not just a charset
# check) means a hallucinated alias for someone who isn't one of these 4 fails loudly as a tool
# error instead of silently landing on an address nobody was actually asking to reach.
KNOWN_RECIPIENT_ALIASES = frozenset({"priyanair", "marcuschen", "jordanlee", "sofiareyes"})

_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class InvalidRecipientAliasError(ValueError):
    """Raised when a requested recipient_alias isn't one of KNOWN_RECIPIENT_ALIASES — checked
    before any address is constructed, so this can never be used to reach anyone else."""


class EmailClient:
    """Sends email to a fixed, pre-approved test account (learnings.md #6). The LLM never
    supplies a full address — at most it supplies a `recipient_alias` for one of the 4 known
    synthetic employees, which this class combines with the *authenticated* SMTP account's own
    local-part/domain to build "<local>+<alias>@<domain>". Every possible resulting address is
    therefore still an alias of the same real mailbox this agent is authenticated as — there is
    no way to construct an address on a different domain or a different base account, so this
    preserves the original guardrail (can never reach a real external person) while allowing
    per-person addressing among the 4 known synthetic employees."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        username: str | None = None,
        app_password: str | None = None,
        from_address: str | None = None,
        recipient: str | None = None,
    ) -> None:
        self._smtp_host = smtp_host or os.environ["EMAIL_SMTP_HOST"]
        self._smtp_port = smtp_port or int(os.environ["EMAIL_SMTP_PORT"])
        self._username = username or os.environ["EMAIL_SMTP_USERNAME"]
        self._app_password = app_password or os.environ["EMAIL_SMTP_APP_PASSWORD"]
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
        local, domain = self._username.split("@", 1)
        return f"{local}+{recipient_alias}@{domain}"

    def _send_sync(self, subject: str, body: str, to_address: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._from_address
        message["To"] = to_address
        message.set_content(body)

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as smtp:
            smtp.starttls()
            smtp.login(self._username, self._app_password)
            smtp.send_message(message)

    async def send_email(self, subject: str, body: str, recipient_alias: str | None = None) -> dict:
        to_address = self._resolve_recipient(recipient_alias)
        await asyncio.to_thread(self._send_sync, subject, body, to_address)
        return {"to": to_address, "subject": subject}
