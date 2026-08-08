from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import asyncpg
from pgvector.asyncpg import register_vector


@dataclass
class RetrievedChunk:
    doc_id: str
    text: str
    metadata: dict
    similarity: float


class VectorStore(Protocol):
    """Abstract seam over wherever embedded chunks are stored/searched (learnings.md #3,
    decision 3) — lets agent logic be tested with a fake store instead of a real database."""

    async def upsert(self, *, doc_id: str, text: str, embedding: list[float], metadata: dict) -> None: ...

    async def query(self, *, embedding: list[float], top_k: int) -> list[RetrievedChunk]: ...


class PgVectorStore:
    """VectorStore backed by Postgres + the pgvector extension, chosen (learnings.md #3,
    decision 3) to consolidate vector search into the same Postgres instance Component 5 will
    use for company data, instead of running a separate dedicated vector database."""

    def __init__(self, pool: asyncpg.Pool, *, table: str = "knowledge_chunks", embedding_dim: int = 1536) -> None:
        self._pool = pool
        self._table = table
        self._embedding_dim = embedding_dim

    @classmethod
    async def connect(cls, dsn: str, *, table: str = "knowledge_chunks", embedding_dim: int = 1536) -> "PgVectorStore":
        async def _init_connection(conn: asyncpg.Connection) -> None:
            await register_vector(conn)

        pool = await asyncpg.create_pool(dsn, init=_init_connection)
        store = cls(pool, table=table, embedding_dim=embedding_dim)
        await store._ensure_schema()
        return store

    async def _ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table} (
                    doc_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding vector({self._embedding_dim}) NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            )

    async def upsert(self, *, doc_id: str, text: str, embedding: list[float], metadata: dict) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self._table} (doc_id, text, embedding, metadata)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (doc_id) DO UPDATE
                SET text = EXCLUDED.text, embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata
                """,
                doc_id,
                text,
                embedding,
                json.dumps(metadata),
            )

    async def query(self, *, embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT doc_id, text, metadata, 1 - (embedding <=> $1) AS similarity
                FROM {self._table}
                ORDER BY embedding <=> $1
                LIMIT $2
                """,
                embedding,
                top_k,
            )

        return [
            RetrievedChunk(
                doc_id=row["doc_id"],
                text=row["text"],
                metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else dict(row["metadata"]),
                similarity=row["similarity"],
            )
            for row in rows
        ]

    async def close(self) -> None:
        await self._pool.close()
