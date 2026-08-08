from __future__ import annotations

import os

import httpx


class ConfluenceClient:
    """Direct Confluence Cloud REST API access (learnings.md #4 follow-up — same fallback
    rationale as JiraClient). Auth: Basic (email, classic API token), same as Jira — both
    products share this auth mechanism, unlike Bitbucket's inverted one."""

    def __init__(
        self,
        site_url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        space_key: str = "AP",
    ) -> None:
        self._site_url = (site_url or os.environ["ATLASSIAN_SITE_URL"]).rstrip("/")
        self._email = email or os.environ["ATLASSIAN_EMAIL"]
        self._api_token = api_token or os.environ["ATLASSIAN_API_TOKEN"]
        self._space_key = space_key

    async def search_pages(self, *, sprint_index: int | None = None) -> list[dict]:
        cql = f'space="{self._space_key}" and type="page"'
        if sprint_index is not None:
            cql += f' and title~"Sprint {sprint_index} Retro"'

        async with httpx.AsyncClient(auth=(self._email, self._api_token), timeout=30) as client:
            resp = await client.get(f"{self._site_url}/wiki/rest/api/content/search", params={"cql": cql})
            resp.raise_for_status()

        return [{"id": r["id"], "title": r["title"]} for r in resp.json().get("results", [])]

    async def get_page_content(self, page_id: str) -> str:
        async with httpx.AsyncClient(auth=(self._email, self._api_token), timeout=30) as client:
            resp = await client.get(
                f"{self._site_url}/wiki/rest/api/content/{page_id}", params={"expand": "body.storage"}
            )
            resp.raise_for_status()

        return resp.json()["body"]["storage"]["value"]
