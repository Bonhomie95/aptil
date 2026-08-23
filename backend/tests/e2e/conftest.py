"""E2E fixtures.

These tests drive the *running* dev stack, so they share its Redis. The rate
limiter is deliberately left enabled (dedicated tests cover it) — this only
clears the per-IP windows between tests so one test's signups do not exhaust
the budget for the next.
"""

from __future__ import annotations

import os

import pytest

WEB_URL = os.environ.get("WEB_URL", "http://localhost:3000")


def _redis_candidates() -> list[str]:
    """Where the running stack's Redis might be, best guess first.

    REDIS_URL itself is usually useless here: against docker-compose it is
    `redis://redis:6379`, a hostname that only resolves *inside* the compose
    network. Falling back to a fixed localhost:6379 was no better, because the
    compose file lets the host port be remapped (REDIS_HOST_PORT) — which is
    exactly what you do when a native Redis already owns 6379.
    """
    explicit = os.environ.get("E2E_REDIS_URL")
    if explicit:
        return [explicit]
    port = os.environ.get("REDIS_HOST_PORT", "6379")
    configured = os.environ.get("REDIS_URL", "")
    candidates = [f"redis://localhost:{port}/0"]
    if port != "6379":
        candidates.append("redis://localhost:6379/0")
    # Only useful when the suite itself runs inside the compose network.
    if configured and configured not in candidates:
        candidates.append(configured)
    return candidates


def _reachable_redis() -> tuple[object | None, list[str]]:
    """``(client, attempts)``. Resolved once per session.

    The attempt log is returned rather than swallowed so the skip message can
    say what was tried and why each one failed — "cannot reach Redis" alone
    sends you looking in the wrong place.
    """
    attempts: list[str] = []
    try:
        import redis
    except ImportError:  # pragma: no cover
        return None, ["redis package is not installed"]
    for url in _redis_candidates():
        try:
            client = redis.Redis.from_url(url, socket_connect_timeout=2)
            client.ping()
            return client, attempts
        except Exception as exc:  # noqa: BLE001 - record it, try the next
            attempts.append(f"{url}: {type(exc).__name__}")
    return None, attempts

# Every route the suite touches. `next dev` compiles routes lazily on first
# request, which can take many seconds and makes the first test to reach a page
# look like a product timeout. Warming them once up front removes the compiler
# from every subsequent measurement. Harmless against a production build.
ROUTES = [
    "/",
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/auth/callback",
    "/dashboard",
    "/jobs",
    "/interview",
    "/plans",
    "/settings",
    "/terms",
    "/privacy",
]


@pytest.fixture(scope="session", autouse=True)
def warm_routes():
    try:
        import httpx

        with httpx.Client(timeout=90) as client:
            for route in ROUTES:
                try:
                    client.get(f"{WEB_URL}{route}")
                except Exception as exc:  # noqa: BLE001 - warming is best-effort
                    print(f"warm {route} failed: {type(exc).__name__}")
    except ImportError:  # pragma: no cover
        print("httpx unavailable; skipping route warm-up")
    yield


@pytest.fixture(scope="session")
def rate_limit_redis():
    """Redis handle used to reset the limiter between tests.

    Skips the suite when it cannot be reached, rather than carrying on.
    Silently continuing was worse than useless: the limiter allows 5 signups per
    5 minutes per IP, so from the sixth test onward every registration came back
    429 and the suite reported eleven unrelated-looking UI failures. A stated
    skip is honest; a red herring is not.
    """
    client, attempts = _reachable_redis()
    if client is None:
        pytest.skip(
            "cannot reach the stack's Redis to reset rate-limit windows, so "
            "these tests would fail on 429 rather than on anything real. Set "
            "E2E_REDIS_URL (or REDIS_HOST_PORT) to the host-side address. "
            f"Tried — {'; '.join(attempts)}"
        )
    return client


@pytest.fixture(autouse=True)
def clear_rate_limit_windows(rate_limit_redis):
    # Scoped delete: never flush the whole DB, which also holds Celery state.
    keys = list(rate_limit_redis.scan_iter("ratelimit:*", count=500))
    if keys:
        rate_limit_redis.delete(*keys)
    yield


def mongo_client():
    """MongoClient for the test harness.

    Atlas (`mongodb+srv://`) needs an explicit CA bundle on machines whose Python
    has no system trust store — the usual macOS symptom is
    `CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`. The app
    itself now does the same (see app/db/session.py); this is the harness's own
    connection from the host.
    """
    from pymongo import MongoClient

    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    kwargs = {"serverSelectionTimeoutMS": 20000}
    if url.startswith("mongodb+srv://") or "mongodb.net" in url:
        import certifi

        kwargs["tlsCAFile"] = certifi.where()
    return MongoClient(url, **kwargs)
