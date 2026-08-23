"""Inbound apply-email webhook and the user's inbox.

The webhook is called by the Cloudflare Email Routing worker (infra/email/),
which forwards mail sent to any u-<id>@APPLY_EMAIL_DOMAIN alias as JSON with an
HMAC signature over the raw body. It is unauthenticated in the session sense on
purpose — mail arrives when it arrives — so the HMAC is the whole gate: an
unsigned or missigned request is dropped before any parsing happens.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.models.profile import InboundEmail
from app.models.user import User
from app.services import apply_email

log = get_logger(__name__)
router = APIRouter()


@router.post(
    "/email",
    status_code=status.HTTP_202_ACCEPTED,
    # Per-IP: the worker is the only legitimate caller and batches naturally.
    dependencies=[Depends(RateLimiter(times=120, seconds=60, scope="ip"))],
)
async def receive_email(
    request: Request,
    x_aptil_signature: str | None = Header(default=None),
):
    if not apply_email.aliases_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    raw = await request.body()
    if not apply_email.verify_signature(raw, x_aptil_signature):
        log.warning("inbound_email_bad_signature")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_json"
        ) from exc
    row = await apply_email.ingest(payload if isinstance(payload, dict) else {})
    # 202 either way: the worker cannot fix an unroutable alias, and telling an
    # outside sender which aliases exist would be an enumeration oracle.
    return {"accepted": row is not None}


class InboxItem(BaseModel):
    id: uuid.UUID
    from_address: str
    subject: str
    body_text: str
    kind: str
    sender_domain: str
    received_at: datetime | None = None

    model_config = {"from_attributes": True}


@router.get("/inbox", response_model=list[InboxItem])
async def inbox(
    limit: int = 20,
    user: User = Depends(get_current_user),
):
    """Mail received on the user's apply alias, newest first.

    This is how application status reaches the dashboard without the user
    forwarding anything: confirmations, interview invites and rejections all
    arrive here because the accounts we created used the alias.
    """
    limit = max(1, min(limit, 50))
    rows = (
        await InboundEmail.find(InboundEmail.user_id == user.id)
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    return [
        InboxItem(
            id=r.id,
            from_address=r.from_address,
            subject=r.subject,
            # Cap the body: the dashboard shows a preview, not an email client.
            body_text=(r.body_text or "")[:2000],
            kind=r.kind,
            sender_domain=r.sender_domain,
            received_at=r.created_at,
        )
        for r in rows
    ]
