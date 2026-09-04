"""Live smoke test for the web API (Component 9/10) — the one integration in this project that
never had a real, non-fake live check (see CLAUDE.md's "still genuinely missing" note). Talks to
a *running* server over real HTTP, exactly like the frontend does: login -> /chat (consuming the
real SSE stream) -> the Communication Agent's HITL stage/cancel path -> logout, then confirms the
old token is actually dead afterward. Not part of the automated test suite (tests/unit/test_api.py
only ever uses fakes/TestClient) — this hits a real running process and its real dependencies.

Works against either a local dev server or the real deployed Render backend — set
SMOKE_TEST_BASE_URL to switch (defaults to local). Needs real login credentials that match an
entry in APP_USERS_JSON (this script can't derive a plaintext password from the bcrypt hash
stored there), supplied separately via SMOKE_TEST_EMAIL/SMOKE_TEST_PASSWORD.

By default this only ever stages-then-cancels a Communication Agent draft, so it never actually
posts to Slack or sends a real email on every run. Set SMOKE_TEST_CONFIRM_SEND=1 to additionally
exercise one real confirm -> real send, proving the full path works end-to-end, not just the
staging mechanism.

Usage:
    .venv/Scripts/python.exe -m uvicorn api.main:app --port 8000   # in one terminal
    .venv/Scripts/python.exe scripts/smoke_test_api.py             # in another

    # against the deployed backend instead:
    SMOKE_TEST_BASE_URL=https://nexusai-api-ctud.onrender.com .venv/Scripts/python.exe scripts/smoke_test_api.py
"""

from __future__ import annotations

import asyncio
import json
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


async def _wait_for_healthy(client: httpx.AsyncClient, base_url: str, attempts: int = 4) -> None:
    """Render's free tier cold-starts after idle: the first request can 503 with a Retry-After
    header before the container is actually up (documented in CLAUDE.md's Component 13 section,
    "expected, not a broken deploy") — retry through that instead of treating it as a failure."""
    for attempt in range(1, attempts + 1):
        resp = await client.get(f"{base_url}/health")
        if resp.status_code == 200:
            print(f"  /health -> 200 {resp.json()}")
            return
        wait_s = float(resp.headers.get("Retry-After", 3))
        print(f"  /health -> {resp.status_code} (cold start?), retrying in {wait_s}s ({attempt}/{attempts})")
        await asyncio.sleep(wait_s)
    raise SystemExit(f"/health never became healthy after {attempts} attempts — is the server actually running?")


async def _consume_chat_stream(client: httpx.AsyncClient, base_url: str, token: str, message: str) -> dict:
    """POST /chat streams Server-Sent Events (routing_decided, agent_started/finished, tool_called/
    tool_result, then a terminal done/error) — this reads the real stream the same way the
    frontend's TracePanel does, not just a plain JSON response, since that's the actual contract."""
    events: list[dict] = []
    async with client.stream(
        "POST", f"{base_url}/chat", json={"message": message}, headers={"Authorization": f"Bearer {token}"}
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            events.append(event)
            if event["type"] == "done":
                return event["result"]
            if event["type"] == "error":
                raise AssertionError(f"/chat stream returned an error event: {event['error']}")
    raise AssertionError(f"/chat stream ended without a done/error event. Events seen: {events}")


async def main() -> None:
    _load_dotenv(ROOT / ".env")

    base_url = os.environ.get("SMOKE_TEST_BASE_URL", "http://localhost:8000").rstrip("/")
    email = os.environ.get("SMOKE_TEST_EMAIL")
    password = os.environ.get("SMOKE_TEST_PASSWORD")
    confirm_send = os.environ.get("SMOKE_TEST_CONFIRM_SEND", "").lower() in ("1", "true", "yes")

    if not email or not password:
        raise SystemExit(
            "SMOKE_TEST_EMAIL and SMOKE_TEST_PASSWORD must be set to a real entry in APP_USERS_JSON "
            "(plaintext password — this script can't derive one from the bcrypt hash)."
        )

    print(f"Target: {base_url}")

    async with httpx.AsyncClient(timeout=30) as client:
        print("1. Health check")
        await _wait_for_healthy(client, base_url)

        print("2. Login")
        resp = await client.post(f"{base_url}/auth/login", json={"email": email, "password": password})
        assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
        login_data = resp.json()
        token = login_data["token"]
        print(f"  logged in as: {login_data['display_name']}")

        print("3. /auth/me confirms the session")
        resp = await client.get(f"{base_url}/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, f"/auth/me failed: {resp.status_code} {resp.text}"
        assert resp.json()["display_name"] == login_data["display_name"]
        print(f"  /auth/me -> {resp.json()}")

        print("4. Chat: a read-only question routes and answers normally")
        result = await _consume_chat_stream(client, base_url, token, "What's our PTO policy?")
        print(f"  routed_to: {result['routed_to']}")
        assert "knowledge" in result["routed_to"], f"expected knowledge in routing, got {result['routed_to']}"
        knowledge_result = result["results"]["knowledge"]
        assert knowledge_result["content"], "knowledge agent returned empty content"
        assert not knowledge_result["requires_confirmation"]
        print(f"  answer: {knowledge_result['content'][:200]}")

        print("5. Chat: a send request stages a pending HITL draft, does not send yet")
        result = await _consume_chat_stream(
            client, base_url, token, "Post a Slack message saying the API smoke test ran successfully."
        )
        assert "communication" in result["routed_to"], f"expected communication in routing, got {result['routed_to']}"
        comm_result = result["results"]["communication"]
        assert comm_result["requires_confirmation"], "expected a staged draft awaiting confirmation"
        print(f"  drafted: {comm_result['content'][:200]}")

        print("6. Cancel it (default: never actually sends on every smoke-test run)")
        resp = await client.post(
            f"{base_url}/pending/cancel", json={"agent": "communication"}, headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, f"/pending/cancel failed: {resp.status_code} {resp.text}"
        print(f"  {resp.json()['content']}")

        print("7. A follow-up chat message works again now nothing is pending")
        result = await _consume_chat_stream(client, base_url, token, "What's our expense policy?")
        assert "knowledge" in result["routed_to"]
        print("  OK — no lingering 409 pending-conflict from the cancelled draft")

        if confirm_send:
            print("8. SMOKE_TEST_CONFIRM_SEND set — staging and REALLY sending one message")
            result = await _consume_chat_stream(
                client, base_url, token, "Post a Slack message saying the API smoke test's confirm path ran."
            )
            comm_result = result["results"]["communication"]
            assert comm_result["requires_confirmation"]
            resp = await client.post(
                f"{base_url}/pending/confirm",
                json={"agent": "communication"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, f"/pending/confirm failed: {resp.status_code} {resp.text}"
            confirmed = resp.json()
            print(f"  {confirmed['content']}")
            assert "failed" not in confirmed["content"].lower(), f"real send reported a failure: {confirmed}"
        else:
            print("8. Skipped real send (set SMOKE_TEST_CONFIRM_SEND=1 to also test a real confirm -> send)")

        print("9. Logout invalidates the session")
        resp = await client.post(f"{base_url}/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 204, f"/auth/logout failed: {resp.status_code} {resp.text}"

        resp = await client.get(f"{base_url}/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, f"expected the old token to be rejected after logout, got {resp.status_code}"
        print("  old token correctly rejected (401) after logout")

    print("\nAll checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
