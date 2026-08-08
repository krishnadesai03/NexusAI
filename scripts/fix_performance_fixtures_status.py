"""One-off remediation for the partial push_performance_fixtures_jira.py run: 106 issues
(KAN-7..KAN-112) were successfully CREATED, but 101 of them failed their status transition
because including "resolution" inside the transition request 400s on this project's
transition screen (works fine as a separate PUT afterward — confirmed live). This script
fixes those in place rather than deleting/recreating, and rebuilds the state file with the
correct ticket -> real Jira key mapping for all 111 tickets.

Usage: .venv/Scripts/python.exe scripts/fix_performance_fixtures_status.py
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
TRANSITION_IDS = {"To Do": "11", "In Progress": "21", "In Review": "31", "Done": "41"}

# Confirmed live: KAN-2..KAN-6 correspond to tickets[0:5] (already correct from the first
# small-batch run). KAN-7..KAN-112 correspond to tickets[5:111], in order, with zero gaps
# (verified: no creation failures occurred, only transition failures).
FIRST_BATCH_KEYS = ["KAN-2", "KAN-3", "KAN-4", "KAN-5", "KAN-6"]
SECOND_BATCH_START_NUM = 7


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _fix_one(client: httpx.Client, site: str, key: str, target_status: str) -> None:
    current = client.get(f"{site}/rest/api/3/issue/{key}", params={"fields": "status"})
    current.raise_for_status()
    current_status = current.json()["fields"]["status"]["name"]

    if current_status != target_status and target_status != "To Do":
        transition_id = TRANSITION_IDS[target_status]
        resp = client.post(f"{site}/rest/api/3/issue/{key}/transitions", json={"transition": {"id": transition_id}})
        resp.raise_for_status()

    if target_status == "Done":
        resp = client.put(f"{site}/rest/api/3/issue/{key}", json={"fields": {"resolution": {"name": "Done"}}})
        resp.raise_for_status()


def main() -> None:
    _load_dotenv(ROOT / ".env")

    site = os.environ["ATLASSIAN_SITE_URL"].rstrip("/")
    email = os.environ["ATLASSIAN_EMAIL"]
    token = os.environ["ATLASSIAN_API_TOKEN"]

    sprints = generate_sprints()
    tickets = generate_tickets(PEOPLE, sprints)

    first_batch = list(zip(FIRST_BATCH_KEYS, tickets[0:5]))
    second_batch_keys = [f"KAN-{SECOND_BATCH_START_NUM + i}" for i in range(len(tickets[5:111]))]
    second_batch = list(zip(second_batch_keys, tickets[5:111]))

    all_results = []
    failures = []

    with httpx.Client(auth=(email, token), timeout=30) as client:
        for i, (key, ticket) in enumerate(first_batch + second_batch, start=1):
            try:
                _fix_one(client, site, key, ticket.status)
                all_results.append(
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
                if i % 10 == 0 or i == len(first_batch) + len(second_batch):
                    print(f"  {i}/{len(first_batch) + len(second_batch)} verified/fixed (latest: {key})")
            except httpx.HTTPStatusError as exc:
                failures.append({"key": key, "summary": ticket.summary, "error": str(exc), "body": exc.response.text[:300]})
                print(f"  FAILED fixing {key} ({ticket.summary!r}): {exc}")

    STATE_FILE.write_text(
        json.dumps(
            {
                "tickets": all_results,
                "sprints": [
                    {"index": s.index, "name": s.name, "start_date": str(s.start_date), "end_date": str(s.end_date)}
                    for s in sprints
                ],
            },
            indent=2,
        )
    )

    print(f"\nDone: {len(all_results)} verified/fixed, {len(failures)} failed.")
    print(f"State rebuilt at {STATE_FILE} — now contains all {len(all_results)} tickets with real keys.")
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  {f['key']} — {f['summary']}: {f['error']}")


if __name__ == "__main__":
    main()
