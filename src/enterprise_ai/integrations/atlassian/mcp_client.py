from __future__ import annotations

import json
import os
from contextlib import AsyncExitStack

import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# The /preview endpoint, not /v1/mcp (learnings.md #4 follow-up) — the original MCP
# investigation only tested the generic Teamwork Graph interface at /v1/mcp and got a genuine
# 403 "Insufficient API token scopes" there; live re-testing found /v1/mcp/preview exposes
# direct, Jira/Confluence-shaped tools (getJiraIssue, searchJiraIssuesUsingJql,
# getConfluenceContent, searchConfluence) that work today with the same ATLASSIAN_MCP_TOKEN.
_MCP_URL = "https://mcp.atlassian.com/v1/mcp/preview"


class AtlassianMCPError(RuntimeError):
    """Raised when the MCP server itself reports a tool-level failure (e.g. insufficient
    scopes, a bad objectIdentifier). These come back as a normal 200 response with
    `{"error": true, "message": ...}` inside the tool result's text content, not as an HTTP
    error or an exception the SDK raises on its own — has to be checked explicitly."""


class AtlassianMCPSession:
    """Owns one persistent connection to Atlassian's Remote MCP Server, shared by
    JiraMCPClient and ConfluenceMCPClient (both live on the same server/session — a
    reconnect-per-call design would add real latency, working against Component 12's
    parallelism/caching work rather than with it).

    Built once per process in `bootstrap.build_shared_resources`, same lifetime as
    PgVectorStore/PostgresQueryClient. The underlying SDK transport
    (`streamable_http_client` + `ClientSession`) is normally used as a single `async with`
    block; `AsyncExitStack` lets it stay open across many calls instead, closed explicitly via
    `close()` at process shutdown (`bootstrap.close_shared_resources`)."""

    def __init__(self, session: ClientSession, cloud_id: str, exit_stack: AsyncExitStack) -> None:
        self._session = session
        self.cloud_id = cloud_id
        self._exit_stack = exit_stack

    @classmethod
    async def connect(
        cls, email: str | None = None, api_token: str | None = None, site_url: str | None = None
    ) -> AtlassianMCPSession:
        email = email or os.environ["ATLASSIAN_EMAIL"]
        # ATLASSIAN_MCP_TOKEN, not ATLASSIAN_API_TOKEN — a separate, scoped token (see
        # .env.example), distinct from the classic token JiraClient/ConfluenceClient/
        # BitbucketClient use for direct REST.
        api_token = api_token or os.environ["ATLASSIAN_MCP_TOKEN"]
        site_url = (site_url or os.environ["ATLASSIAN_SITE_URL"]).rstrip("/")

        cloud_id = await cls._resolve_cloud_id(site_url)

        stack = AsyncExitStack()
        try:
            http_client = await stack.enter_async_context(httpx2.AsyncClient(auth=(email, api_token), timeout=30))
            read, write = await stack.enter_async_context(streamable_http_client(_MCP_URL, http_client=http_client))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise

        return cls(session, cloud_id, stack)

    @staticmethod
    async def _resolve_cloud_id(site_url: str) -> str:
        # cloudId is never silently auto-resolved by the MCP server itself (per its own tool
        # descriptions) — this is the same lightweight, unauthenticated lookup used to confirm
        # it live during the original investigation, resolved once per process and cached here
        # rather than re-resolved on every tool call.
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{site_url}/_edge/tenant_info")
            resp.raise_for_status()
        return resp.json()["cloudId"]

    async def call(self, tool_name: str, arguments: dict) -> dict:
        result = await self._session.call_tool(tool_name, arguments={"cloudId": self.cloud_id, **arguments})
        payload = json.loads(result.content[0].text)
        if payload.get("error"):
            raise AtlassianMCPError(f"{tool_name}: {payload.get('message')}")
        return payload["data"]

    async def close(self) -> None:
        await self._exit_stack.aclose()


class JiraMCPClient:
    """Drop-in replacement for JiraClient (direct REST) backed by Atlassian's Remote MCP
    Server — same public interface, so PerformanceAgent needed zero changes; only what
    bootstrap.py constructs changed (learnings.md #4/#12 follow-up)."""

    def __init__(self, session: AtlassianMCPSession, project_key: str = "KAN") -> None:
        self._session = session
        self._project_key = project_key

    async def search_issues(
        self,
        *,
        sprint_index: int | None = None,
        assignee: str | None = None,
        work_type: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """Same structured-search contract as JiraClient — builds JQL internally rather than
        accepting raw JQL from the LLM."""
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

        results: list[dict] = []
        next_page_token: str | None = None
        while True:
            # view="evidence" is required to get `labels` back at all — the default "compact"
            # view omits them entirely (confirmed live), and this project encodes sprint
            # membership/story points as labels ("sprint-6", "points-3"), not native fields.
            arguments: dict = {"jql": jql, "view": "evidence", "maxResults": 100}
            if next_page_token:
                arguments["nextPageToken"] = next_page_token
            data = await self._session.call("searchJiraIssuesUsingJql", arguments)

            for issue in data.get("issues", []):
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

            if data.get("isLast", True) or not data.get("nextPageToken"):
                break
            next_page_token = data["nextPageToken"]

        return results


class ConfluenceMCPClient:
    """Drop-in replacement for ConfluenceClient (direct REST) backed by Atlassian's Remote MCP
    Server — same public interface as JiraMCPClient's rationale above."""

    def __init__(self, session: AtlassianMCPSession, space_key: str = "AP") -> None:
        self._session = session
        self._space_key = space_key

    async def search_pages(self, *, sprint_index: int | None = None) -> list[dict]:
        cql = f'space="{self._space_key}" and type="page"'
        if sprint_index is not None:
            cql += f' and title~"Sprint {sprint_index} Retro"'

        data = await self._session.call("searchConfluence", {"cql": cql})
        return [{"id": r["content"]["id"], "title": r["title"]} for r in data.get("results", [])]

    async def get_page_content(self, page_id: str) -> str:
        # detail="full" is required to get the actual body — the default "summary" detail
        # only returns a short excerpt, confirmed live.
        data = await self._session.call(
            "getConfluenceContent",
            {"content_id": page_id, "content_format": "markdown", "detail": "full"},
        )
        return data["body"]["value"]
