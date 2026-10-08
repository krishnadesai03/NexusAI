from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class Conversation:
    id: UUID
    user_id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredTurn:
    id: int
    conversation_id: UUID
    user_request: str
    routed_to: list[str]
    results: dict
    created_at: datetime


@dataclass(frozen=True)
class PendingAction:
    id: UUID
    conversation_id: UUID
    turn_id: int
    user_id: UUID
    agent_name: str
    payload: dict
    status: str
    expires_at: datetime


@dataclass(frozen=True)
class DemoSession:
    id: UUID
    persona_slug: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class DemoDelivery:
    id: UUID
    demo_session_id: UUID
    persona_slug: str
    channel: str
    recipient: str
    subject: str | None
    content: str
    status: str
    created_at: datetime
    expires_at: datetime


class ConversationNotFoundError(LookupError):
    pass


class DemoSessionNotFoundError(LookupError):
    pass


class ConversationStore(Protocol):
    async def create_demo_session(
        self, token_hash: str, persona_slug: str, expires_at: datetime
    ) -> DemoSession: ...
    async def get_and_extend_demo_session(
        self, token_hash: str, expires_at: datetime
    ) -> DemoSession | None: ...
    async def create_demo_delivery(
        self,
        demo_session_id: UUID,
        persona_slug: str,
        channel: str,
        recipient: str,
        subject: str | None,
        content: str,
    ) -> DemoDelivery: ...
    async def list_demo_deliveries(self, demo_session_id: UUID) -> list[DemoDelivery]: ...
    async def is_auth_session_active(self, session_id: UUID) -> bool: ...
    async def get_profile(self, user_id: UUID) -> tuple[str, str] | None: ...
    async def create_conversation(self, user_id: UUID, title: str = "New conversation") -> Conversation: ...
    async def list_conversations(self, user_id: UUID) -> list[Conversation]: ...
    async def get_conversation(self, user_id: UUID, conversation_id: UUID) -> Conversation: ...
    async def delete_conversation(self, user_id: UUID, conversation_id: UUID) -> None: ...
    async def list_turns(self, user_id: UUID, conversation_id: UUID) -> list[StoredTurn]: ...
    async def recent_turns(self, user_id: UUID, conversation_id: UUID, limit: int) -> list[StoredTurn]: ...
    async def save_turn(
        self,
        user_id: UUID,
        conversation_id: UUID,
        user_request: str,
        routed_to: list[str],
        results: dict,
        pending_agent: str | None = None,
        pending_payload: dict | None = None,
    ) -> StoredTurn: ...
    async def get_pending(self, user_id: UUID, conversation_id: UUID) -> PendingAction | None: ...
    async def claim_pending(self, user_id: UUID, conversation_id: UUID, agent_name: str) -> PendingAction | None: ...
    async def replace_pending(self, pending: PendingAction, payload: dict, result: dict | None = None) -> None: ...
    async def resolve_pending(
        self, pending: PendingAction, status: str, result: dict
    ) -> None: ...
    async def close(self) -> None: ...


def _decode_json(value: object) -> dict:
    return json.loads(value) if isinstance(value, str) else dict(value)


def _conversation(row: asyncpg.Record) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row["owner_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _turn(row: asyncpg.Record) -> StoredTurn:
    return StoredTurn(
        id=row["id"],
        conversation_id=row["conversation_id"],
        user_request=row["user_request"],
        routed_to=list(row["routed_to"]),
        results=_decode_json(row["results"]),
        created_at=row["created_at"],
    )


def _pending(row: asyncpg.Record) -> PendingAction:
    return PendingAction(
        id=row["id"],
        conversation_id=row["conversation_id"],
        turn_id=row["turn_id"],
        user_id=row["owner_id"],
        agent_name=row["agent_name"],
        payload=_decode_json(row["payload"]),
        status=row["status"],
        expires_at=row["expires_at"],
    )


def _demo_session(row: asyncpg.Record) -> DemoSession:
    return DemoSession(
        id=row["id"],
        persona_slug=row["persona_slug"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        expires_at=row["expires_at"],
    )


def _demo_delivery(row: asyncpg.Record) -> DemoDelivery:
    return DemoDelivery(
        id=row["id"],
        demo_session_id=row["demo_session_id"],
        persona_slug=row["persona_slug"],
        channel=row["channel"],
        recipient=row["recipient"],
        subject=row["subject"],
        content=row["content"],
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


class PostgresConversationStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> PostgresConversationStore:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        return cls(pool)

    async def create_demo_session(
        self, token_hash: str, persona_slug: str, expires_at: datetime
    ) -> DemoSession:
        row = await self._pool.fetchrow(
            """
            INSERT INTO public.demo_sessions (token_hash, persona_slug, expires_at)
            VALUES ($1, $2, $3)
            RETURNING id, persona_slug, created_at, last_seen_at, expires_at
            """,
            token_hash,
            persona_slug,
            expires_at,
        )
        return _demo_session(row)

    async def get_and_extend_demo_session(
        self, token_hash: str, expires_at: datetime
    ) -> DemoSession | None:
        row = await self._pool.fetchrow(
            """
            UPDATE public.demo_sessions
            SET last_seen_at = now(), expires_at = $2
            WHERE token_hash = $1 AND expires_at > now()
            RETURNING id, persona_slug, created_at, last_seen_at, expires_at
            """,
            token_hash,
            expires_at,
        )
        return _demo_session(row) if row else None

    async def create_demo_delivery(
        self,
        demo_session_id: UUID,
        persona_slug: str,
        channel: str,
        recipient: str,
        subject: str | None,
        content: str,
    ) -> DemoDelivery:
        row = await self._pool.fetchrow(
            """
            INSERT INTO public.demo_deliveries
                (demo_session_id, persona_slug, channel, recipient, subject, content)
            SELECT id, persona_slug, $3, $4, $5, $6
            FROM public.demo_sessions
            WHERE id = $1 AND persona_slug = $2 AND expires_at > now()
            RETURNING id, demo_session_id, persona_slug, channel, recipient, subject, content,
                      status, created_at, expires_at
            """,
            demo_session_id,
            persona_slug,
            channel,
            recipient,
            subject,
            content,
        )
        if row is None:
            raise DemoSessionNotFoundError(str(demo_session_id))
        return _demo_delivery(row)

    async def list_demo_deliveries(self, demo_session_id: UUID) -> list[DemoDelivery]:
        rows = await self._pool.fetch(
            """
            SELECT id, demo_session_id, persona_slug, channel, recipient, subject, content,
                   status, created_at, expires_at
            FROM public.demo_deliveries
            WHERE demo_session_id = $1 AND expires_at > now()
            ORDER BY created_at DESC
            """,
            demo_session_id,
        )
        return [_demo_delivery(row) for row in rows]

    async def create_conversation(self, user_id: UUID, title: str = "New conversation") -> Conversation:
        demo = await self._pool.fetchrow(
            "SELECT persona_slug FROM public.demo_sessions WHERE id = $1 AND expires_at > now()",
            user_id,
        )
        if demo:
            row = await self._pool.fetchrow(
                """
                INSERT INTO public.conversations (demo_session_id, persona_slug, title)
                VALUES ($1, $2, $3)
                RETURNING id, demo_session_id AS owner_id, title, created_at, updated_at
                """,
                user_id,
                demo["persona_slug"],
                title,
            )
        else:
            row = await self._pool.fetchrow(
                """
                INSERT INTO public.conversations (user_id, title)
                VALUES ($1, $2)
                RETURNING id, user_id AS owner_id, title, created_at, updated_at
                """,
                user_id,
                title,
            )
        return _conversation(row)

    async def is_auth_session_active(self, session_id: UUID) -> bool:
        return bool(
            await self._pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM auth.sessions WHERE id = $1)",
                session_id,
            )
        )

    async def get_profile(self, user_id: UUID) -> tuple[str, str] | None:
        row = await self._pool.fetchrow(
            "SELECT display_name, employee_role FROM public.profiles WHERE id = $1",
            user_id,
        )
        if row is None:
            return None
        return row["display_name"], row["employee_role"]

    async def list_conversations(self, user_id: UUID) -> list[Conversation]:
        rows = await self._pool.fetch(
            """
            SELECT id, COALESCE(user_id, demo_session_id) AS owner_id,
                   title, created_at, updated_at
            FROM public.conversations
            WHERE (user_id = $1 OR demo_session_id = $1)
              AND (demo_session_id IS NULL OR updated_at > now() - interval '24 hours')
            ORDER BY updated_at DESC
            """,
            user_id,
        )
        return [_conversation(row) for row in rows]

    async def get_conversation(self, user_id: UUID, conversation_id: UUID) -> Conversation:
        row = await self._pool.fetchrow(
            """
            SELECT id, COALESCE(user_id, demo_session_id) AS owner_id,
                   title, created_at, updated_at
            FROM public.conversations
            WHERE id = $1 AND (user_id = $2 OR demo_session_id = $2)
              AND (demo_session_id IS NULL OR updated_at > now() - interval '24 hours')
            """,
            conversation_id,
            user_id,
        )
        if row is None:
            raise ConversationNotFoundError(str(conversation_id))
        return _conversation(row)

    async def delete_conversation(self, user_id: UUID, conversation_id: UUID) -> None:
        result = await self._pool.execute(
            """
            DELETE FROM public.conversations
            WHERE id = $1 AND (user_id = $2 OR demo_session_id = $2)
            """,
            conversation_id,
            user_id,
        )
        if result == "DELETE 0":
            raise ConversationNotFoundError(str(conversation_id))

    async def list_turns(self, user_id: UUID, conversation_id: UUID) -> list[StoredTurn]:
        await self.get_conversation(user_id, conversation_id)
        rows = await self._pool.fetch(
            """
            SELECT id, conversation_id, user_request, routed_to, results, created_at
            FROM public.conversation_turns
            WHERE conversation_id = $1 AND (user_id = $2 OR demo_session_id = $2)
            ORDER BY id
            """,
            conversation_id,
            user_id,
        )
        return [_turn(row) for row in rows]

    async def recent_turns(self, user_id: UUID, conversation_id: UUID, limit: int) -> list[StoredTurn]:
        await self.get_conversation(user_id, conversation_id)
        rows = await self._pool.fetch(
            """
            SELECT id, conversation_id, user_request, routed_to, results, created_at
            FROM (
                SELECT id, conversation_id, user_request, routed_to, results, created_at
                FROM public.conversation_turns
                WHERE conversation_id = $1 AND (user_id = $2 OR demo_session_id = $2)
                ORDER BY id DESC
                LIMIT $3
            ) AS recent
            ORDER BY id
            """,
            conversation_id,
            user_id,
            limit,
        )
        return [_turn(row) for row in rows]

    async def save_turn(
        self,
        user_id: UUID,
        conversation_id: UUID,
        user_request: str,
        routed_to: list[str],
        results: dict,
        pending_agent: str | None = None,
        pending_payload: dict | None = None,
    ) -> StoredTurn:
        async with self._pool.acquire() as connection, connection.transaction():
            owner = await connection.fetchrow(
                """
                SELECT user_id, demo_session_id
                FROM public.conversations
                WHERE id = $1 AND (user_id = $2 OR demo_session_id = $2)
                FOR UPDATE
                """,
                conversation_id,
                user_id,
            )
            if owner is None:
                raise ConversationNotFoundError(str(conversation_id))

            row = await connection.fetchrow(
                """
                INSERT INTO public.conversation_turns
                    (conversation_id, user_id, demo_session_id, user_request, routed_to, results)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                RETURNING id, conversation_id, user_request, routed_to, results, created_at
                """,
                conversation_id,
                owner["user_id"],
                owner["demo_session_id"],
                user_request,
                routed_to,
                json.dumps(results),
            )
            await connection.execute(
                """
                UPDATE public.conversations
                SET updated_at = now(),
                    title = CASE WHEN title = 'New conversation' THEN left($3, 80) ELSE title END
                WHERE id = $1 AND (user_id = $2 OR demo_session_id = $2)
                """,
                conversation_id,
                user_id,
                user_request,
            )
            if pending_agent is not None and pending_payload is not None:
                await connection.execute(
                    """
                    INSERT INTO public.pending_actions
                        (conversation_id, turn_id, user_id, demo_session_id, agent_name, payload)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                    """,
                    conversation_id,
                    row["id"],
                    owner["user_id"],
                    owner["demo_session_id"],
                    pending_agent,
                    json.dumps(pending_payload),
                )
        return _turn(row)

    async def get_pending(self, user_id: UUID, conversation_id: UUID) -> PendingAction | None:
        row = await self._pool.fetchrow(
            """
            SELECT id, conversation_id, turn_id,
                   COALESCE(user_id, demo_session_id) AS owner_id,
                   agent_name, payload, status, expires_at
            FROM public.pending_actions
            WHERE conversation_id = $1 AND (user_id = $2 OR demo_session_id = $2)
              AND status = 'pending' AND expires_at > now()
            ORDER BY created_at DESC
            LIMIT 1
            """,
            conversation_id,
            user_id,
        )
        return _pending(row) if row else None

    async def claim_pending(self, user_id: UUID, conversation_id: UUID, agent_name: str) -> PendingAction | None:
        row = await self._pool.fetchrow(
            """
            UPDATE public.pending_actions
            SET status = 'executing', updated_at = now()
            WHERE id = (
                SELECT id FROM public.pending_actions
                WHERE conversation_id = $1
                  AND (user_id = $2 OR demo_session_id = $2) AND agent_name = $3
                  AND status = 'pending' AND expires_at > now()
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, conversation_id, turn_id,
                      COALESCE(user_id, demo_session_id) AS owner_id,
                      agent_name, payload, status, expires_at
            """,
            conversation_id,
            user_id,
            agent_name,
        )
        return _pending(row) if row else None

    async def replace_pending(self, pending: PendingAction, payload: dict, result: dict | None = None) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            if result is not None:
                row = await connection.fetchrow(
                    """
                    SELECT results FROM public.conversation_turns
                    WHERE id = $1 AND (user_id = $2 OR demo_session_id = $2)
                    FOR UPDATE
                    """,
                    pending.turn_id,
                    pending.user_id,
                )
                if row is None:
                    raise ConversationNotFoundError(str(pending.conversation_id))
                results = _decode_json(row["results"])
                results[pending.agent_name] = result
                await connection.execute(
                    "UPDATE public.conversation_turns SET results = $2::jsonb WHERE id = $1",
                    pending.turn_id,
                    json.dumps(results),
                )
            await connection.execute(
                """
                UPDATE public.pending_actions
                SET payload = $2::jsonb, status = 'pending', updated_at = now(),
                    expires_at = now() + interval '24 hours'
                WHERE id = $1 AND status = 'executing'
                """,
                pending.id,
                json.dumps(payload),
            )

    async def resolve_pending(self, pending: PendingAction, status: str, result: dict) -> None:
        if status not in {"completed", "cancelled"}:
            raise ValueError(f"Invalid terminal pending status: {status}")
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                SELECT results FROM public.conversation_turns
                WHERE id = $1 AND (user_id = $2 OR demo_session_id = $2)
                FOR UPDATE
                """,
                pending.turn_id,
                pending.user_id,
            )
            if row is None:
                raise ConversationNotFoundError(str(pending.conversation_id))
            results = _decode_json(row["results"])
            results[pending.agent_name] = result
            await connection.execute(
                "UPDATE public.conversation_turns SET results = $2::jsonb WHERE id = $1",
                pending.turn_id,
                json.dumps(results),
            )
            await connection.execute(
                """
                UPDATE public.pending_actions
                SET status = $2, updated_at = now()
                WHERE id = $1 AND status = 'executing'
                """,
                pending.id,
                status,
            )
            await connection.execute(
                "UPDATE public.conversations SET updated_at = now() WHERE id = $1",
                pending.conversation_id,
            )

    async def close(self) -> None:
        await self._pool.close()
