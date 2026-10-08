"""Temporary stand-in for Component 4's future ingestion job (learnings.md #3, decision 8).

Embeds the synthetic company-policy-style fixture docs in tests/fixtures/knowledge_docs/ into
pgvector so the Knowledge Agent has something real to retrieve against. This is not a permanent
part of the system — once Component 4 exists and can pull real documents, this script goes away.

Usage: docker compose up -d postgres, fill in .env (OPENAI_API_KEY), then run
    .venv/Scripts/python.exe scripts/seed_knowledge_fixtures.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "knowledge_docs"
ACCESS_MANIFEST_PATH = FIXTURES_DIR / "_access_manifest.json"
ALLOWED_ACCESS_SCOPES = {"company", "department", "executive"}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _load_access_manifest() -> dict[str, dict]:
    manifest = json.loads(ACCESS_MANIFEST_PATH.read_text(encoding="utf-8"))
    document_names = {
        path.name for path in FIXTURES_DIR.iterdir() if path.suffix in {".md", ".txt"}
    }
    manifest_names = set(manifest)

    missing = sorted(document_names - manifest_names)
    unknown = sorted(manifest_names - document_names)
    if missing or unknown:
        raise ValueError(
            f"Knowledge access manifest mismatch: missing={missing}, unknown={unknown}"
        )

    for filename, access in manifest.items():
        scope = access.get("access_scope")
        departments = access.get("departments")
        if scope not in ALLOWED_ACCESS_SCOPES:
            raise ValueError(f"Invalid access scope for {filename}: {scope!r}")
        if not isinstance(departments, list) or not all(
            isinstance(department, str) and department.strip() for department in departments
        ):
            raise ValueError(f"Invalid departments for {filename}: {departments!r}")
        if scope == "department" and not departments:
            raise ValueError(f"Department-scoped document has no department: {filename}")
        if scope != "department" and departments:
            raise ValueError(f"Only department-scoped documents may list departments: {filename}")

    return manifest


async def main() -> None:
    _load_dotenv(ROOT / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and fill in your key.")

    dsn = os.environ.get("DATABASE_URL", "postgresql://enterprise_ai:enterprise_ai@localhost:5432/enterprise_ai")

    from enterprise_ai.core.chunking import chunk_document
    from enterprise_ai.core.embedding_client import OpenAIEmbeddingClient
    from enterprise_ai.integrations.vector_store.pgvector_store import PgVectorStore

    embedding_client = OpenAIEmbeddingClient()
    store = await PgVectorStore.connect(dsn)
    access_manifest = _load_access_manifest()

    doc_count = 0
    chunk_count = 0
    for doc_path in sorted(FIXTURES_DIR.glob("*")):
        if doc_path.suffix not in (".md", ".txt"):
            continue

        text = doc_path.read_text(encoding="utf-8")
        chunks = chunk_document(text)
        access = access_manifest[doc_path.name]

        for i, chunk in enumerate(chunks):
            embedding = await embedding_client.embed(chunk)
            await store.upsert(
                doc_id=f"{doc_path.name}::{i}",
                text=chunk,
                embedding=embedding,
                metadata={
                    "source_file": doc_path.name,
                    "access_scope": access["access_scope"],
                    "departments": access["departments"],
                },
            )
            chunk_count += 1

        doc_count += 1
        print(f"Seeded {doc_path.name} ({len(chunks)} chunk(s))")

    await store.close()
    print(f"\nDone: {doc_count} documents, {chunk_count} chunks embedded into pgvector.")


if __name__ == "__main__":
    asyncio.run(main())
