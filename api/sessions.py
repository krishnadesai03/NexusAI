"""In-memory session store: one entry per logged-in employee, mapping an opaque Bearer token to
that employee's own Orchestrator (and therefore their own ConversationMemory and their own
CommunicationAgent pending-action slot — see enterprise_ai.bootstrap for why those specifically
need to be per-session rather than shared).

Deliberately a plain dict, not Redis/Postgres — this project's session state has never persisted
across a process restart anywhere else either (learnings.md #7's ConversationMemory is the same
trade-off), so this isn't a new limitation, just the same one applied to a new layer. Revisit if
the backend ever needs to run as more than one process.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from enterprise_ai.orchestrator.orchestrator import Orchestrator

SESSION_TTL_HOURS = 24


@dataclass
class SessionState:
    token: str
    email: str
    display_name: str
    orchestrator: Orchestrator
    expires_at: datetime


class SessionStore:
    def __init__(self, ttl_hours: int = SESSION_TTL_HOURS) -> None:
        self._ttl = timedelta(hours=ttl_hours)
        self._sessions: dict[str, SessionState] = {}

    def create(self, *, email: str, display_name: str, orchestrator: Orchestrator) -> SessionState:
        token = secrets.token_urlsafe(32)
        session = SessionState(
            token=token,
            email=email,
            display_name=display_name,
            orchestrator=orchestrator,
            expires_at=datetime.now(timezone.utc) + self._ttl,
        )
        self._sessions[token] = session
        return session

    def get(self, token: str) -> SessionState | None:
        session = self._sessions.get(token)
        if session is None:
            return None
        if session.expires_at < datetime.now(timezone.utc):
            del self._sessions[token]
            return None
        return session

    def delete(self, token: str) -> None:
        self._sessions.pop(token, None)
