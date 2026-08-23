"""Plans and subscriptions with entitlement metering."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.db.base import TenantDocument, TimestampedDocument


class Plan(TimestampedDocument):
    """A subscription tier. 3–5 of these; middle one flagged `is_featured`."""

    code: str
    name: str
    description: str | None = None
    price_cents: int
    currency: str = "USD"
    is_featured: bool = False
    is_active: bool = True
    sort_order: int = 0

    monthly_applications: int = 0
    monthly_interviews: int = 0
    prep_minutes: int = 0
    features: dict[str, Any] = Field(default_factory=dict)

    stripe_price_id: str | None = None

    class Settings:
        name = "plans"
        indexes = [IndexModel([("code", ASCENDING)], unique=True)]


class Subscription(TenantDocument):
    plan_id: uuid.UUID
    status: str = "trialing"

    current_period_start: datetime | None = None
    current_period_end: datetime | None = None

    # Usage counters, reset each billing period (entitlement metering).
    applications_used: int = 0
    interviews_used: int = 0

    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    class Settings:
        name = "subscriptions"
        indexes = [
            IndexModel([("tenant_id", ASCENDING)]),
            IndexModel(
                [("stripe_subscription_id", ASCENDING)],
                unique=True,
                partialFilterExpression={
                    "stripe_subscription_id": {"$type": "string"}
                },
            ),
        ]


class StripeEvent(TimestampedDocument):
    """Processed Stripe webhook ids, for idempotency against retries/replays."""

    event_id: str

    class Settings:
        name = "stripe_events"
        indexes = [
            IndexModel([("event_id", ASCENDING)], unique=True),
            IndexModel([("created_at", ASCENDING)], expireAfterSeconds=2592000),
        ]
