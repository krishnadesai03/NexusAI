from __future__ import annotations

import os
import re
from datetime import date, datetime
from decimal import Decimal

import asyncpg

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5_000

# The real guardrail is the database role itself (created by push_database_fixtures.py with
# only SELECT granted, nothing else) — even a bypassed check here can't do anything harmful,
# since Postgres itself will refuse. This is a cheap secondary check, not the actual defense —
# it just fails fast with a clear message instead of waiting on a DB round-trip.
_FORBIDDEN_PATTERN = re.compile(
    r"""
    \b(
        INSERT | UPDATE | DELETE | MERGE | TRUNCATE
      | CREATE | ALTER  | DROP   | GRANT | REVOKE
      | COMMENT | REINDEX | VACUUM | REFRESH
      | COPY \s+ .*? \bFROM
      | SELECT \s+ .*? \bINTO
    )\b
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


class ReadOnlyViolationError(ValueError):
    """Raised when a query isn't a plain read — checked before ever reaching the database."""


def _validate_readonly_query(sql: str) -> None:
    normalized = sql.strip().lower()
    if not (normalized.startswith("select") or normalized.startswith("with")):
        raise ReadOnlyViolationError("Only SELECT (or WITH ... SELECT) queries are allowed.")
    match = _FORBIDDEN_PATTERN.search(sql)
    if match:
        raise ReadOnlyViolationError(
            f"Query contains a forbidden keyword ({match.group(1)!r}) — only read queries are allowed."
        )


def _serialize_value(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class PostgresQueryClient:
    """Read-only access to the company_data schema (learnings.md #5). Connects using
    DATABASE_READONLY_URL — a dedicated Postgres role granted SELECT only, created by
    push_database_fixtures.py. That role is the real safety guardrail: even if a harmful
    query somehow got past _validate_readonly_query, Postgres itself would still refuse it."""

    def __init__(self, pool: asyncpg.Pool, schema: str = "company_data") -> None:
        self._pool = pool
        self._schema = schema

    @classmethod
    async def connect(cls, dsn: str | None = None, schema: str = "company_data") -> "PostgresQueryClient":
        dsn = dsn or os.environ["DATABASE_READONLY_URL"]

        async def _init_connection(conn: asyncpg.Connection) -> None:
            await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")

        pool = await asyncpg.create_pool(dsn, init=_init_connection)
        return cls(pool, schema=schema)

    async def get_schema_description(self) -> str:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = $1
                ORDER BY table_name, ordinal_position
                """,
                self._schema,
            )

            # For low-cardinality text columns (status/tier/stage/category-style), also list
            # the real distinct values — confirmed live that without this, the LLM guesses at
            # exact casing/spelling (e.g. wrote 'active' when the real value is 'Active') and
            # silently gets zero matching rows instead of an error, which is worse than a
            # crash: it looks like a valid "no data" answer instead of a wrong query.
            distinct_values: dict[tuple[str, str], list[str]] = {}
            text_columns = [r for r in rows if r["data_type"] in ("text", "character varying")]
            for row in text_columns:
                table, column = row["table_name"], row["column_name"]
                count = await conn.fetchval(
                    f'SELECT COUNT(DISTINCT "{column}") FROM {self._schema}."{table}"'
                )
                if count is not None and count <= 15:
                    values = await conn.fetch(
                        f'SELECT DISTINCT "{column}" FROM {self._schema}."{table}" ORDER BY 1'
                    )
                    distinct_values[(table, column)] = [v[column] for v in values]

        lines = []
        current_table = None
        for row in rows:
            if row["table_name"] != current_table:
                current_table = row["table_name"]
                lines.append(f"\nTable: {self._schema}.{current_table}")
            line = f"  {row['column_name']} ({row['data_type']})"
            values = distinct_values.get((row["table_name"], row["column_name"]))
            if values:
                line += f" — actual values: {values}"
            lines.append(line)
        return "\n".join(lines).strip()

    async def run_query(self, sql: str) -> dict:
        _validate_readonly_query(sql)

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)

        truncated = len(rows) > MAX_ROWS
        result_rows = [{k: _serialize_value(v) for k, v in dict(r).items()} for r in rows[:MAX_ROWS]]
        return {"row_count": len(rows), "truncated": truncated, "rows": result_rows}

    async def close(self) -> None:
        await self._pool.close()
