"""Read-only connection check for Jira, Confluence, and Bitbucket — confirms the credentials
in .env actually authenticate before scripts/push_performance_fixtures.py does anything
bulk/write. Makes no writes, creates nothing, safe to run repeatedly.

Usage: .venv/Scripts/python.exe scripts/smoke_test_atlassian_connection.py
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _require_env(*names: str) -> dict[str, str]:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise SystemExit(f"Missing required .env vars: {', '.join(missing)}")
    return {n: os.environ[n] for n in names}


def check_jira(site_url: str, email: str, api_token: str) -> None:
    print("--- Jira ---")
    with httpx.Client(auth=(email, api_token), timeout=15) as client:
        me = client.get(f"{site_url}/rest/api/3/myself")
        me.raise_for_status()
        print(f"Authenticated as: {me.json().get('displayName')} ({me.json().get('emailAddress')})")

        project = client.get(f"{site_url}/rest/api/3/project/KAN")
        project.raise_for_status()
        print(f"Project found: {project.json().get('name')} (key={project.json().get('key')})")

        boards = client.get(f"{site_url}/rest/agile/1.0/board", params={"projectKeyOrId": "KAN"})
        boards.raise_for_status()
        board_list = boards.json().get("values", [])
        for b in board_list:
            print(f"Board found: id={b['id']} name={b['name']} type={b['type']}")


def check_confluence(site_url: str, email: str, api_token: str) -> None:
    print("\n--- Confluence ---")
    with httpx.Client(auth=(email, api_token), timeout=15) as client:
        space = client.get(f"{site_url}/wiki/rest/api/space/AP")
        space.raise_for_status()
        print(f"Space found: {space.json().get('name')} (key={space.json().get('key')})")


def check_bitbucket(workspace: str, username: str, app_password: str, atlassian_email: str) -> None:
    print("\n--- Bitbucket ---")
    with httpx.Client(timeout=15) as client:
        # Try a few auth combinations — Bitbucket's auth has moved onto the same unified
        # scoped-API-token system as Jira/Confluence, so the classic username:app_password
        # combo (and a bare bearer token) may no longer be what's expected.
        for label, kwargs in [
            ("bearer token", {"headers": {"Authorization": f"Bearer {app_password}"}}),
            ("basic auth (bitbucket username:token)", {"auth": (username, app_password)}),
            ("basic auth (atlassian email:token)", {"auth": (atlassian_email, app_password)}),
        ]:
            resp = client.get(f"https://api.bitbucket.org/2.0/repositories/{workspace}/api-gateway", **kwargs)
            if resp.status_code == 200:
                print(f"Auth worked via {label}.")
                print(f"Repo found: {resp.json().get('full_name')}")
                return
            print(f"Auth via {label} failed: {resp.status_code} {resp.text[:200]}")

        raise SystemExit("Both Bitbucket auth methods failed — see errors above.")


def main() -> None:
    _load_dotenv(ROOT / ".env")

    atlassian = _require_env("ATLASSIAN_SITE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN")
    bitbucket = _require_env("BITBUCKET_WORKSPACE", "BITBUCKET_USERNAME", "BITBUCKET_APP_PASSWORD")

    site_url = atlassian["ATLASSIAN_SITE_URL"].rstrip("/")

    check_jira(site_url, atlassian["ATLASSIAN_EMAIL"], atlassian["ATLASSIAN_API_TOKEN"])
    check_confluence(site_url, atlassian["ATLASSIAN_EMAIL"], atlassian["ATLASSIAN_API_TOKEN"])
    check_bitbucket(
        bitbucket["BITBUCKET_WORKSPACE"],
        bitbucket["BITBUCKET_USERNAME"],
        bitbucket["BITBUCKET_APP_PASSWORD"],
        atlassian["ATLASSIAN_EMAIL"],
    )

    print("\nAll three connections verified.")


if __name__ == "__main__":
    main()
