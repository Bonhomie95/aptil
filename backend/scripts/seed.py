"""Seed default subscription plans (spec point 10).

Usage (inside the api container):
    python -m scripts.seed

MongoDB is schemaless — there is no table creation step. Beanie creates collections
and indexes on first use / init. This script just upserts the default plans.

The `free` plan is what makes "start without a credit card" true: every new
account is provisioned onto it, so entitlement checks have real quota to read.
"""

from __future__ import annotations

import asyncio

from app.db.session import init_db
from app.models.billing import Plan

# Ladder note: the free tier is a real trial, not a demo — 20 applications is
# roughly a week of active searching, which is long enough to see the product
# work. The paid tiers moved up with it so each still buys a meaningful step
# (5x, 15x, 37x free) and the price per application keeps falling as you go up:
# roughly $0.19, $0.16, $0.13.
DEFAULT_PLANS = [
    dict(code="free", name="Free", price_cents=0, is_featured=False,
         monthly_applications=20, monthly_interviews=2, prep_minutes=30, sort_order=0,
         description="Try it properly: a few weeks of applications and two mock interviews.",
         features={"support": "community"}),
    dict(code="starter", name="Starter", price_cents=1900, is_featured=False,
         monthly_applications=100, monthly_interviews=5, prep_minutes=120, sort_order=1,
         description="Get moving: steady automated applications and regular practice.",
         features={"support": "email", "resume_tailoring": True}),
    dict(code="pro", name="Pro", price_cents=4900, is_featured=True,
         monthly_applications=300, monthly_interviews=15, prep_minutes=400, sort_order=2,
         description="Most popular: serious volume plus regular interview practice.",
         features={"support": "priority", "resume_tailoring": True,
                   "priority_discovery": True}),
    dict(code="accelerate", name="Accelerate", price_cents=9900, is_featured=False,
         monthly_applications=750, monthly_interviews=40, prep_minutes=1000, sort_order=3,
         description="Full-throttle search with deep interview preparation.",
         features={"support": "priority", "resume_tailoring": True,
                   "priority_discovery": True, "deep_prep": True}),
]


async def seed_plans() -> None:
    for spec in DEFAULT_PLANS:
        existing = await Plan.find_one(Plan.code == spec["code"])
        if existing:
            for k, v in spec.items():
                setattr(existing, k, v)
            existing.is_active = True
            existing.touch()
            await existing.save()
        else:
            await Plan(**spec).insert()
    print(f"Seeded {len(DEFAULT_PLANS)} plans.")


async def main() -> None:
    await init_db()
    await seed_plans()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
