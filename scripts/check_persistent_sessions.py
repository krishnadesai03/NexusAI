"""Exercise Supabase Auth and durable conversation storage without calling an LLM."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.auth_service import SupabaseAuthClient, SupabaseTokenVerifier  # noqa: E402
from api.conversation_store import PostgresConversationStore  # noqa: E402


def _load_dotenv(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


async def main() -> None:
    _load_dotenv(ROOT / ".env")
    auth = SupabaseAuthClient.from_env()
    verifier = SupabaseTokenVerifier.from_env()
    store = await PostgresConversationStore.connect(os.environ["DATABASE_URL"])
    conversation = None
    try:
        tokens = await auth.login(os.environ["SMOKE_TEST_EMAIL"], os.environ["SMOKE_TEST_PASSWORD"])
        user = await verifier.verify(tokens.access_token)
        assert await store.is_auth_session_active(user.session_id)
        profile = await store.get_profile(user.id)
        assert profile is not None

        api_headers = {
            "apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"],
            "Authorization": f"Bearer {tokens.access_token}",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            visible = await client.get(
                f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/profiles?select=id,display_name,employee_role",
                headers=api_headers,
            )
            visible.raise_for_status()
            assert [row["id"] for row in visible.json()] == [str(user.id)]
            forbidden = await client.patch(
                f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/profiles?id=eq.{user.id}",
                headers={**api_headers, "Content-Type": "application/json"},
                json={"employee_role": "ceo"},
            )
            assert forbidden.status_code in {401, 403}
        print("RLS exposes only the user's profile and blocks role escalation")

        conversation = await store.create_conversation(user.id, "Persistence integration test")
        turn = await store.save_turn(
            user.id,
            conversation.id,
            "Remember this test message",
            ["knowledge"],
            {
                "knowledge": {
                    "content": "Persistent test response",
                    "citations": [],
                    "requires_confirmation": False,
                }
            },
        )
        restored = await store.list_turns(user.id, conversation.id)
        assert [item.id for item in restored] == [turn.id]
        print(f"Supabase Auth login successful for profile: {profile[0]}")
        print("Conversation survived a database round trip")

        await auth.logout(tokens.access_token)
        for _ in range(10):
            if not await store.is_auth_session_active(user.session_id):
                break
            await asyncio.sleep(0.2)
        assert not await store.is_auth_session_active(user.session_id)
        print("Logout revoked the server-side session")
    finally:
        if conversation is not None:
            await store.delete_conversation(conversation.user_id, conversation.id)
        await store.close()
        await auth.close()


if __name__ == "__main__":
    asyncio.run(main())
