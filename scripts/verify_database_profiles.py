"""Verify that both demo profiles can use their intended database access paths.

Usage: .venv/Scripts/python.exe scripts/verify_database_profiles.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from enterprise_ai.integrations.sql_db.role_credentials import employee_readonly_dsn  # noqa: E402


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def _verify_executive() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_READONLY_URL"])
    try:
        employee_count = await conn.fetchval("SELECT count(*) FROM company_data.employees")
        engineering_salary_count = await conn.fetchval(
            """SELECT count(*)
               FROM company_data.employees AS e
               JOIN company_data.departments AS d ON d.id = e.department_id
               WHERE d.name = 'Engineering' AND e.salary IS NOT NULL"""
        )
        if employee_count != 46 or not engineering_salary_count:
            raise RuntimeError(
                f"Executive data check failed: employees={employee_count}, "
                f"engineering_salaries={engineering_salary_count}"
            )
        print(
            f"Matt/executive: OK ({employee_count} employees; "
            f"{engineering_salary_count} Engineering salaries visible)"
        )
    finally:
        await conn.close()


async def _verify_employee() -> None:
    dsn = employee_readonly_dsn(
        os.environ["DATABASE_READONLY_URL"], os.environ["DATABASE_READONLY_PASSWORD"]
    )
    conn = await asyncpg.connect(dsn)
    try:
        directory_count = await conn.fetchval("SELECT count(*) FROM company_employee.employees")
        own_profile = await conn.fetchrow(
            "SELECT id, name, salary FROM company_employee.own_employee_profile"
        )
        directory_columns = {
            row["column_name"]
            for row in await conn.fetch(
                """SELECT column_name
                   FROM information_schema.columns
                   WHERE table_schema = 'company_employee' AND table_name = 'employees'"""
            )
        }
        if directory_count != 46 or own_profile is None or own_profile["id"] != 4:
            raise RuntimeError(
                f"Employee data check failed: directory={directory_count}, own_profile={own_profile!r}"
            )
        if "salary" in directory_columns:
            raise RuntimeError("Employee directory unexpectedly exposes other employees' salaries")

        try:
            await conn.fetchval("SELECT count(*) FROM company_data.employees")
        except asyncpg.InsufficientPrivilegeError:
            pass
        else:
            raise RuntimeError("Employee role unexpectedly has access to company_data")

        print(
            f"Sofia/employee: OK ({directory_count} directory entries; own salary visible; "
            "other salaries protected)"
        )
    finally:
        await conn.close()


async def main() -> None:
    _load_dotenv(ROOT / ".env")
    await _verify_executive()
    await _verify_employee()


if __name__ == "__main__":
    asyncio.run(main())
