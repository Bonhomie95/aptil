"""Billing: Stripe checkout, webhook ingestion, and subscription status."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user, get_verified_user
from app.core.ratelimit import RateLimiter
from app.models.user import User
from app.services import billing

router = APIRouter()

# Stripe caps webhook payloads well below this; anything larger is not ours.
MAX_WEBHOOK_BYTES = 1024 * 1024


class CheckoutRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=64)


class CheckoutResponse(BaseModel):
    url: str


class SubscriptionSummary(BaseModel):
    subscription_id: uuid.UUID | None = None
    plan_code: str | None = None
    plan_name: str | None = None
    status: str | None = None
    is_free: bool = True
    current_period_start: str | None = None
    current_period_end: str | None = None
    applications_used: int = 0
    applications_limit: int = 0
    interviews_used: int = 0
    interviews_limit: int = 0
    can_apply: bool = False
    can_interview: bool = False
    manage_url_available: bool = False


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=300, scope="user"))],
)
async def checkout(
    body: CheckoutRequest,
    user: User = Depends(get_verified_user),
):
    """Start a Stripe Checkout Session for the given plan; returns its URL."""
    try:
        url = await billing.create_checkout_session(
            user.tenant_id, body.plan_code, customer_email=user.email
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return CheckoutResponse(url=url)


@router.post(
    "/portal",
    response_model=CheckoutResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=300, scope="user"))],
)
async def billing_portal(user: User = Depends(get_verified_user)):
    """Stripe customer portal (change card, cancel) for the caller's tenant."""
    try:
        url = await billing.create_billing_portal_url(user.tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return CheckoutResponse(url=url)


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request):
    """Stripe webhook receiver. Raw body, no auth; verified by signature."""
    payload = await request.body()
    if len(payload) > MAX_WEBHOOK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload too large",
        )
    sig_header = request.headers.get("Stripe-Signature")
    try:
        return await billing.handle_webhook(payload, sig_header)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/subscription", response_model=SubscriptionSummary)
async def my_subscription(user: User = Depends(get_current_user)):
    """Current subscription plus entitlement usage for the caller's tenant."""
    # Resolve through the same path the spend checks use, so a period that has
    # rolled over is reset here too. Reading the raw document instead reported
    # "quota reached" on a subscription that would happily have accepted another
    # application — the dashboard and the apply button disagreed.
    sub, plan = await billing.resolve_entitlement(user.tenant_id)
    if sub is None:
        return SubscriptionSummary()
    app_limit = plan.monthly_applications if plan else 0
    int_limit = plan.monthly_interviews if plan else 0
    used_apps = sub.applications_used or 0
    used_ints = sub.interviews_used or 0
    return SubscriptionSummary(
        subscription_id=sub.id,
        plan_code=plan.code if plan else None,
        plan_name=plan.name if plan else None,
        status=sub.status,
        is_free=bool(plan and plan.price_cents <= 0),
        current_period_start=(
            sub.current_period_start.isoformat() if sub.current_period_start else None
        ),
        current_period_end=(
            sub.current_period_end.isoformat() if sub.current_period_end else None
        ),
        applications_used=used_apps,
        applications_limit=app_limit,
        interviews_used=used_ints,
        interviews_limit=int_limit,
        can_apply=used_apps < app_limit,
        can_interview=used_ints < int_limit,
        manage_url_available=bool(sub.stripe_customer_id) and billing.stripe_configured(),
    )
