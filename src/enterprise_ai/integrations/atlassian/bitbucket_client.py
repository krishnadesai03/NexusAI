from __future__ import annotations

import os
from datetime import datetime

import httpx


class BitbucketClient:
    """Direct Bitbucket Cloud REST API access (learnings.md #4 follow-up — same fallback
    rationale as JiraClient). Auth: Basic (ATLASSIAN_EMAIL, Bitbucket-scoped token) — the
    REST API's auth requirement, confirmed live to be the *opposite* of git-over-HTTPS,
    which needs BITBUCKET_USERNAME instead (see learnings.md #4's git-push finding).

    Bitbucket's commits endpoint has no reliable author/date query-param filtering, so this
    fetches the full commit list (106 commits — small enough to be cheap) and filters in
    Python rather than risk an unverified server-side filter syntax."""

    def __init__(
        self,
        email: str | None = None,
        app_password: str | None = None,
        workspace: str | None = None,
        repo_slug: str = "api-gateway",
    ) -> None:
        self._email = email or os.environ["ATLASSIAN_EMAIL"]
        self._app_password = app_password or os.environ["BITBUCKET_APP_PASSWORD"]
        self._workspace = workspace or os.environ["BITBUCKET_WORKSPACE"]
        self._repo_slug = repo_slug

    async def get_commits(
        self,
        *,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        message_contains: str | None = None,
    ) -> list[dict]:
        commits = []
        url = f"https://api.bitbucket.org/2.0/repositories/{self._workspace}/{self._repo_slug}/commits"

        async with httpx.AsyncClient(auth=(self._email, self._app_password), timeout=30) as client:
            while url:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                commits.extend(data.get("values", []))
                url = data.get("next")

        since_dt = datetime.fromisoformat(since) if since else None
        until_dt = datetime.fromisoformat(until) if until else None

        results = []
        for c in commits:
            author_raw = c["author"]["raw"]
            message = c["message"].strip()
            commit_dt = datetime.fromisoformat(c["date"])

            if author and author.lower() not in author_raw.lower():
                continue
            if since_dt and commit_dt.replace(tzinfo=None) < since_dt:
                continue
            if until_dt and commit_dt.replace(tzinfo=None) > until_dt:
                continue
            if message_contains and message_contains.lower() not in message.lower():
                continue

            results.append({"author": author_raw, "date": c["date"], "message": message})

        return results
