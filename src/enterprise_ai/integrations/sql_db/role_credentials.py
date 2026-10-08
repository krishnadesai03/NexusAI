"""Derive a separate employee database login from the existing read-only master secret."""

from __future__ import annotations

import base64
import hashlib
import hmac
from urllib.parse import quote, urlsplit, urlunsplit

EXECUTIVE_READONLY_ROLE = "enterprise_ai_readonly"
EMPLOYEE_READONLY_ROLE = "enterprise_ai_employee_readonly"


def derive_employee_password(master_password: str) -> str:
    digest = hmac.new(
        master_password.encode("utf-8"),
        b"enterprise-ai/database-role/employee/v1",
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def replace_database_credentials(dsn: str, role: str, password: str) -> str:
    parts = urlsplit(dsn)
    username = parts.username or ""
    # Supabase's transaction/session pooler usernames have the form role.project-ref. Preserve
    # the project suffix while replacing only the PostgreSQL role name.
    suffix = username.partition(".")[2]
    replacement_username = f"{role}.{suffix}" if suffix else role
    hostname = parts.hostname or ""
    host = f"[{hostname}]" if ":" in hostname else hostname
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    netloc = f"{quote(replacement_username, safe='.')}:{quote(password, safe='')}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def employee_readonly_dsn(executive_dsn: str, master_password: str) -> str:
    return replace_database_credentials(
        executive_dsn,
        EMPLOYEE_READONLY_ROLE,
        derive_employee_password(master_password),
    )
