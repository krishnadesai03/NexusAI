"""Pushes the synthetic dataset from seed_performance_data.py into the real Jira sandbox
(Component 4). Design constraints discovered via live testing before writing this, not
guessed — see learnings.md Component 4 follow-up:

- The board doesn't support native Sprint objects (Kanban-style, not Scrum-capable), so
  sprint membership is encoded as a label ("sprint-6") instead of Jira's own Sprint field.
- This project has no "Story Points" custom field configured at all, so points are also
  encoded as a label ("points-3") rather than a native field.
- Jira Cloud stamps `created` server-side on issue creation — it is NOT settable via the
  REST API, so no attempt is made to backdate it. Historical sprint/date context lives in
  the "sprint-N" label plus the sprint calendar this script prints/saves, not in Jira's own
  created/resolved timestamps.
- Bitbucket's auth (used by a later script, not this one) is Basic Auth with the Atlassian
  EMAIL (not the Bitbucket username) + the Bitbucket-scoped API token.

Writes real issues to the KAN project. Saves a local state file (ticket -> real Jira key
mapping) that scripts/push_performance_fixtures_bitbucket.py depends on next, since commit
messages need to reference real issue keys that only exist after this runs.

Usage: .venv/Scripts/python.exe scripts/push_performance_fixtures_jira.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from seed_performance_data import PEOPLE, generate_sprints, generate_tickets  # noqa: E402

STATE_FILE = ROOT / "scripts" / "_performance_seed_state.json"

# Discovered live for this project's single workflow (see module docstring) — all issue
# types on this board share one workflow, so these transition IDs are constant across tickets.
TRANSITION_IDS = {"To Do": "11", "In Progress": "21", "In Review": "31", "Done": "41"}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _lookup_account_ids(client: httpx.Client, site: str, people) -> dict[str, str]:
    account_ids = {}
    for person in people:
        resp = client.get(f"{site}/rest/api/3/user/search", params={"query": person.name})
        resp.raise_for_status()
        results = resp.json()
        if not results:
            raise SystemExit(f"Could not find a Jira account for {person.name!r}")
        account_ids[person.name] = results[0]["accountId"]
    return account_ids


def _create_issue(client: httpx.Client, site: str, ticket, account_ids: dict[str, str]) -> str:
    labels = [f"sprint-{ticket.sprint.index}"]
    if ticket.story_points is not None:
        labels.append(f"points-{ticket.story_points}")

    payload = {
        "fields": {
            "project": {"key": "KAN"},
            "summary": ticket.summary,
            "issuetype": {"name": ticket.work_type},
            "assignee": {"accountId": account_ids[ticket.assignee.name]},
            "reporter": {"accountId": account_ids[ticket.reporter.name]},
            "labels": labels,
        }
    }
    resp = client.post(f"{site}/rest/api/3/issue", json=payload)
    resp.raise_for_status()
    return resp.json()["key"]


def _transition_issue(client: httpx.Client, site: str, key: str, status: str) -> None:
    if status == "To Do":
        return  # already the default status on creation
    transition_id = TRANSITION_IDS[status]
    resp = client.post(f"{site}/rest/api/3/issue/{key}/transitions", json={"transition": {"id": transition_id}})
    resp.raise_for_status()

    if status == "Done":
        # Jira's workflow doesn't reliably auto-set Resolution on this transition (confirmed
        # flaky live: 4/5 tickets got it, 1 silently didn't, from identical code). Including
        # "resolution" inside the transition request itself also 400s — confirmed live, this
        # project's transition screen doesn't have that field on it. The only combination that
        # actually works: transition first, then a SEPARATE PUT to set resolution afterward.
        resp = client.put(f"{site}/rest/api/3/issue/{key}", json={"fields": {"resolution": {"name": "Done"}}})
        resp.raise_for_status()


def main() -> None:
    _load_dotenv(ROOT / ".env")

    # skip: how many of the (deterministic, fixed-seed) generated tickets to skip — used to
    # resume after an earlier partial run instead of re-creating already-pushed tickets.
    # limit: cap how many to push after skipping, e.g. for another small-batch check.
    skip = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    site = os.environ["ATLASSIAN_SITE_URL"].rstrip("/")
    email = os.environ["ATLASSIAN_EMAIL"]
    token = os.environ["ATLASSIAN_API_TOKEN"]

    sprints = generate_sprints()
    tickets = generate_tickets(PEOPLE, sprints)[skip:]
    if limit:
        tickets = tickets[:limit]
    print(f"Skipping first {skip} (already pushed). Pushing {len(tickets)} tickets to Jira...\n")

    results = []
    failures = []

    with httpx.Client(auth=(email, token), timeout=30) as client:
        account_ids = _lookup_account_ids(client, site, PEOPLE)
        print(f"Resolved account IDs for: {', '.join(account_ids)}\n")

        for i, ticket in enumerate(tickets, start=1):
            try:
                key = _create_issue(client, site, ticket, account_ids)
                _transition_issue(client, site, key, ticket.status)
                results.append(
                    {
                        "key": key,
                        "summary": ticket.summary,
                        "work_type": ticket.work_type,
                        "service": ticket.service,
                        "assignee": ticket.assignee.name,
                        "sprint_index": ticket.sprint.index,
                        "story_points": ticket.story_points,
                        "status": ticket.status,
                    }
                )
                if i % 10 == 0 or i == len(tickets):
                    print(f"  {i}/{len(tickets)} created (latest: {key})")
            except httpx.HTTPStatusError as exc:
                failures.append({"summary": ticket.summary, "error": str(exc), "body": exc.response.text[:300]})
                print(f"  FAILED on ticket {i} ({ticket.summary!r}): {exc}")

    existing_tickets = []
    if STATE_FILE.exists():
        existing_tickets = json.loads(STATE_FILE.read_text()).get("tickets", [])

    STATE_FILE.write_text(json.dumps({"tickets": existing_tickets + results, "sprints": [
        {"index": s.index, "name": s.name, "start_date": str(s.start_date), "end_date": str(s.end_date)}
        for s in sprints
    ]}, indent=2))

    print(f"\nDone: {len(results)} succeeded, {len(failures)} failed.")
    print(f"State saved to {STATE_FILE}")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  {f['summary']}: {f['error']}")


if __name__ == "__main__":
    main()
