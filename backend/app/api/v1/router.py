"""Aggregate v1 routers."""

from fastapi import APIRouter

from app.api.v1.routes import (
    account,
    auth,
    billing,
    credentials,
    inbound,
    interviews,
    jobs,
    oauth,
    onboarding,
    plans,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(oauth.router, prefix="/auth", tags=["auth"])
api_router.include_router(account.router, prefix="/account", tags=["account"])
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
api_router.include_router(
    credentials.router, prefix="/onboarding/credentials", tags=["onboarding"]
)
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(inbound.router, prefix="/inbound", tags=["inbound"])
api_router.include_router(interviews.router, prefix="/interviews", tags=["interviews"])
