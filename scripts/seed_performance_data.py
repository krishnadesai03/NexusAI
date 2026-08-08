"""Synthetic data GENERATOR for Component 4 (Performance Analyzer Agent) — pure Python,
makes NO API calls and touches nothing live. Produces the sprint/ticket/retro dataset as
plain Python objects, so it can be reviewed (via the preview block below) before anything
gets pushed to the real Jira/Confluence/Bitbucket sandbox.

Bitbucket commit content is deliberately NOT generated here: commit messages need to
reference real Jira issue keys (e.g. "KAN-142: ..."), which only exist after tickets are
actually created via the Jira API. Commit generation happens in the push stage, after
ticket creation, using the real keys returned by that API.

Usage (preview only, no side effects):
    .venv/Scripts/python.exe scripts/seed_performance_data.py
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

RANDOM_SEED = 42
SPRINT_COUNT = 13
SPRINT_LENGTH_DAYS = 14
SERVICES = ["api-gateway", "billing-service", "notifications-service", "search-service"]

STORY_POINT_SCALE = [1, 2, 3, 5, 8]
STORY_POINT_WEIGHTS = [0.15, 0.30, 0.30, 0.20, 0.05]


@dataclass
class Person:
    name: str
    email_alias: str  # combined with SYNTHETIC_EMPLOYEE_BASE_EMAIL at push time
    role: str  # "backend" | "frontend" | "qa"


PEOPLE = [
    Person("Priya Nair", "priyanair", "backend"),
    Person("Marcus Chen", "marcuschen", "backend"),
    Person("Jordan Lee", "jordanlee", "frontend"),
    Person("Sofia Reyes", "sofiareyes", "qa"),
]


@dataclass
class Sprint:
    index: int  # 1-based
    name: str
    start_date: date
    end_date: date
    is_current: bool  # last sprint — mix of statuses instead of all Done


@dataclass
class Ticket:
    summary: str
    work_type: str  # "Story" | "Task" | "Bug"
    service: str
    assignee: Person
    reporter: Person
    sprint: Sprint
    story_points: int | None
    status: str  # "Done" | "In Progress" | "To Do"
    created_date: date
    resolved_date: date | None


@dataclass
class RetroNote:
    sprint: Sprint
    body: str


TITLE_TEMPLATES = {
    ("backend", "Story"): [
        "Implement rate limiting for {service}",
        "Add caching layer to {service} read path",
        "Migrate {service} to new auth middleware",
        "Add pagination support to {service} list endpoints",
        "Implement retry-with-backoff for {service} downstream calls",
        "Add webhook support to {service}",
        "Support bulk operations in {service} API",
        "Add multi-region failover for {service}",
        "Implement idempotency keys for {service} write endpoints",
        "Add audit logging to {service}",
    ],
    ("backend", "Task"): [
        "Upgrade {service} dependencies to latest stable versions",
        "Add structured logging to {service}",
        "Refactor {service} config loading",
        "Improve {service} startup time",
        "Add health check endpoint to {service}",
        "Document {service} API in OpenAPI spec",
        "Set up dashboards for {service} latency metrics",
        "Clean up deprecated endpoints in {service}",
        "Add unit test coverage for {service} edge cases",
        "Tune {service} database connection pool settings",
    ],
    ("backend", "Bug"): [
        "Fix race condition in {service} under concurrent writes",
        "Resolve memory leak in {service} worker process",
        "Fix incorrect error code returned by {service} on validation failure",
        "{service} occasionally drops events under high load",
        "Fix timezone handling bug in {service}",
        "{service} returns stale data after cache invalidation",
        "Fix deadlock in {service} during batch processing",
        "{service} crashes on malformed input payload",
        "Fix connection pool exhaustion in {service}",
        "{service} retries duplicate requests incorrectly",
    ],
    ("frontend", "Story"): [
        "Build new dashboard view consuming {service} API",
        "Add pagination controls to {service} results list",
        "Implement dark mode for {service} settings page",
        "Add inline validation to {service} configuration form",
        "Build notification center powered by {service}",
        "Add search/filter UI for {service} data",
        "Implement optimistic UI updates for {service} actions",
        "Add export-to-CSV feature for {service} reports",
        "Build onboarding flow for {service} setup",
        "Add real-time status indicator for {service}",
    ],
    ("frontend", "Task"): [
        "Update {service} client SDK to latest version",
        "Improve error handling for {service} API failures in UI",
        "Refactor {service} settings page components",
        "Add loading skeletons to {service} views",
        "Improve accessibility of {service} forms",
        "Optimize bundle size for {service} module",
        "Add analytics tracking to {service} UI",
        "Clean up unused CSS in {service} views",
        "Add Storybook stories for {service} components",
        "Fix responsive layout issues in {service} views",
    ],
    ("frontend", "Bug"): [
        "Fix broken layout on {service} settings page",
        "{service} form doesn't show validation errors on mobile",
        "Fix stale data shown after {service} update",
        "{service} dashboard chart fails to render on Safari",
        "Fix infinite loading spinner on {service} page",
        "{service} settings not saving on first attempt",
        "Fix incorrect date formatting on {service} view",
        "{service} modal doesn't close on outside click",
    ],
    ("qa", "Bug"): [
        "{service} returns 500 on malformed input",
        "Intermittent timeout when calling {service} under load",
        "Data inconsistency observed after {service} deploy",
        "{service} allows duplicate records to be created",
        "Found permission bypass in {service} API",
        "{service} response schema doesn't match documented API",
        "Regression: {service} pagination broken after last release",
        "{service} fails silently when downstream dependency is down",
        "Found XSS vector in {service}-consuming UI",
        "{service} load test reveals throughput regression",
    ],
    ("qa", "Task"): [
        "Write integration tests for {service}",
        "Set up load testing for {service}",
        "Add regression test suite for {service} critical paths",
        "Review and update test plan for {service}",
        "Set up contract tests between {service} and dependent services",
        "Automate smoke tests for {service} deploy pipeline",
        "Expand edge-case test coverage for {service}",
        "Validate {service} behavior under network partition",
    ],
}

WORK_TYPE_MIX = {
    "backend": [("Story", 0.40), ("Task", 0.35), ("Bug", 0.25)],
    "frontend": [("Story", 0.45), ("Task", 0.35), ("Bug", 0.20)],
    "qa": [("Bug", 0.60), ("Task", 0.40)],
}

# Base sprint capacity (rough "points-equivalent" ticket count) per role, with per-sprint
# gaussian noise. ROUGH_SPRINTS injects a deliberate dip for specific (person, sprint_index)
# pairs, so velocity data has real variance instead of being suspiciously flat. Values here
# are half of an earlier, higher-volume pass (226 tickets total) — cut for practicality of
# actually pushing this many issues through the Jira API, not because more data would have
# added analytical value. Dip multipliers are pronounced (not just "below average") so
# they read as unambiguous outliers rather than noise.
BASE_CAPACITY = {"backend": 2.5, "frontend": 2.0, "qa": 2.0}
ROUGH_SPRINTS = {("Marcus Chen", 6): 0.15, ("Sofia Reyes", 10): 0.15}


def generate_sprints() -> list[Sprint]:
    today = date.today()
    total_days = SPRINT_COUNT * SPRINT_LENGTH_DAYS
    first_start = today - timedelta(days=total_days)

    sprints = []
    for i in range(SPRINT_COUNT):
        start = first_start + timedelta(days=i * SPRINT_LENGTH_DAYS)
        end = start + timedelta(days=SPRINT_LENGTH_DAYS - 1)
        sprints.append(
            Sprint(
                index=i + 1,
                name=f"Sprint {i + 1}",
                start_date=start,
                end_date=end,
                is_current=(i == SPRINT_COUNT - 1),
            )
        )
    return sprints


def _pick_work_type(role: str, rng: random.Random) -> str:
    types, weights = zip(*WORK_TYPE_MIX[role])
    return rng.choices(types, weights=weights, k=1)[0]


def _pick_story_points(work_type: str, rng: random.Random) -> int | None:
    if work_type != "Story":
        return None
    return rng.choices(STORY_POINT_SCALE, weights=STORY_POINT_WEIGHTS, k=1)[0]


def generate_tickets(people: list[Person], sprints: list[Sprint], seed: int = RANDOM_SEED) -> list[Ticket]:
    rng = random.Random(seed)
    tickets = []

    for sprint in sprints:
        for person in people:
            capacity = BASE_CAPACITY[person.role]
            noise = rng.gauss(1.0, 0.2)
            is_rough_sprint = (person.name, sprint.index) in ROUGH_SPRINTS
            dip = ROUGH_SPRINTS.get((person.name, sprint.index), 1.0)
            raw_count = round(capacity * noise * dip)
            # The floor of 1 only applies to normal sprints — a rough sprint is allowed to hit
            # zero tickets outright (e.g. someone was on leave), since a floored "1 vs 2" isn't
            # distinguishable from ordinary noise, but a genuine zero unambiguously is.
            ticket_count = raw_count if is_rough_sprint else max(1, raw_count)

            for _ in range(ticket_count):
                work_type = _pick_work_type(person.role, rng)
                service = rng.choice(SERVICES)
                template = rng.choice(TITLE_TEMPLATES[(person.role, work_type)])
                summary = template.format(service=service)
                story_points = _pick_story_points(work_type, rng)

                created = sprint.start_date + timedelta(days=rng.randint(0, SPRINT_LENGTH_DAYS - 3))
                if sprint.is_current:
                    status = rng.choices(["Done", "In Progress", "To Do"], weights=[0.5, 0.3, 0.2], k=1)[0]
                else:
                    status = "Done"
                resolved = created + timedelta(days=rng.randint(1, 5)) if status == "Done" else None

                reporter = person if person.role != "qa" else rng.choice(people)

                tickets.append(
                    Ticket(
                        summary=summary,
                        work_type=work_type,
                        service=service,
                        assignee=person,
                        reporter=reporter,
                        sprint=sprint,
                        story_points=story_points,
                        status=status,
                        created_date=created,
                        resolved_date=resolved,
                    )
                )

    return tickets


def generate_retro_notes(sprints: list[Sprint], tickets: list[Ticket]) -> list[RetroNote]:
    notes = []
    for sprint in sprints:
        sprint_tickets = [t for t in tickets if t.sprint.index == sprint.index]
        done = [t for t in sprint_tickets if t.status == "Done"]
        points = sum(t.story_points or 0 for t in done)
        bugs = [t for t in done if t.work_type == "Bug"]

        body = (
            f"Sprint {sprint.index} ({sprint.start_date} to {sprint.end_date})\n\n"
            f"Completed {len(done)} of {len(sprint_tickets)} tickets, {points} story points delivered.\n"
            f"{len(bugs)} bugs resolved this sprint.\n"
        )
        notes.append(RetroNote(sprint=sprint, body=body))
    return notes


def _print_preview() -> None:
    sprints = generate_sprints()
    tickets = generate_tickets(PEOPLE, sprints)
    retros = generate_retro_notes(sprints, tickets)

    print(f"Sprints: {len(sprints)} ({sprints[0].start_date} to {sprints[-1].end_date})")
    print(f"Total tickets: {len(tickets)}\n")

    print("Per-person breakdown:")
    for person in PEOPLE:
        person_tickets = [t for t in tickets if t.assignee.name == person.name]
        by_type = {}
        for t in person_tickets:
            by_type[t.work_type] = by_type.get(t.work_type, 0) + 1
        print(f"  {person.name} ({person.role}): {len(person_tickets)} tickets — {by_type}")

    print("\nVelocity (completed story points) per sprint, per backend person:")
    for person in PEOPLE:
        if person.role != "backend":
            continue
        line = []
        for sprint in sprints:
            pts = sum(
                t.story_points or 0
                for t in tickets
                if t.assignee.name == person.name and t.sprint.index == sprint.index and t.status == "Done"
            )
            line.append(str(pts))
        print(f"  {person.name}: {' '.join(line)}")

    print("\nRaw ticket count per sprint, per person (checks whether injected dips are visible")
    print("in count even when points alone are noisy from type-mix):")
    for person in PEOPLE:
        line = []
        for sprint in sprints:
            count = sum(1 for t in tickets if t.assignee.name == person.name and t.sprint.index == sprint.index)
            line.append(str(count))
        print(f"  {person.name}: {' '.join(line)}")

    print("\nSample tickets:")
    for t in tickets[:8]:
        print(f"  [{t.work_type}] {t.summary} — {t.assignee.name}, {t.sprint.name}, {t.status}, pts={t.story_points}")

    print("\nSample retro note (Sprint 1):")
    print(retros[0].body)


if __name__ == "__main__":
    _print_preview()
