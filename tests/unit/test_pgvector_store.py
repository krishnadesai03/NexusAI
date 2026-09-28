from unittest.mock import AsyncMock

import pytest

from enterprise_ai.integrations.vector_store import pgvector_store


@pytest.mark.asyncio
async def test_connect_discovers_supabase_vector_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_connection = AsyncMock()
    setup_connection.fetchval.return_value = "extensions"
    pool = AsyncMock()
    create_pool = AsyncMock(return_value=pool)
    register_vector = AsyncMock()

    monkeypatch.setattr(pgvector_store.asyncpg, "connect", AsyncMock(return_value=setup_connection))
    monkeypatch.setattr(pgvector_store.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(pgvector_store, "register_vector", register_vector)
    monkeypatch.setattr(pgvector_store.PgVectorStore, "_ensure_schema", AsyncMock())

    store = await pgvector_store.PgVectorStore.connect("postgresql://example")

    setup_connection.execute.assert_awaited_once_with("CREATE EXTENSION IF NOT EXISTS vector")
    setup_connection.close.assert_awaited_once()
    assert store._vector_schema == "extensions"

    init_connection = create_pool.await_args.kwargs["init"]
    pooled_connection = AsyncMock()
    await init_connection(pooled_connection)
    register_vector.assert_awaited_once_with(pooled_connection, schema="extensions")
