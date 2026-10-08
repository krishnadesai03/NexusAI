"""Canonical demo personas and their role-based capabilities.

This module contains policy only. API session creation and agent/tool enforcement consume this
policy in later 0.4.0 steps rather than defining permissions independently in each endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    EMPLOYEE = "employee"
    EXECUTIVE = "executive"


class Capability(StrEnum):
    KNOWLEDGE_READ_COMPANY = "knowledge.read_company"
    KNOWLEDGE_READ_OWN_DEPARTMENT = "knowledge.read_own_department"
    KNOWLEDGE_READ_ALL_DEPARTMENTS = "knowledge.read_all_departments"
    KNOWLEDGE_READ_EXECUTIVE = "knowledge.read_executive"

    PERFORMANCE_READ_ENGINEERING = "performance.read_engineering"

    DATABASE_READ_DIRECTORY = "database.read_directory"
    DATABASE_READ_SELF = "database.read_self"
    DATABASE_READ_SUPPORT_OPERATIONS = "database.read_support_operations"
    DATABASE_READ_ALL_EMPLOYEES = "database.read_all_employees"
    DATABASE_READ_COMPANY_FINANCIALS = "database.read_company_financials"
    DATABASE_READ_COMPANY_OPERATIONS = "database.read_company_operations"

    COMMUNICATION_DRAFT = "communication.draft"
    COMMUNICATION_SIMULATE_DELIVERY = "communication.simulate_delivery"


@dataclass(frozen=True)
class DemoPersona:
    slug: str
    display_name: str
    title: str
    role: Role
    department: str | None
    employee_id: int | None


@dataclass(frozen=True)
class AccessContext:
    role: Role
    department: str | None
    employee_id: int | None


def access_context_for(persona: DemoPersona) -> AccessContext:
    return AccessContext(
        role=persona.role,
        department=persona.department,
        employee_id=persona.employee_id,
    )


SOFIA_REYES = DemoPersona(
    slug="sofia-reyes",
    display_name="Sofia Reyes",
    title="Software Engineer",
    role=Role.EMPLOYEE,
    department="Engineering",
    employee_id=4,
)

MATT_DAVIDSON = DemoPersona(
    slug="matt-davidson",
    display_name="Matt Davidson",
    title="Chief Executive Officer",
    role=Role.EXECUTIVE,
    department="Executive Office",
    employee_id=46,
)

DEMO_PERSONAS: dict[str, DemoPersona] = {
    persona.slug: persona for persona in (SOFIA_REYES, MATT_DAVIDSON)
}


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.EMPLOYEE: frozenset(
        {
            Capability.KNOWLEDGE_READ_COMPANY,
            Capability.KNOWLEDGE_READ_OWN_DEPARTMENT,
            Capability.PERFORMANCE_READ_ENGINEERING,
            Capability.DATABASE_READ_DIRECTORY,
            Capability.DATABASE_READ_SELF,
            Capability.DATABASE_READ_SUPPORT_OPERATIONS,
            Capability.COMMUNICATION_DRAFT,
            Capability.COMMUNICATION_SIMULATE_DELIVERY,
        }
    ),
    Role.EXECUTIVE: frozenset(
        {
            Capability.KNOWLEDGE_READ_COMPANY,
            Capability.KNOWLEDGE_READ_ALL_DEPARTMENTS,
            Capability.KNOWLEDGE_READ_EXECUTIVE,
            Capability.PERFORMANCE_READ_ENGINEERING,
            Capability.DATABASE_READ_DIRECTORY,
            Capability.DATABASE_READ_ALL_EMPLOYEES,
            Capability.DATABASE_READ_COMPANY_FINANCIALS,
            Capability.DATABASE_READ_COMPANY_OPERATIONS,
            Capability.COMMUNICATION_DRAFT,
            Capability.COMMUNICATION_SIMULATE_DELIVERY,
        }
    ),
}


class AccessDeniedError(PermissionError):
    pass


def get_demo_persona(slug: str) -> DemoPersona:
    try:
        return DEMO_PERSONAS[slug]
    except KeyError as exc:
        raise ValueError(f"Unknown demo persona: {slug}") from exc


def has_capability(persona: DemoPersona, capability: Capability) -> bool:
    return capability in ROLE_CAPABILITIES[persona.role]


def require_capability(persona: DemoPersona, capability: Capability) -> None:
    if not has_capability(persona, capability):
        raise AccessDeniedError(
            f"{persona.display_name} does not have the required capability: {capability.value}"
        )
