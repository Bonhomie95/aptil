"""Subscription plans (spec point 10)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from app.models.billing import Plan

router = APIRouter()


class PlanRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    price_cents: int
    currency: str
    is_featured: bool
    monthly_applications: int
    monthly_interviews: int
    prep_minutes: int
    features: dict
    # A plan with no price is self-serve; the UI must not send it to Stripe.
    is_free: bool = False
    # False when the plan is priced but has no Stripe price wired up yet, so the
    # UI can disable the button instead of failing at checkout.
    purchasable: bool = True

    model_config = {"from_attributes": True}


@router.get("", response_model=list[PlanRead])
async def list_plans():
    """Public plan catalogue, cheapest first. Drives both the marketing page and
    the in-app plan picker so the two can never drift apart."""
    plans = await Plan.find(Plan.is_active == True).sort(  # noqa: E712
        +Plan.sort_order
    ).to_list()
    out: list[PlanRead] = []
    for plan in plans:
        item = PlanRead.model_validate(plan)
        item.is_free = plan.price_cents <= 0
        item.purchasable = plan.price_cents <= 0 or bool(plan.stripe_price_id)
        out.append(item)
    return out
