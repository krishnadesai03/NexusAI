"""Safely verify the configured Supabase connection without printing its URL."""

import asyncio
from pathlib import Path

import asyncpg


def _get_env_value(env_path: Path, key: str) -> str:
    return next(
        line.split("=", 1)[1].strip()
        for line in env_path.read_text().splitlines()
        if line.strip().startswith(f"{key}=")
    )


async def main() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    admin_dsn = _get_env_value(env_path, "DATABASE_URL")
    readonly_dsn = _get_env_value(env_path, "DATABASE_READONLY_URL")

    connection = await asyncpg.connect(admin_dsn, timeout=15)
    try:
        vector_enabled = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
    finally:
        await connection.close()

    print("Supabase connection successful")
    print(f"pgvector enabled: {vector_enabled}")

    readonly_connection = await asyncpg.connect(readonly_dsn, timeout=15)
    try:
        employee_count = await readonly_connection.fetchval(
            "SELECT COUNT(*) FROM company_data.employees"
        )
        transaction = readonly_connection.transaction()
        await transaction.start()
        try:
            await readonly_connection.execute(
                "UPDATE company_data.departments SET name = name WHERE id = 1"
            )
        except asyncpg.InsufficientPrivilegeError:
            write_blocked = True
        else:
            write_blocked = False
        finally:
            await transaction.rollback()
    finally:
        await readonly_connection.close()

    if not write_blocked:
        raise RuntimeError("The read-only database role unexpectedly allowed an UPDATE")

    print(f"Read-only connection successful ({employee_count} employees visible)")
    print("Write access correctly blocked by PostgreSQL")


if __name__ == "__main__":
    asyncio.run(main())
