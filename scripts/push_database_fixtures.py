"""Pushes the synthetic dataset from seed_database_data.py into the real Postgres instance
(Component 5), in its own `company_data` schema — separate from pgvector's `knowledge_chunks`
table, same Postgres container (avoids running a second database, same reasoning as the
pgvector decision for Component 3).

Also creates a dedicated READ-ONLY Postgres role (DATABASE_READONLY_URL) that DatabaseAgent
connects as. This is the real safety guardrail: even if the agent generated a harmful query,
that role is physically incapable of doing anything but SELECT — enforced by Postgres itself,
not by trusting the agent's own behavior.

Usage: .venv/Scripts/python.exe scripts/push_database_fixtures.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from seed_database_data import generate_all  # noqa: E402

READONLY_ROLE = "enterprise_ai_readonly"
READONLY_PASSWORD = "enterprise_ai_readonly"

SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS company_data;

CREATE TABLE IF NOT EXISTS company_data.departments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    budget NUMERIC(12,2) NOT NULL,
    head_employee_id INTEGER
);

CREATE TABLE IF NOT EXISTS company_data.employees (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES company_data.departments(id),
    role TEXT NOT NULL,
    salary NUMERIC(12,2) NOT NULL,
    hire_date DATE NOT NULL,
    manager_id INTEGER REFERENCES company_data.employees(id)
);

CREATE TABLE IF NOT EXISTS company_data.customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    signup_date DATE NOT NULL,
    account_tier TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_data.deals (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES company_data.customers(id),
    sales_rep_id INTEGER NOT NULL REFERENCES company_data.employees(id),
    amount NUMERIC(12,2) NOT NULL,
    stage TEXT NOT NULL,
    close_date DATE
);

CREATE TABLE IF NOT EXISTS company_data.subscriptions (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES company_data.customers(id),
    plan TEXT NOT NULL,
    monthly_revenue NUMERIC(12,2) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_data.expenses (
    id INTEGER PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES company_data.departments(id),
    category TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS company_data.budgets (
    id INTEGER PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES company_data.departments(id),
    fiscal_year INTEGER NOT NULL,
    allocated_amount NUMERIC(12,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS company_data.support_tickets (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES company_data.customers(id),
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    created_date DATE NOT NULL,
    resolved_date DATE,
    assigned_employee_id INTEGER REFERENCES company_data.employees(id)
);
"""


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def _ensure_readonly_role(conn: asyncpg.Connection) -> None:
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", READONLY_ROLE)
    if not exists:
        await conn.execute(f"CREATE ROLE {READONLY_ROLE} LOGIN PASSWORD '{READONLY_PASSWORD}'")
    await conn.execute(f"GRANT USAGE ON SCHEMA company_data TO {READONLY_ROLE}")
    await conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA company_data TO {READONLY_ROLE}")
    await conn.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA company_data GRANT SELECT ON TABLES TO {READONLY_ROLE}"
    )


async def _clear_tables(conn: asyncpg.Connection) -> None:
    # Reverse FK order — children before parents. Safe to call on a fresh or re-seeded schema.
    for table in [
        "support_tickets", "budgets", "expenses", "subscriptions", "deals", "customers", "employees", "departments",
    ]:
        await conn.execute(f"TRUNCATE company_data.{table} RESTART IDENTITY CASCADE")


async def main() -> None:
    _load_dotenv(ROOT / ".env")
    dsn = os.environ["DATABASE_URL"]

    data = generate_all()
    print("Generated: " + ", ".join(f"{k}={len(v)}" for k, v in data.items()))

    conn = await asyncpg.connect(dsn)
    try:
        print("\nCreating schema/tables...")
        await conn.execute(SCHEMA_DDL)

        print("Creating read-only role...")
        await _ensure_readonly_role(conn)

        print("Clearing existing rows (idempotent re-seed)...")
        await _clear_tables(conn)

        print("Inserting departments...")
        await conn.executemany(
            "INSERT INTO company_data.departments (id, name, budget) VALUES ($1, $2, $3)",
            [(d.id, d.name, d.budget) for d in data["departments"]],
        )

        print("Inserting employees...")
        # manager_id is self-referential (an employee's manager is also an employee) — insert
        # with it NULL first, since a manager can be inserted after the people who report to
        # them within the same batch, then fill it in once every employee row exists.
        await conn.executemany(
            "INSERT INTO company_data.employees (id, name, department_id, role, salary, hire_date) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            [(e.id, e.name, e.department_id, e.role, e.salary, e.hire_date) for e in data["employees"]],
        )
        await conn.executemany(
            "UPDATE company_data.employees SET manager_id = $2 WHERE id = $1",
            [(e.id, e.manager_id) for e in data["employees"] if e.manager_id],
        )

        print("Setting department heads...")
        await conn.executemany(
            "UPDATE company_data.departments SET head_employee_id = $2 WHERE id = $1",
            [(d.id, d.head_employee_id) for d in data["departments"] if d.head_employee_id],
        )

        print("Inserting customers...")
        await conn.executemany(
            "INSERT INTO company_data.customers (id, name, industry, signup_date, account_tier) "
            "VALUES ($1, $2, $3, $4, $5)",
            [(c.id, c.name, c.industry, c.signup_date, c.account_tier) for c in data["customers"]],
        )

        print("Inserting deals...")
        await conn.executemany(
            "INSERT INTO company_data.deals (id, customer_id, sales_rep_id, amount, stage, close_date) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            [(d.id, d.customer_id, d.sales_rep_id, d.amount, d.stage, d.close_date) for d in data["deals"]],
        )

        print("Inserting subscriptions...")
        await conn.executemany(
            "INSERT INTO company_data.subscriptions (id, customer_id, plan, monthly_revenue, start_date, end_date, status) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            [
                (s.id, s.customer_id, s.plan, s.monthly_revenue, s.start_date, s.end_date, s.status)
                for s in data["subscriptions"]
            ],
        )

        print("Inserting expenses...")
        await conn.executemany(
            "INSERT INTO company_data.expenses (id, department_id, category, amount, date) VALUES ($1, $2, $3, $4, $5)",
            [(e.id, e.department_id, e.category, e.amount, e.date) for e in data["expenses"]],
        )

        print("Inserting budgets...")
        await conn.executemany(
            "INSERT INTO company_data.budgets (id, department_id, fiscal_year, allocated_amount) VALUES ($1, $2, $3, $4)",
            [(b.id, b.department_id, b.fiscal_year, b.allocated_amount) for b in data["budgets"]],
        )

        print("Inserting support tickets...")
        await conn.executemany(
            "INSERT INTO company_data.support_tickets "
            "(id, customer_id, priority, status, created_date, resolved_date, assigned_employee_id) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            [
                (t.id, t.customer_id, t.priority, t.status, t.created_date, t.resolved_date, t.assigned_employee_id)
                for t in data["support_tickets"]
            ],
        )

        print("\nDone.")
    finally:
        await conn.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
