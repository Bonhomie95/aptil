"""Shared test fixtures.

Integration tests run against a real MongoDB + Redis (the docker-compose stack,
or local services). They are skipped automatically when Mongo is unreachable so
`pytest` still passes in a bare CI container.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-32ch")
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY", "zH8kQmXvNpLrTyWjBdFgCsEuAiOoPqRnMlKhJgFdSaQ="
)
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
# Generated per run, and only a database matching this prefix is ever dropped
# in teardown — see _drop_test_database. Pointing MONGO_DB at a real database
# must never let the suite delete it.
TEST_DB_PREFIX = "aptil_test_"
os.environ.setdefault("MONGO_DB", f"{TEST_DB_PREFIX}{uuid.uuid4().hex[:8]}")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ROOT_USER", "aptil")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "aptil12345")


def _mongo_available() -> bool:
    try:
        from pymongo import MongoClient

        MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=1500).admin.command(
            "ping"
        )
        return True
    except Exception:
        return False


MONGO_UP = _mongo_available()
requires_mongo = pytest.mark.skipif(not MONGO_UP, reason="MongoDB is not reachable")


def _redis_available() -> bool:
    try:
        import redis

        redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


REDIS_UP = _redis_available()
requires_redis = pytest.mark.skipif(not REDIS_UP, reason="Redis is not reachable")


@pytest.fixture(autouse=True)
def clear_rate_limits():
    """Reset the rate-limit windows between tests.

    The limiter is deliberately left ENABLED (a dedicated test covers it); this
    only stops one test's requests from exhausting the budget for the next.
    """
    if not REDIS_UP:
        yield
        return
    import redis

    client = redis.Redis.from_url(os.environ["REDIS_URL"])
    client.flushdb()
    yield
    client.flushdb()


@pytest.fixture(scope="session", autouse=True)
async def _init_beanie():
    """Register the document models once for the whole session.

    Beanie raises CollectionWasNotInitialized on any Document instantiation
    before init_beanie runs, including in tests that never touch the database.
    """
    if not MONGO_UP:
        return
    from app.db.session import init_db

    await init_db()


@pytest.fixture(scope="session")
async def seeded_plans():
    """Seed the plan catalogue once; `ensure_subscription` needs the free plan."""
    from scripts.seed import seed_plans

    await seed_plans()
    return True


@pytest.fixture(scope="session")
async def client(seeded_plans):  # noqa: ARG001 - ordering dependency only
    """Session-scoped ASGI client shared by every test module.

    Lives here rather than in one test file so other modules don't have to
    import it from each other — that shadows the fixture name with the test
    parameter and trips F811 in every test that uses it.
    """
    import httpx
    from httpx import ASGITransport

    from app.db.session import init_db
    from app.main import app

    await init_db()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="session", autouse=True)
def _drop_test_database():
    """Remove the throwaway database when the session ends.

    Refuses to drop anything the suite did not create. Without this guard,
    running with MONGO_DB pointed at a real database (a dev box, or worse)
    would delete it on teardown.
    """
    yield
    db_name = os.environ["MONGO_DB"]
    if not MONGO_UP or not db_name.startswith(TEST_DB_PREFIX):
        return
    from pymongo import MongoClient

    MongoClient(os.environ["MONGO_URL"]).drop_database(db_name)
