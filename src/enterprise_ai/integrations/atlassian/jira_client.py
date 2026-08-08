from __future__ import annotations

import os

import httpx


class JiraClient:
    """Direct Jira Cloud REST API access (learnings.md #4 follow-up: genuine MCP access is
    blocked on Atlassian's side, likely an EAP gate — this is the proven fallback already
    used throughout Component 4's data seeding). Auth: Basic (email, classic API token) —
    confirmed working live, unlike Bitbucket's inverted requirement."""

    def __init__(
        self,
        site_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        project_key: str = "KAN",
    ) -> None:
        self._site_url = (site_url or os.environ["ATLASSIAN_SITE_URL"]).rstrip("/")
        self._email = email or os.environ["ATLASSIAN_EMAIL"]
        self._api_token = api_token or os.environ["ATLASSIAN_API_TOKEN"]
        self._project_key = project_key

    async def search_issues(
        self,
        *,
        sprint_index: int | None = None,
        assignee: str | None = None,
        work_type: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """Structured search — builds JQL internally from parameters rather than accepting
        raw JQL from the LLM, consistent with this project's guardrail philosophy of
        constraining model output to a fixed shape rather than trusting freeform input."""

        clauses = [f'project = "{self._project_key}"']
        if sprint_index is not None:
            clauses.append(f'labels = "sprint-{sprint_index}"')
        if assignee:
            clauses.append(f'assignee = "{assignee}"')
        if work_type:
            clauses.append(f'issuetype = "{work_type}"')
        if status:
            clauses.append(f'status = "{status}"')
        jql = " AND ".join(clauses)

        async with httpx.AsyncClient(auth=(self._email, self._api_token), timeout=30) as client:
            # /rest/api/3/search was deprecated and removed (410 Gone, confirmed live) in
            # favor of /rest/api/3/search/jql — Atlassian shut off the old endpoint entirely
            # by end of October 2025.
            resp = await client.get(
                f"{self._site_url}/rest/api/3/search/jql",
                params={"jql": jql, "fields": "summary,issuetype,assignee,reporter,status,labels"},
            )
            resp.raise_for_status()

        results = []
        for issue in resp.json().get("issues", []):
            fields = issue["fields"]
            labels = fields.get("labels", [])
            points = next((int(lbl.split("-")[1]) for lbl in labels if lbl.startswith("points-")), None)
            results.append(
                {
                    "key": issue["key"],
                    "summary": fields["summary"],
                    "work_type": fields["issuetype"]["name"],
                    "assignee": (fields.get("assignee") or {}).get("displayName"),
                    "status": fields["status"]["name"],
                    "story_points": points,
                    "labels": labels,
                }
            )
        return results
