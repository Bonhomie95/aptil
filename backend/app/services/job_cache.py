"""Fetch-dedup cache: don't re-hit a board/API for a query we just fetched.

The jobs a connector returns are already persisted in the shared Mongo pool, so
once ANY user's sweep has fetched "(remotive, Platform Engineer / US)", every
other user targeting the same role can reuse those jobs instead of triggering
their own identical API call. This turns "one fetch per user per sweep" into
"one fetch per unique query per cache window" — the difference between hammering
a free board and being a good citizen of it.

Backed by Redis (already in the stack). Fails OPEN: any Redis trouble just means
we fetch as before — the cache can never block discovery.
"""

from __future__ import annotations

import hashlib
import json

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client = None


def _redis():
    global _client
    if _client is None:
        import redis

        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def _key(source: str, query: dict) -> str:
    raw = json.dumps({"s": source, "q": query}, sort_keys=True, default=str)
    return "jobfetch:" + hashlib.sha1(raw.encode()).hexdigest()  # noqa: S324


def was_fetched_recently(source: str, query: dict) -> bool:
    """True if this (source, query) is still within the cache window — skip it."""
    if settings.JOB_CACHE_TTL_HOURS <= 0:
        return False
    try:
        return bool(_redis().exists(_key(source, query)))
    except Exception as exc:  # noqa: BLE001 - fail open, never block a sweep
        log.warning("job_cache_check_failed", error=str(exc)[:200])
        return False


def mark_fetched(source: str, query: dict) -> None:
    """Record that (source, query) was just fetched, with the cache TTL."""
    if settings.JOB_CACHE_TTL_HOURS <= 0:
        return
    try:
        _redis().set(
            _key(source, query), "1", ex=settings.JOB_CACHE_TTL_HOURS * 3600
        )
    except Exception as exc:  # noqa: BLE001 - fail open
        log.warning("job_cache_mark_failed", error=str(exc)[:200])


# --- "couldn't apply" skip markers ------------------------------------------
#
# When the apply engine cannot complete a job, we DELETE the application (the
# user never sees anything Aptil could not do) and drop a short-lived marker so
# matching does not immediately recreate it and retry in a tight loop. The
# marker expires, so a transient failure (a CAPTCHA that was there once) is
# retried later rather than banned forever.

_SKIP_TTL_SECONDS = 3 * 24 * 3600  # 3 days


def _skip_key(user_id: str, job_id: str) -> str:
    return f"applyskip:{user_id}:{job_id}"


def mark_unapplicable(user_id: str, job_id: str) -> None:
    try:
        _redis().set(_skip_key(user_id, job_id), "1", ex=_SKIP_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - fail open
        log.warning("apply_skip_mark_failed", error=str(exc)[:200])


def is_unapplicable(user_id: str, job_id: str) -> bool:
    try:
        return bool(_redis().exists(_skip_key(user_id, job_id)))
    except Exception as exc:  # noqa: BLE001 - fail open (retry rather than hide)
        log.warning("apply_skip_check_failed", error=str(exc)[:200])
        return False


# --- periodic-sweep in-flight guard -----------------------------------------
#
# scheduler.py's sweeps (sourcing/matching/apply) re-enqueue every eligible
# user each interval, with no memory of whether that user's task from the
# PREVIOUS interval is even done yet. Each real run takes minutes (sequential
# external API calls), so on a large user base the queue can never drain
# before the next sweep piles more onto it — this marker is set at ENQUEUE
# time (covering queue wait, not just run time) and cleared by the task
# itself on completion, so a sweep skips anyone who already has a pending or
# running unit of work instead of stacking a duplicate behind it. The TTL is
# the backstop: a dead worker or lost task must not permanently block that
# user's sweeps, so callers pass something generous relative to their own
# sweep interval (see scheduler.py).


def _sweep_key(kind: str, user_id: str) -> str:
    return f"sweep:{kind}:{user_id}"


def sweep_in_flight(kind: str, user_id: str) -> bool:
    """True if a sweep-triggered task of this kind is already queued or
    running for this user."""
    try:
        return bool(_redis().exists(_sweep_key(kind, user_id)))
    except Exception as exc:  # noqa: BLE001 - fail open, never block a sweep
        log.warning("sweep_guard_check_failed", kind=kind, error=str(exc)[:200])
        return False


def mark_sweep_started(kind: str, user_id: str, ttl_seconds: int) -> None:
    try:
        _redis().set(_sweep_key(kind, user_id), "1", ex=ttl_seconds)
    except Exception as exc:  # noqa: BLE001 - fail open
        log.warning("sweep_guard_mark_failed", kind=kind, error=str(exc)[:200])


def clear_sweep(kind: str, user_id: str) -> None:
    try:
        _redis().delete(_sweep_key(kind, user_id))
    except Exception as exc:  # noqa: BLE001 - fail open
        log.warning("sweep_guard_clear_failed", kind=kind, error=str(exc)[:200])
