from types import SimpleNamespace

import pytest

from enterprise_ai.integrations.atlassian.mcp_client import AtlassianMCPError, AtlassianMCPSession


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def _result(*, text: str, is_error: bool = False, structured_content=None):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        is_error=is_error,
        structured_content=structured_content,
    )


async def test_call_reports_plain_text_mcp_errors() -> None:
    session = FakeSession(_result(text="Failed to fetch accessible products: 401", is_error=True))
    client = AtlassianMCPSession(session, "cloud-1", SimpleNamespace())

    with pytest.raises(AtlassianMCPError, match="401"):
        await client.call("searchJiraIssuesUsingJql", {"jql": 'project = "KAN"'})


async def test_call_accepts_legacy_text_data_envelope() -> None:
    session = FakeSession(_result(text='{"data": {"issues": []}}'))
    client = AtlassianMCPSession(session, "cloud-1", SimpleNamespace())

    result = await client.call("searchJiraIssuesUsingJql", {"jql": 'project = "KAN"'})

    assert result == {"issues": []}
    assert session.calls[0][1]["cloudId"] == "cloud-1"


async def test_call_accepts_v2_structured_content() -> None:
    session = FakeSession(_result(text="", structured_content={"issues": []}))
    client = AtlassianMCPSession(session, "cloud-1", SimpleNamespace())

    assert await client.call("searchJiraIssuesUsingJql", {}) == {"issues": []}
