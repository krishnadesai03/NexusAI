"""Synthetic data GENERATOR for Component 5 (Database Agent) — pure Python, makes no DB calls,
touches nothing live. Produces all 8 tables' worth of rows as plain Python objects, deterministic
(fixed seed), so the shape/volume can be reviewed (via the preview block below) before anything
gets pushed to the real Postgres schema.

Reuses the same 4 synthetic employees from Component 4 (Priya Nair, Marcus Chen, Jordan Lee,
Sofia Reyes) inside Engineering, so the fictional "Alderbrook Systems" company is consistent
across both agents' data.

Usage (preview only, no side effects):
    .venv/Scripts/python.exe scripts/seed_database_data.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

RANDOM_SEED = 42

DEPARTMENTS = ["Engineering", "Sales", "Finance", "Customer Support", "Marketing", "People"]

ROLES_BY_DEPT = {
    "Engineering": ["Software Engineer", "Senior Software Engineer", "QA Engineer", "Engineering Manager"],
    "Sales": ["Sales Rep", "Senior Sales Rep", "Sales Manager"],
    "Finance": ["Financial Analyst", "Accountant", "Finance Manager"],
    "Customer Support": ["Support Agent", "Senior Support Agent", "Support Manager"],
    "Marketing": ["Marketing Specialist", "Content Manager", "Marketing Manager"],
    "People": ["HR Generalist", "Recruiter", "People Manager"],
}

SALARY_RANGE_BY_ROLE_LEVEL = {
    "manager": (115_000, 175_000),
    "senior": (95_000, 145_000),
    "ic": (70_000, 115_000),
}

FIRST_NAMES = [
    "Alex", "Jamie", "Taylor", "Morgan", "Casey", "Riley", "Jordan", "Avery", "Cameron", "Drew",
    "Elliot", "Harper", "Kendall", "Logan", "Parker", "Reese", "Rowan", "Sage", "Skyler", "Quinn",
    "Blake", "Emerson", "Finley", "Hayden", "Jesse", "Kai", "Micah", "Noel", "Peyton", "Sam",
    "Amara", "Devon", "Frankie", "Greer", "Indigo", "Jules", "Kit", "Lior", "Marlowe", "Nico",
]
LAST_NAMES = [
    "Anderson", "Bennett", "Cole", "Diaz", "Ellis", "Foster", "Gray", "Hayes", "Irwin", "Jensen",
    "Kane", "Lowry", "Mercer", "Nolan", "Ortiz", "Pierce", "Quinn", "Reyes", "Shaw", "Tate",
    "Vance", "Walsh", "Yates", "Zimmer", "Abbott", "Brooks", "Cross", "Dunn", "Everly", "Frost",
    "Grant", "Hale", "Ingram", "Jared", "Knox", "Lane", "Monroe", "Nash", "Osborn", "Powell",
]

CUSTOMER_NAME_POOL = [
    "Northwind", "Brightline", "Cobalt", "Everstream", "Fernwood", "Granite Peak", "Harbor Light",
    "Ironclad", "Junction", "Keystone", "Lumen", "Meridian", "Nimbus", "Outland", "Pinnacle",
    "Quarry", "Redshift", "Silverline", "Tidewater", "Underway", "Vantage", "Westbound", "Yonder",
    "Zenith", "Anchor Point", "Beacon Hill", "Crestview", "Drift", "Elmwood", "Foundry",
]
CUSTOMER_SUFFIXES = ["Inc.", "Co.", "Group", "Labs", "Partners", "Solutions", "Systems", "Holdings"]
INDUSTRIES = ["Software", "Healthcare", "Finance", "Retail", "Manufacturing", "Education", "Media", "Logistics"]
ACCOUNT_TIERS = ["Free", "Pro", "Enterprise"]
TIER_MRR_RANGE = {"Free": (0, 0), "Pro": (99, 499), "Enterprise": (1500, 8000)}

EXPENSE_CATEGORIES = ["Salaries", "Software & Tools", "Travel", "Marketing", "Office", "Equipment", "Other"]
SUPPORT_PRIORITIES = ["Low", "Medium", "High", "Critical"]
SUPPORT_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
DEAL_STAGES = ["Prospecting", "Negotiation", "Won", "Lost"]

KNOWN_ENGINEERS = ["Priya Nair", "Marcus Chen", "Jordan Lee", "Sofia Reyes"]


@dataclass
class Department:
    id: int
    name: str
    budget: float
    head_employee_id: int | None = None


@dataclass
class Employee:
    id: int
    name: str
    department_id: int
    role: str
    salary: float
    hire_date: date
    manager_id: int | None


@dataclass
class Customer:
    id: int
    name: str
    industry: str
    signup_date: date
    account_tier: str


@dataclass
class Deal:
    id: int
    customer_id: int
    sales_rep_id: int
    amount: float
    stage: str
    close_date: date | None


@dataclass
class Subscription:
    id: int
    customer_id: int
    plan: str
    monthly_revenue: float
    start_date: date
    end_date: date | None
    status: str


@dataclass
class Expense:
    id: int
    department_id: int
    category: str
    amount: float
    date: date


@dataclass
class Budget:
    id: int
    department_id: int
    fiscal_year: int
    allocated_amount: float


@dataclass
class SupportTicket:
    id: int
    customer_id: int
    priority: str
    status: str
    created_date: date
    resolved_date: date | None
    assigned_employee_id: int | None


def _role_level(role: str) -> str:
    if "Manager" in role:
        return "manager"
    if "Senior" in role:
        return "senior"
    return "ic"


def generate_departments() -> list[Department]:
    budgets = {
        "Engineering": 4_500_000,
        "Sales": 2_200_000,
        "Finance": 900_000,
        "Customer Support": 1_100_000,
        "Marketing": 1_500_000,
        "People": 700_000,
    }
    return [Department(id=i + 1, name=name, budget=budgets[name]) for i, name in enumerate(DEPARTMENTS)]


def generate_employees(departments: list[Department], rng: random.Random, total: int = 45) -> list[Employee]:
    dept_by_name = {d.name: d for d in departments}
    used_names: set[str] = set()
    employees: list[Employee] = []
    today = date.today()

    # Reuse the 4 known Performance Agent employees, all in Engineering.
    for name in KNOWN_ENGINEERS:
        used_names.add(name)
        role = rng.choice(ROLES_BY_DEPT["Engineering"])
        low, high = SALARY_RANGE_BY_ROLE_LEVEL[_role_level(role)]
        employees.append(
            Employee(
                id=len(employees) + 1,
                name=name,
                department_id=dept_by_name["Engineering"].id,
                role=role,
                salary=round(rng.uniform(low, high), -2),
                hire_date=today - timedelta(days=rng.randint(200, 1400)),
                manager_id=None,
            )
        )

    # Roughly proportional headcount per department (Engineering biggest, People smallest).
    # Weights are shares of the FULL target headcount, not the remaining pool — subtracting
    # the 4 known engineers from Engineering's share happens once, below, not twice.
    weights = {"Engineering": 0.30, "Sales": 0.20, "Customer Support": 0.20, "Marketing": 0.15, "Finance": 0.10, "People": 0.05}
    counts = {name: max(1, round(total * w)) for name, w in weights.items()}
    counts["Engineering"] -= len(KNOWN_ENGINEERS)  # already added above

    for dept_name, count in counts.items():
        dept = dept_by_name[dept_name]
        for _ in range(count):
            while True:
                name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
                if name not in used_names:
                    used_names.add(name)
                    break
            role = rng.choice(ROLES_BY_DEPT[dept_name])
            low, high = SALARY_RANGE_BY_ROLE_LEVEL[_role_level(role)]
            employees.append(
                Employee(
                    id=len(employees) + 1,
                    name=name,
                    department_id=dept.id,
                    role=role,
                    salary=round(rng.uniform(low, high), -2),
                    hire_date=today - timedelta(days=rng.randint(30, 1800)),
                    manager_id=None,
                )
            )

    # Assign each non-manager to a manager within their own department, if one exists.
    for dept in departments:
        dept_employees = [e for e in employees if e.department_id == dept.id]
        managers = [e for e in dept_employees if "Manager" in e.role]
        if not managers:
            continue
        for emp in dept_employees:
            if "Manager" not in emp.role:
                emp.manager_id = rng.choice(managers).id
        dept.head_employee_id = managers[0].id

    return employees


def generate_customers(rng: random.Random, total: int = 70) -> list[Customer]:
    today = date.today()
    used_names: set[str] = set()
    customers = []
    for i in range(total):
        while True:
            name = f"{rng.choice(CUSTOMER_NAME_POOL)} {rng.choice(CUSTOMER_SUFFIXES)}"
            if name not in used_names:
                used_names.add(name)
                break
        customers.append(
            Customer(
                id=i + 1,
                name=name,
                industry=rng.choice(INDUSTRIES),
                signup_date=today - timedelta(days=rng.randint(30, 1100)),
                account_tier=rng.choices(ACCOUNT_TIERS, weights=[0.2, 0.5, 0.3], k=1)[0],
            )
        )
    return customers


def generate_deals(customers: list[Customer], employees: list[Employee], rng: random.Random, total: int = 180) -> list[Deal]:
    sales_reps = [e for e in employees if "Sales" in e.role]
    deals = []
    for i in range(total):
        customer = rng.choice(customers)
        stage = rng.choices(DEAL_STAGES, weights=[0.15, 0.10, 0.40, 0.35], k=1)[0]
        tier_amount = {"Free": (500, 2000), "Pro": (2000, 15000), "Enterprise": (20000, 120000)}
        low, high = tier_amount[customer.account_tier]
        close_date = None
        if stage in ("Won", "Lost"):
            close_date = customer.signup_date + timedelta(days=rng.randint(5, 90))
        deals.append(
            Deal(
                id=i + 1,
                customer_id=customer.id,
                sales_rep_id=rng.choice(sales_reps).id,
                amount=round(rng.uniform(low, high), -2),
                stage=stage,
                close_date=close_date,
            )
        )
    return deals


def generate_subscriptions(customers: list[Customer], deals: list[Deal], rng: random.Random) -> list[Subscription]:
    won_deals = [d for d in deals if d.stage == "Won"]
    customers_by_id = {c.id: c for c in customers}
    subscriptions = []
    seen_customers: set[int] = set()

    for i, deal in enumerate(won_deals):
        if deal.customer_id in seen_customers:
            continue
        seen_customers.add(deal.customer_id)
        customer = customers_by_id[deal.customer_id]
        low, high = TIER_MRR_RANGE[customer.account_tier]
        status = rng.choices(["Active", "Cancelled"], weights=[0.8, 0.2], k=1)[0]
        start = deal.close_date or customer.signup_date
        end = start + timedelta(days=rng.randint(60, 500)) if status == "Cancelled" else None
        subscriptions.append(
            Subscription(
                id=len(subscriptions) + 1,
                customer_id=customer.id,
                plan=customer.account_tier,
                monthly_revenue=round(rng.uniform(low, high), 2) if high > 0 else 0.0,
                start_date=start,
                end_date=end,
                status=status,
            )
        )
    return subscriptions


def generate_expenses(departments: list[Department], rng: random.Random, total: int = 200) -> list[Expense]:
    today = date.today()
    expenses = []
    for i in range(total):
        dept = rng.choice(departments)
        category = rng.choice(EXPENSE_CATEGORIES)
        amount = round(rng.uniform(200, 25000), 2) if category != "Salaries" else round(rng.uniform(50000, 400000), 2)
        expenses.append(
            Expense(
                id=i + 1,
                department_id=dept.id,
                category=category,
                amount=amount,
                date=today - timedelta(days=rng.randint(0, 730)),
            )
        )
    return expenses


def generate_budgets(departments: list[Department]) -> list[Budget]:
    budgets = []
    for dept in departments:
        for fiscal_year in (2025, 2026):
            budgets.append(
                Budget(
                    id=len(budgets) + 1,
                    department_id=dept.id,
                    fiscal_year=fiscal_year,
                    allocated_amount=dept.budget * (0.95 if fiscal_year == 2025 else 1.0),
                )
            )
    return budgets


def generate_support_tickets(
    customers: list[Customer], support_agents: list[Employee], rng: random.Random, total: int = 220
) -> list[SupportTicket]:
    today = date.today()
    tickets = []
    for i in range(total):
        status = rng.choices(SUPPORT_STATUSES, weights=[0.1, 0.15, 0.35, 0.40], k=1)[0]
        created = today - timedelta(days=rng.randint(0, 400))
        resolved = created + timedelta(days=rng.randint(1, 14)) if status in ("Resolved", "Closed") else None
        tickets.append(
            SupportTicket(
                id=i + 1,
                customer_id=rng.choice(customers).id,
                priority=rng.choices(SUPPORT_PRIORITIES, weights=[0.35, 0.35, 0.20, 0.10], k=1)[0],
                status=status,
                created_date=created,
                resolved_date=resolved,
                assigned_employee_id=rng.choice(support_agents).id if support_agents else None,
            )
        )
    return tickets


def generate_all(seed: int = RANDOM_SEED) -> dict:
    rng = random.Random(seed)
    departments = generate_departments()
    employees = generate_employees(departments, rng)
    customers = generate_customers(rng)
    deals = generate_deals(customers, employees, rng)
    subscriptions = generate_subscriptions(customers, deals, rng)
    expenses = generate_expenses(departments, rng)
    budgets = generate_budgets(departments)
    support_agents = [e for e in employees if e.department_id == next(d.id for d in departments if d.name == "Customer Support")]
    support_tickets = generate_support_tickets(customers, support_agents, rng)

    return {
        "departments": departments,
        "employees": employees,
        "customers": customers,
        "deals": deals,
        "subscriptions": subscriptions,
        "expenses": expenses,
        "budgets": budgets,
        "support_tickets": support_tickets,
    }


def _print_preview() -> None:
    data = generate_all()
    for table, rows in data.items():
        print(f"{table}: {len(rows)} rows")

    print("\nSample employees:")
    for e in data["employees"][:6]:
        print(f"  {e.name} — {e.role}, dept={e.department_id}, salary=${e.salary:,.0f}, manager={e.manager_id}")

    print("\nSample customers:")
    for c in data["customers"][:5]:
        print(f"  {c.name} — {c.industry}, {c.account_tier}, signed up {c.signup_date}")

    print("\nDeal stage distribution:")
    from collections import Counter

    print(" ", dict(Counter(d.stage for d in data["deals"])))

    print("\nSubscription status distribution:")
    print(" ", dict(Counter(s.status for s in data["subscriptions"])))


if __name__ == "__main__":
    _print_preview()
