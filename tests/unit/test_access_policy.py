from __future__ import annotations

import pytest

from scripts.seed_database_data import generate_all
from enterprise_ai.access_policy import (
    MATT_DAVIDSON,
    SOFIA_REYES,
    AccessDeniedError,
    Capability,
    Role,
    get_demo_persona,
    has_capability,
    require_capability,
)


def test_canonical_demo_personas_match_synthetic_company_data():
    assert SOFIA_REYES.display_name == "Sofia Reyes"
    assert SOFIA_REYES.title == "Software Engineer"
    assert SOFIA_REYES.role is Role.EMPLOYEE
    assert SOFIA_REYES.department == "Engineering"
    assert SOFIA_REYES.employee_id == 4

    assert MATT_DAVIDSON.display_name == "Matt Davidson"
    assert MATT_DAVIDSON.title == "Chief Executive Officer"
    assert MATT_DAVIDSON.role is Role.EXECUTIVE
    assert MATT_DAVIDSON.department == "Executive Office"
    assert MATT_DAVIDSON.employee_id == 46

    employee_rows = {employee.id: employee for employee in generate_all()["employees"]}
    matt = employee_rows[MATT_DAVIDSON.employee_id]
    assert matt.name == MATT_DAVIDSON.display_name
    assert matt.role == MATT_DAVIDSON.title


def test_both_personas_can_read_engineering_performance_data():
    capability = Capability.PERFORMANCE_READ_ENGINEERING
    assert has_capability(SOFIA_REYES, capability)
    assert has_capability(MATT_DAVIDSON, capability)


def test_employee_and_executive_knowledge_boundaries_differ():
    assert has_capability(SOFIA_REYES, Capability.KNOWLEDGE_READ_COMPANY)
    assert has_capability(SOFIA_REYES, Capability.KNOWLEDGE_READ_OWN_DEPARTMENT)
    assert not has_capability(SOFIA_REYES, Capability.KNOWLEDGE_READ_EXECUTIVE)

    assert has_capability(MATT_DAVIDSON, Capability.KNOWLEDGE_READ_COMPANY)
    assert has_capability(MATT_DAVIDSON, Capability.KNOWLEDGE_READ_ALL_DEPARTMENTS)
    assert has_capability(MATT_DAVIDSON, Capability.KNOWLEDGE_READ_EXECUTIVE)


def test_employee_cannot_receive_executive_database_capability():
    with pytest.raises(AccessDeniedError):
        require_capability(SOFIA_REYES, Capability.DATABASE_READ_COMPANY_FINANCIALS)

    require_capability(MATT_DAVIDSON, Capability.DATABASE_READ_COMPANY_FINANCIALS)


def test_communication_is_simulated_for_both_personas():
    for persona in (SOFIA_REYES, MATT_DAVIDSON):
        assert has_capability(persona, Capability.COMMUNICATION_DRAFT)
        assert has_capability(persona, Capability.COMMUNICATION_SIMULATE_DELIVERY)


def test_unknown_demo_persona_is_rejected():
    with pytest.raises(ValueError, match="Unknown demo persona"):
        get_demo_persona("unknown")
