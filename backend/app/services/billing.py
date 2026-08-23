"""Stripe billing: checkout, webhooks, and entitlement metering.

Checkout + webhook keep local Subscription documents in sync with Stripe, and the
metering helpers enforce plan entitlements (monthly applications / interviews)
against the usage counters on the linked Subscription.

Every account gets a Subscription at signup — on the zero-cost ``free`` plan when
they haven't paid — so entitlement checks have something to read and the "start
without a credit card" promise is actually backed by quota.

The Stripe SDK is synchronous; calls are pushed to a worker thread so a slow
Stripe round-trip cannot stall the API event loop.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from anyio import to_thread
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.billing import Plan, StripeEvent, Subscription

log = get_logger(__name__)

# Statuses that grant access to metered entitlements.
ACTIVE_STATUSES = ("trialing", "active", "past_due")
FREE_PLAN_CODE = "free"


def _stripe() -> Any:
    """Return the stripe module with the secret key applied."""
    stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    return stripe


def stripe_configured() -> bool:
    return bool((getattr(settings, "STRIPE_SECRET_KEY", "") or "").strip())


# --------------------------------------------------------------------------- #
# Subscription provisioning
# --------------------------------------------------------------------------- #
async def ensure_subscription(tenant_id: uuid.UUID | str) -> Subscription | None:
    """Guarantee the tenant has a Subscription, defaulting to the free plan.

    Returns None only when no plan exists at all (an unseeded database).
    """
    tenant_uuid = _as_uuid(tenant_id)
    existing = await Subscription.find(
        Subscription.tenant_id == tenant_uuid
    ).sort(-Subscription.created_at).first_or_none()
    if existing is not None:
        return existing

    plan = await Plan.find_one(Plan.code == FREE_PLAN_CODE)
    if plan is None:
        plan = await Plan.find(Plan.is_active == True).sort(  # noqa: E712
            +Plan.sort_order
        ).first_or_none()
    if plan is None:
        log.warning("no_plans_seeded", tenant_id=str(tenant_uuid))
        return None

    now = datetime.now(UTC)
    sub = Subscription(
        tenant_id=tenant_uuid,
        plan_id=plan.id,
        status="trialing",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    try:
        await sub.insert()
    except DuplicateKeyError:  # pragma: no cover - concurrent provisioning
        return await Subscription.find(
            Subscription.tenant_id == tenant_uuid
        ).sort(-Subscription.created_at).first_or_none()
    return sub


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
async def create_checkout_session(
    tenant_id: uuid.UUID | str, plan_code: str, customer_email: str | None = None
) -> str:
    """Create a Stripe Checkout Session for `plan_code` and return its URL."""
    tenant_uuid = _as_uuid(tenant_id)

    if not stripe_configured():
        raise ValueError(
            "Payments are not configured on this server yet. "
            "Please try again later or contact support."
        )

    plan = await Plan.find_one(Plan.code == plan_code)
    if plan is None or not plan.is_active:
        raise ValueError(f"Unknown plan: {plan_code}")
    if plan.price_cents <= 0:
        raise ValueError("The free plan does not require checkout.")
    if not plan.stripe_price_id:
        raise ValueError(f"Plan {plan_code} is not available for purchase yet.")

    # Reuse the tenant's Stripe customer so repeat checkouts do not create a new
    # customer record (and a split billing history) every time.
    sub = await ensure_subscription(tenant_uuid)
    existing_customer = sub.stripe_customer_id if sub else None

    kwargs: dict[str, Any] = dict(
        mode="subscription",
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        success_url=settings.STRIPE_SUCCESS_URL,
        cancel_url=settings.STRIPE_CANCEL_URL,
        client_reference_id=str(tenant_uuid),
        metadata={"tenant_id": str(tenant_uuid), "plan_code": plan_code},
        subscription_data={
            "metadata": {"tenant_id": str(tenant_uuid), "plan_code": plan_code}
        },
    )
    if existing_customer:
        kwargs["customer"] = existing_customer
    elif customer_email:
        kwargs["customer_email"] = customer_email

    def _create():
        return _stripe().checkout.Session.create(**kwargs)

    try:
        session = await to_thread.run_sync(_create)
    except Exception as exc:  # noqa: BLE001 - surface a clean message, not a trace
        log.error("stripe_checkout_failed", tenant_id=str(tenant_uuid), error=str(exc))
        raise ValueError("Could not start checkout. Please try again.") from exc

    log.info("stripe_checkout_created", tenant_id=str(tenant_uuid), plan_code=plan_code)
    return session.url


async def create_billing_portal_url(tenant_id: uuid.UUID | str) -> str:
    """Stripe customer portal so users can cancel or change payment method."""
    sub = await get_any_subscription(tenant_id)
    if sub is None or not sub.stripe_customer_id:
        raise ValueError("No billing account yet. Choose a paid plan first.")
    if not stripe_configured():
        raise ValueError("Payments are not configured on this server yet.")

    def _create():
        return _stripe().billing_portal.Session.create(
            customer=sub.stripe_customer_id,
            return_url=f"{settings.frontend_base_url}/plans",
        )

    try:
        portal = await to_thread.run_sync(_create)
    except Exception as exc:  # noqa: BLE001
        log.error("stripe_portal_failed", error=str(exc))
        raise ValueError("Could not open the billing portal. Please try again.") from exc
    return portal.url


# --------------------------------------------------------------------------- #
# Webhook
# --------------------------------------------------------------------------- #
async def handle_webhook(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    """Verify + process a Stripe webhook, upserting local Subscription documents."""
    secret = (getattr(settings, "STRIPE_WEBHOOK_SECRET", "") or "").strip()
    if not secret:
        # Without a signing secret any caller could forge subscription upgrades.
        log.error("stripe_webhook_secret_missing")
        raise ValueError("Webhook signing secret is not configured")
    try:
        event = _stripe().Webhook.construct_event(payload, sig_header, secret)
    except Exception as exc:  # signature / parse failure
        log.error("stripe_webhook_invalid", error=str(exc))
        raise ValueError("Invalid Stripe webhook signature") from exc

    event_id = event.get("id")
    event_type = event["type"]

    # Stripe retries aggressively and replays are possible; process each id once.
    if event_id:
        try:
            await StripeEvent(event_id=event_id).insert()
        except DuplicateKeyError:
            log.info("stripe_webhook_duplicate", event_id=event_id, event_type=event_type)
            return {"received": True, "type": event_type, "duplicate": True}

    obj = event["data"]["object"]
    log.info("stripe_webhook", event_type=event_type, event_id=event_id)

    if event_type == "checkout.session.completed":
        await _on_checkout_completed(obj)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _upsert_subscription(obj)
    elif event_type == "customer.subscription.deleted":
        await _on_subscription_deleted(obj)

    return {"received": True, "type": event_type}


async def _on_checkout_completed(obj: dict[str, Any]) -> None:
    tenant_id = _tenant_from_metadata(obj)
    plan_code = (obj.get("metadata") or {}).get("plan_code")
    stripe_customer_id = obj.get("customer")
    stripe_subscription_id = obj.get("subscription")
    if tenant_id is None:
        log.error("stripe_checkout_no_tenant", session_id=obj.get("id"))
        return

    plan = await _resolve_plan(plan_code)
    if plan is None:
        log.error("stripe_checkout_unresolvable_plan", plan_code=plan_code)
        return

    sub = await _get_or_create_subscription(
        tenant_id=tenant_id,
        stripe_subscription_id=stripe_subscription_id,
        plan=plan,
    )
    if sub is None:
        return
    if stripe_customer_id:
        sub.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        sub.stripe_subscription_id = stripe_subscription_id
    sub.status = "active"
    # A paid upgrade starts a fresh allowance.
    sub.applications_used = 0
    sub.interviews_used = 0
    sub.touch()
    await sub.save()


async def _upsert_subscription(obj: dict[str, Any]) -> None:
    tenant_id = _tenant_from_metadata(obj)
    stripe_subscription_id = obj.get("id")
    plan_code = (obj.get("metadata") or {}).get("plan_code")

    sub = None
    if stripe_subscription_id:
        sub = await Subscription.find_one(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
    if sub is None and tenant_id is not None:
        plan = await _resolve_plan(plan_code)
        if plan is None:
            log.error("stripe_subscription_unresolvable_plan", plan_code=plan_code)
            return
        sub = await _get_or_create_subscription(
            tenant_id=tenant_id,
            stripe_subscription_id=stripe_subscription_id,
            plan=plan,
        )
    if sub is None:
        log.error("stripe_subscription_unlinked", stripe_id=stripe_subscription_id)
        return

    if stripe_subscription_id:
        sub.stripe_subscription_id = stripe_subscription_id
    if obj.get("customer"):
        sub.stripe_customer_id = obj.get("customer")
    if obj.get("status"):
        sub.status = obj["status"]

    new_start = _period_start(obj)
    new_end = _period_end(obj)
    # A new billing period begins -> reset metered usage counters.
    if new_start is not None and _naive_utc(sub.current_period_start) != new_start:
        sub.applications_used = 0
        sub.interviews_used = 0
    if new_start is not None:
        sub.current_period_start = new_start
    if new_end is not None:
        sub.current_period_end = new_end
    sub.touch()
    await sub.save()


async def _on_subscription_deleted(obj: dict[str, Any]) -> None:
    stripe_subscription_id = obj.get("id")
    sub = None
    if stripe_subscription_id:
        sub = await Subscription.find_one(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
    if sub is None:
        return
    # Drop back to the free plan rather than leaving the account with no access
    # at all, and clear the Stripe link so a future checkout starts clean.
    free_plan = await Plan.find_one(Plan.code == FREE_PLAN_CODE)
    sub.status = "canceled" if free_plan is None else "trialing"
    if free_plan is not None:
        sub.plan_id = free_plan.id
        sub.applications_used = 0
        sub.interviews_used = 0
        now = datetime.now(UTC)
        sub.current_period_start = now
        sub.current_period_end = now + timedelta(days=30)
    sub.stripe_subscription_id = None
    sub.touch()
    await sub.save()


# --------------------------------------------------------------------------- #
# Entitlement metering
# --------------------------------------------------------------------------- #
async def get_active_subscription(
    tenant_id: uuid.UUID | str,
) -> Subscription | None:
    """Return the tenant's most recent access-granting subscription, if any."""
    tenant_uuid = _as_uuid(tenant_id)
    return await Subscription.find(
        Subscription.tenant_id == tenant_uuid,
        {"status": {"$in": list(ACTIVE_STATUSES)}},
    ).sort(-Subscription.created_at).first_or_none()


async def get_any_subscription(tenant_id: uuid.UUID | str) -> Subscription | None:
    tenant_uuid = _as_uuid(tenant_id)
    return await Subscription.find(
        Subscription.tenant_id == tenant_uuid
    ).sort(-Subscription.created_at).first_or_none()


async def _plan_for(sub: Subscription) -> Plan | None:
    return await Plan.get(sub.plan_id)


async def _resolved(tenant_id: uuid.UUID | str) -> tuple[Subscription | None, Plan | None]:
    sub = await get_active_subscription(tenant_id)
    if sub is None:
        sub = await ensure_subscription(tenant_id)
        if sub is None or sub.status not in ACTIVE_STATUSES:
            return None, None
    if await _maybe_reset_period(sub):
        await sub.save()
    return sub, await _plan_for(sub)


async def resolve_entitlement(
    tenant_id: uuid.UUID | str,
) -> tuple[Subscription | None, Plan | None]:
    """The tenant's subscription and plan, with an elapsed period already reset.

    Public because the API has to report the same numbers the spend checks act
    on; reading the raw Subscription gave the dashboard stale counters.
    """
    return await _resolved(tenant_id)


async def can_apply(tenant_id: uuid.UUID | str) -> bool:
    """True if the tenant may submit another application this billing period."""
    sub, plan = await _resolved(tenant_id)
    if sub is None or plan is None:
        return False
    return sub.applications_used < plan.monthly_applications


async def can_interview(tenant_id: uuid.UUID | str) -> bool:
    """True if the tenant may run another mock interview this billing period."""
    sub, plan = await _resolved(tenant_id)
    if sub is None or plan is None:
        return False
    return sub.interviews_used < plan.monthly_interviews


async def increment_application_usage(tenant_id: uuid.UUID | str) -> Subscription:
    """Consume one application from the tenant's entitlement."""
    return await _increment(tenant_id, "applications_used")


async def increment_interview_usage(tenant_id: uuid.UUID | str) -> Subscription:
    """Consume one interview from the tenant's entitlement."""
    return await _increment(tenant_id, "interviews_used")


async def _increment(tenant_id: uuid.UUID | str, field: str) -> Subscription:
    sub = await get_active_subscription(tenant_id) or await ensure_subscription(tenant_id)
    if sub is None:
        raise ValueError("No active subscription for tenant")
    reset = await _maybe_reset_period(sub)
    # Atomic $inc so two concurrent workers cannot both read the same counter
    # and overwrite each other's increment.
    update: dict[str, Any] = {"$inc": {field: 1}}
    if reset:
        other = "interviews_used" if field == "applications_used" else "applications_used"
        # Persist the rolled-forward window too. Writing only the counters left
        # `current_period_end` in the past, so the next call reset them again —
        # an expired subscription would have metered nothing, forever.
        update["$set"] = {
            other: 0,
            field: 1,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
        }
        update.pop("$inc")
    await Subscription.find_one(Subscription.id == sub.id).update(update)
    refreshed = await Subscription.get(sub.id)
    return refreshed or sub


async def _maybe_reset_period(sub: Subscription) -> bool:
    """Reset usage counters (in memory) if the stored billing period elapsed.

    The webhook resets on period rollover; this is the safety net for a metered
    action that lands after `current_period_end` but before Stripe's update.
    Returns True when a reset was applied.
    """
    end = sub.current_period_end
    if end is None:
        return False
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if datetime.now(UTC) <= end:
        return False
    sub.applications_used = 0
    sub.interviews_used = 0
    # Roll the window forward so the reset is not re-applied on every call.
    sub.current_period_start = end
    sub.current_period_end = end + timedelta(days=30)
    return True


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return None


def _period_start(obj: dict[str, Any]) -> datetime | None:
    return _period_field(obj, "current_period_start")


def _period_end(obj: dict[str, Any]) -> datetime | None:
    return _period_field(obj, "current_period_end")


def _period_field(obj: dict[str, Any], field: str) -> datetime | None:
    """Read a billing-period boundary from either API shape.

    Stripe moved ``current_period_start`` / ``current_period_end`` off the
    subscription and onto its items in the 2025-03 API version. Read the
    top-level field when present, otherwise fall back to the first item, so the
    usage reset keeps working across API versions.
    """
    direct = _ts(obj.get(field))
    if direct is not None:
        return direct
    items = (obj.get("items") or {}).get("data") or []
    for item in items:
        value = _ts((item or {}).get(field))
        if value is not None:
            return value
    return None


def _tenant_from_metadata(obj: dict[str, Any]) -> uuid.UUID | None:
    meta = obj.get("metadata") or {}
    raw = meta.get("tenant_id") or obj.get("client_reference_id")
    if not raw:
        return None
    try:
        return _as_uuid(raw)
    except (ValueError, AttributeError):
        return None


async def _resolve_plan(plan_code: str | None) -> Plan | None:
    """Resolve the plan a webhook refers to.

    Returns None when it cannot be determined. Guessing here (the previous
    "fall back to any active plan" behaviour) could silently grant a tenant an
    entitlement tier they never bought.
    """
    if not plan_code:
        return None
    return await Plan.find_one(Plan.code == plan_code)


async def _get_or_create_subscription(
    *,
    tenant_id: uuid.UUID,
    stripe_subscription_id: str | None,
    plan: Plan,
) -> Subscription | None:
    sub = None
    if stripe_subscription_id:
        sub = await Subscription.find_one(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
    if sub is None:
        sub = await Subscription.find(
            Subscription.tenant_id == tenant_id
        ).sort(-Subscription.created_at).first_or_none()
    if sub is None:
        sub = Subscription(tenant_id=tenant_id, plan_id=plan.id, status="trialing")
        try:
            await sub.insert()
        except DuplicateKeyError:  # pragma: no cover
            return await Subscription.find(
                Subscription.tenant_id == tenant_id
            ).sort(-Subscription.created_at).first_or_none()
    else:
        sub.plan_id = plan.id
        sub.touch()
        await sub.save()
    return sub
