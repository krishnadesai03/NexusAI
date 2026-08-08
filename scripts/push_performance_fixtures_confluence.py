"""Pushes one sprint retro page per sprint (13 total) to Confluence (Component 4), using
the real Jira ticket data from scripts/_performance_seed_state.json — pages reference real
issue keys so the agent has genuine cross-system content to read, not just raw ticket data.

Depends on push_performance_fixtures_jira.py (or fix_performance_fixtures_status.py) having
already populated the state file with real Jira keys for all 111 tickets.

Usage:
    .venv/Scripts/python.exe scripts/push_performance_fixtures_confluence.py        # all 13
    .venv/Scripts/python.exe scripts/push_performance_fixtures_confluence.py 1      # just sprint 1, for review
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from seed_performance_data import PEOPLE  # noqa: E402

STATE_FILE = ROOT / "scripts" / "_performance_seed_state.json"

# Ties the deliberately injected "rough sprint" data anomalies (see seed_performance_data.py
# ROUGH_SPRINTS) to a plausible human explanation, so the agent has real narrative context to
# find, not just a raw zero in the ticket counts.
ROUGH_SPRINT_NOTES = {
    ("Marcus Chen", 6): "Marcus was on leave for most of this sprint.",
    ("Sofia Reyes", 10): "Sofia was out for most of this sprint.",
}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _build_page_body(sprint: dict, sprint_tickets: list[dict]) -> str:
    done = [t for t in sprint_tickets if t["status"] == "Done"]
    points = sum(t["story_points"] or 0 for t in done)
    bugs = [t for t in done if t["work_type"] == "Bug"]

    html = [
        f"<p>Completed {len(done)} of {len(sprint_tickets)} tickets, {points} story points delivered. "
        f"{len(bugs)} bugs resolved.</p>",
        "<h3>Per-person breakdown</h3>",
        "<ul>",
    ]

    by_person = defaultdict(list)
    for t in sprint_tickets:
        by_person[t["assignee"]].append(t)

    for person in PEOPLE:
        person_tickets = by_person.get(person.name, [])
        note = ROUGH_SPRINT_NOTES.get((person.name, sprint["index"]))

        if not person_tickets:
            extra = f" {note}" if note else ""
            html.append(f"<li><strong>{person.name}</strong>: no tickets this sprint.{extra}</li>")
            continue

        type_counts: dict[str, int] = defaultdict(int)
        for t in person_tickets:
            type_counts[t["work_type"]] += 1
        mix = ", ".join(f"{v} {k}" for k, v in type_counts.items())
        sample = ", ".join(f"{t['key']} ({t['summary']})" for t in person_tickets[:2])
        html.append(f"<li><strong>{person.name}</strong>: {len(person_tickets)} tickets ({mix}) — e.g. {sample}</li>")

    html.append("</ul>")
    return "\n".join(html)


def _page_exists(client: httpx.Client, site: str, space_key: str, title: str) -> bool:
    resp = client.get(f"{site}/wiki/rest/api/content", params={"spaceKey": space_key, "title": title})
    resp.raise_for_status()
    return len(resp.json().get("results", [])) > 0


def _create_page(client: httpx.Client, site: str, space_key: str, title: str, body_html: str) -> dict | None:
    # Idempotent: Confluence enforces unique titles per space, and a 400 on that isn't
    # distinguishable from a real error without checking first — confirmed live after a
    # duplicate-title collision on a re-run. Skip rather than fail if it already exists.
    if _page_exists(client, site, space_key, title):
        print(f"Already exists, skipping: {title!r}")
        return None

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": body_html, "representation": "storage"}},
    }
    resp = client.post(f"{site}/wiki/rest/api/content", json=payload)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    _load_dotenv(ROOT / ".env")

    only_sprint = int(sys.argv[1]) if len(sys.argv) > 1 else None

    site = os.environ["ATLASSIAN_SITE_URL"].rstrip("/")
    email = os.environ["ATLASSIAN_EMAIL"]
    token = os.environ["ATLASSIAN_API_TOKEN"]

    if not STATE_FILE.exists():
        raise SystemExit(f"{STATE_FILE} not found — run the Jira push script(s) first.")

    state = json.loads(STATE_FILE.read_text())
    tickets = state["tickets"]
    sprints = state["sprints"]

    if len(tickets) < 111:
        raise SystemExit(f"State file only has {len(tickets)} tickets — expected 111. Finish the Jira push first.")

    if only_sprint:
        sprints = [s for s in sprints if s["index"] == only_sprint]

    with httpx.Client(auth=(email, token), timeout=30) as client:
        for sprint in sprints:
            sprint_tickets = [t for t in tickets if t["sprint_index"] == sprint["index"]]
            body = _build_page_body(sprint, sprint_tickets)
            title = f"Sprint {sprint['index']} Retro ({sprint['start_date']} to {sprint['end_date']})"
            result = _create_page(client, site, "AP", title, body)
            if result:
                print(f"Created: {result['title']!r} (id={result['id']})")

    print(f"\nDone: {len(sprints)} retro page(s) created.")


if __name__ == "__main__":
    main()
