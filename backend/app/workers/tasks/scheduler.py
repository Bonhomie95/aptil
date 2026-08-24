"""Periodic sweeps that drive the product loop.

These are the tasks Celery beat fires (see ``app/workers/celery_app.py``). They
fan out to the per-source / per-user tasks so no single tick does unbounded work
inside one job.

Only users who have finished onboarding, verified their email, and still have
entitlement left are swept — the apply engine acts on a user's behalf, so it
must never run for an account that has not completed consent.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import AutomationState
from app.models.profile import Profile
from app.models.user import User
from app.workers.celery_app import celery
from app.workers.db import run_async

log = get_logger(__name__)

# Guardrail so a sweep can never fan out unboundedly.
MAX_USERS_PER_SWEEP = 500


async def _dispatch_per_user_sourcing() -> int:
    """Periodically re-run each eligible user's own web search.

    This is what keeps existing users' pipelines fresh between the events that
    trigger source_for_user directly (CV upload, "Find matches", target change).
    Each user's search is CV-driven and web-wide, so this replaced the old
    aggregator "demand queries" path.
    """
    from app.workers.tasks.sourcing import source_for_user

    dispatched = 0
    users = await _eligible_users()
    for user in users:
        profile = await Profile.find_one(Profile.user_id == user.id)
        # Nothing to search on until they have told us what they want.
        if profile is None or not (profile.target_titles or profile.work_history):
            continue
        source_for_user.delay(str(user.id))
        dispatched += 1
    return dispatched


@celery.task(name="scheduler.run_all_sources")
def run_all_sources() -> dict:
    """Fan out discovery each sweep:

      1. per-user web search (the primary, web-wide, CV-driven source), and
      2. the shipped ATS boards + any operator-configured connector queries,
         which top up the shared pool for everyone.
    """
    from app.workers.tasks.sourcing import run_source

    per_user = run_async(_dispatch_per_user_sourcing())

    # No shipped board list: discovery is the user's own CV-driven web search.
    # sourcing_jobs is an OPTIONAL operator escape hatch (default empty) for
    # pulling a specific company board — it is not a default anyone gets.
    entries = list(settings.sourcing_jobs)
    dispatched = 0
    seen: set[str] = set()
    for entry in entries:
        source = entry.get("source")
        query = entry.get("query") or {}
        if not source:
            continue
        key = f"{source}:{sorted(query.items())}"
        if key in seen:
            continue
        seen.add(key)
        run_source.delay(source, query)
        dispatched += 1
    log.info(
        "sourcing_sweep_dispatched",
        per_user=per_user,
        operator_queries=dispatched,
    )
    return {"per_user": per_user, "board_queries": dispatched}


@celery.task(name="scheduler.match_all_users")
def match_all_users() -> dict:
    return run_async(_match_all())


async def _match_all() -> dict:
    from app.workers.tasks.sourcing import match_for_user

    users = await _eligible_users()
    for user in users:
        # Only bother for users whose profile has something to match on.
        profile = await Profile.find_one(Profile.user_id == user.id)
        if profile is None or not (profile.skills or profile.work_history):
            continue
        match_for_user.delay(str(user.id))
    log.info("matching_sweep_dispatched", count=len(users))
    return {"dispatched": len(users)}


@celery.task(name="scheduler.enqueue_all_users")
def enqueue_all_users() -> dict:
    return run_async(_enqueue_all())


async def _enqueue_all() -> dict:
    from app.workers.tasks.apply import enqueue_for_user

    users = await _eligible_users()
    dispatched = 0
    for user in users:
        # Respect the per-user apply mode: with auto-apply off, discovery still
        # ran for them, but nothing is submitted until they press Apply.
        if not getattr(user, "auto_apply", True):
            continue
        profile = await Profile.find_one(Profile.user_id == user.id)
        if profile is None:
            continue
        # "none" means the user opted out of us attaching a résumé, not out of
        # applying; but an unset profile with no résumé strategy is skipped.
        enqueue_for_user.delay(str(user.id))
        dispatched += 1
    log.info("apply_sweep_dispatched", count=dispatched)
    return {"dispatched": dispatched}


async def _eligible_users() -> list[User]:
    """Users the engine may act for on this sweep.

    automation_state is filtered HERE rather than inside each task, so a paused
    user costs nothing per tick instead of being fanned out and then discarded.
    The `$ne` form also covers accounts created before the field existed, whose
    documents have no automation_state key at all.
    """
    return await User.find(
        User.is_active == True,  # noqa: E712
        User.is_email_verified == True,  # noqa: E712
        User.onboarding_completed == True,  # noqa: E712
        {"automation_state": {"$nin": [
            AutomationState.PAUSED.value,
            AutomationState.STOPPED.value,
        ]}},
    ).limit(MAX_USERS_PER_SWEEP).to_list()
