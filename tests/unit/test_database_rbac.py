from __future__ import annotations

from urllib.parse import unquote, urlsplit

from enterprise_ai.integrations.sql_db.role_credentials import (
    EMPLOYEE_READONLY_ROLE,
    derive_employee_password,
    employee_readonly_dsn,
)


def test_employee_database_password_is_deterministic_and_distinct():
    master = "executive-master-password"
    first = derive_employee_password(master)
    second = derive_employee_password(master)

    assert first == second
    assert first != master
    assert len(first) >= 40


def test_employee_dsn_preserves_supabase_project_suffix_and_connection_target():
    executive_dsn = (
        "postgresql://enterprise_ai_readonly.project-ref:master%21pass@"
        "pooler.example.com:5432/postgres?sslmode=require"
    )

    result = urlsplit(employee_readonly_dsn(executive_dsn, "master!pass"))

    assert unquote(result.username or "") == f"{EMPLOYEE_READONLY_ROLE}.project-ref"
    assert result.hostname == "pooler.example.com"
    assert result.port == 5432
    assert result.path == "/postgres"
    assert result.query == "sslmode=require"
