"""Safe Slack/email capture clients and the session-owned Demo Outbox API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from api.auth_service import AuthenticatedUser
from api.conversation_store import ConversationStore, DemoDelivery
from api.dependencies import get_conversation_store, get_current_session
from api.schemas import DemoDeliveryResponse

router = APIRouter(prefix="/demo/outbox", tags=["demo-outbox"])

_RECIPIENT_NAMES = {
    "priyanair": "Priya Nair",
    "marcuschen": "Marcus Chen",
    "jordanlee": "Jordan Lee",
    "sofiareyes": "Sofia Reyes",
}


def _response(delivery: DemoDelivery) -> DemoDeliveryResponse:
    return DemoDeliveryResponse(
        id=delivery.id,
        persona_slug=delivery.persona_slug,
        channel=delivery.channel,
        recipient=delivery.recipient,
        subject=delivery.subject,
        content=delivery.content,
        status=delivery.status,
        created_at=delivery.created_at,
        expires_at=delivery.expires_at,
    )


class DemoSlackClient:
    def __init__(self, store: ConversationStore, session_id: UUID, persona_slug: str) -> None:
        self._store = store
        self._session_id = session_id
        self._persona_slug = persona_slug

    async def send_message(self, text: str) -> dict:
        delivery = await self._store.create_demo_delivery(
            self._session_id,
            self._persona_slug,
            "slack",
            "Nexus Demo Slack Channel",
            None,
            text,
        )
        return {
            "delivery_id": str(delivery.id),
            "destination": "Demo Outbox",
            "status": delivery.status,
            "simulated": True,
        }


class DemoEmailClient:
    def __init__(self, store: ConversationStore, session_id: UUID, persona_slug: str) -> None:
        self._store = store
        self._session_id = session_id
        self._persona_slug = persona_slug

    async def send_email(self, subject: str, body: str, recipient_alias: str | None = None) -> dict:
        recipient = _RECIPIENT_NAMES.get(recipient_alias or "", "Demo Inbox")
        delivery = await self._store.create_demo_delivery(
            self._session_id,
            self._persona_slug,
            "email",
            recipient,
            subject,
            body,
        )
        return {
            "delivery_id": str(delivery.id),
            "destination": "Demo Outbox",
            "recipient": recipient,
            "status": delivery.status,
            "simulated": True,
        }


@router.get("", response_model=list[DemoDeliveryResponse])
async def list_demo_outbox(
    user: AuthenticatedUser = Depends(get_current_session),
    store: ConversationStore = Depends(get_conversation_store),
) -> list[DemoDeliveryResponse]:
    if not user.is_demo:
        raise HTTPException(status_code=403, detail="Demo Outbox is available only in demo sessions.")
    deliveries = await store.list_demo_deliveries(user.id)
    return [_response(delivery) for delivery in deliveries]
