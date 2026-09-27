from unittest.mock import AsyncMock

import enterprise_ai.bootstrap as bootstrap


async def test_shared_resources_start_when_databases_are_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "default_llm_client", lambda: object())
    monkeypatch.setattr(bootstrap, "default_embedding_client", lambda: object())
    monkeypatch.setattr(bootstrap, "_performance_state_file", lambda: None)
    monkeypatch.setattr(bootstrap.PgVectorStore, "connect", AsyncMock(side_effect=TimeoutError))
    monkeypatch.setattr(bootstrap.PostgresQueryClient, "connect", AsyncMock(side_effect=TimeoutError))
    monkeypatch.setattr(bootstrap, "SlackClient", lambda: object())
    monkeypatch.setattr(bootstrap, "EmailClient", lambda: object())

    shared = await bootstrap.build_shared_resources()

    assert shared.vector_store is None
    knowledge_result = await shared.knowledge_agent.handle("What is the PTO policy?")
    database_result = await shared.database_agent.handle("What is Priya's salary?")
    assert "temporarily unavailable" in knowledge_result.content
    assert "hasn't been seeded" in database_result.content

    await bootstrap.close_shared_resources(shared)
