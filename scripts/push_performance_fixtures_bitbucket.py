"""Pushes real git commits to the api-gateway Bitbucket repo (Component 4), one per
completed Jira ticket, backdated to that ticket's resolved date with the correct synthetic
employee as commit AUTHOR (you remain the committer, since you're the one actually running
this) — using real git operations (clone/commit/push), not Bitbucket's REST file-update
endpoint, since that endpoint stamps "now" and the authenticated account with no way to
override either; git's --author flag plus GIT_AUTHOR_DATE/GIT_COMMITTER_DATE do support both.

Depends on the state file having real Jira keys for all 111 tickets, but that file doesn't
store ticket dates (only push_performance_fixtures_jira.py's summary fields) — so this script
regenerates the deterministic ticket list (same fixed seed) to get dates, and maps it to real
keys using the same index->key correspondence established in fix_performance_fixtures_status.py
(confirmed live: zero creation failures, so the mapping has no gaps).

Usage:
    .venv/Scripts/python.exe scripts/push_performance_fixtures_bitbucket.py        # all commits
    .venv/Scripts/python.exe scripts/push_performance_fixtures_bitbucket.py 5      # first 5 only, for review
"""

from __future__ import annotations

import os
import random
import shutil
import stat
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from seed_performance_data import PEOPLE, generate_sprints, generate_tickets  # noqa: E402

CLONE_DIR = ROOT / "scripts" / "_bitbucket_clone"

FIRST_BATCH_KEYS = ["KAN-2", "KAN-3", "KAN-4", "KAN-5", "KAN-6"]
SECOND_BATCH_START_NUM = 7

COMMIT_TIME_SEED = 7


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _run_git(*args: str, cwd: Path, extra_env: dict | None = None) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **(extra_env or {})},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Never echo raw args here — a clone/push URL can carry embedded credentials, and
        # this exact bug leaked an app password into terminal output once already.
        safe_args = [a if "@bitbucket.org" not in a else "<url with embedded credentials redacted>" for a in args]
        raise RuntimeError(f"git {' '.join(safe_args)} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")


def _person_email(person, base_email: str) -> str:
    local, domain = base_email.split("@", 1)
    return f"{local}+{person.email_alias}@{domain}"


def main() -> None:
    _load_dotenv(ROOT / ".env")

    # skip: how many of the (deterministically ordered) completed tickets to skip — used to
    # resume after an earlier partial push instead of re-committing already-pushed tickets
    # (which would re-append duplicate changelog lines into files that already have them).
    # limit: cap how many to commit after skipping.
    skip = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    email = os.environ["ATLASSIAN_EMAIL"]
    bitbucket_username = os.environ["BITBUCKET_USERNAME"]
    app_password = os.environ["BITBUCKET_APP_PASSWORD"]
    workspace = os.environ["BITBUCKET_WORKSPACE"]
    base_email = os.environ["SYNTHETIC_EMPLOYEE_BASE_EMAIL"]

    sprints = generate_sprints()
    all_tickets = generate_tickets(PEOPLE, sprints)
    keys = FIRST_BATCH_KEYS + [f"KAN-{SECOND_BATCH_START_NUM + i}" for i in range(len(all_tickets) - 5)]
    keyed_tickets = list(zip(keys, all_tickets))

    done = [(key, t) for key, t in keyed_tickets if t.status == "Done" and t.resolved_date is not None]
    done.sort(key=lambda kt: kt[1].resolved_date)
    done = done[skip:]
    if limit:
        done = done[:limit]
    print(f"Skipping first {skip} (already pushed).")

    rng = random.Random(COMMIT_TIME_SEED)
    people_by_name = {p.name: p for p in PEOPLE}

    print(f"{len(done)} completed tickets to commit, chronologically.\n")

    if CLONE_DIR.exists():
        # git marks .git/objects/* read-only on Windows; shutil.rmtree can't delete those
        # without clearing the flag first.
        def _make_writable_and_retry(func, path, _exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        shutil.rmtree(CLONE_DIR, onerror=_make_writable_and_retry)

    # Confirmed live: git's HTTPS auth for Bitbucket needs BITBUCKET_USERNAME + token — the
    # opposite of the REST API, which needs ATLASSIAN_EMAIL + token. Non-obvious, genuinely
    # inconsistent between Bitbucket's git-over-HTTPS endpoint and its REST API.
    clone_url = f"https://{quote(bitbucket_username, safe='')}:{quote(app_password, safe='')}@bitbucket.org/{workspace}/api-gateway.git"
    print("Cloning repo...")
    _run_git("clone", clone_url, str(CLONE_DIR), cwd=ROOT)

    _run_git("config", "user.name", "Krishna Desai", cwd=CLONE_DIR)
    _run_git("config", "user.email", email, cwd=CLONE_DIR)

    for i, (key, ticket) in enumerate(done, start=1):
        person = people_by_name[ticket.assignee.name]
        author_email = _person_email(person, base_email)

        commit_time = time(hour=rng.randint(9, 17), minute=rng.randint(0, 59))
        commit_dt = datetime.combine(ticket.resolved_date, commit_time)
        git_date = commit_dt.strftime("%Y-%m-%dT%H:%M:%S")

        service_dir = CLONE_DIR / "services" / ticket.service
        service_dir.mkdir(parents=True, exist_ok=True)
        changelog = service_dir / "CHANGELOG.md"
        if not changelog.exists():
            changelog.write_text(f"# {ticket.service} changelog\n\n")

        with changelog.open("a", encoding="utf-8") as f:
            f.write(f"- {ticket.resolved_date} — {key}: {ticket.summary} ({person.name})\n")

        rel_path = str(changelog.relative_to(CLONE_DIR))
        _run_git("add", rel_path, cwd=CLONE_DIR)
        _run_git(
            "commit",
            "--author",
            f"{person.name} <{author_email}>",
            "-m",
            f"{key}: {ticket.summary}",
            cwd=CLONE_DIR,
            extra_env={"GIT_AUTHOR_DATE": git_date, "GIT_COMMITTER_DATE": git_date},
        )

        if i % 10 == 0 or i == len(done):
            print(f"  {i}/{len(done)} committed (latest: {key} by {person.name} on {ticket.resolved_date})")

    print("\nPushing to Bitbucket...")
    _run_git("push", "origin", "HEAD", cwd=CLONE_DIR)
    print(f"\nDone: {len(done)} commits pushed.")


if __name__ == "__main__":
    main()
