"""Apply the repository's SQL migrations to DATABASE_URL in filename order."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "supabase" / "migrations"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def main() -> None:
    _load_dotenv(ROOT / ".env")
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS public.app_schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            applied = await connection.fetchval(
                "SELECT 1 FROM public.app_schema_migrations WHERE filename = $1",
                migration.name,
            )
            if applied:
                print(f"Already applied: {migration.name}")
                continue
            async with connection.transaction():
                await connection.execute(migration.read_text())
                await connection.execute(
                    "INSERT INTO public.app_schema_migrations (filename) VALUES ($1)",
                    migration.name,
                )
            print(f"Applied: {migration.name}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
