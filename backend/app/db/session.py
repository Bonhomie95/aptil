"""MongoDB connection + Beanie initialization.

- API (async): `init_db()` is called once at FastAPI startup.
- Workers (sync Celery tasks): call `run_async(coro)` which lazily initializes Beanie
  on the worker's event loop, then runs the coroutine. This lets task code use the
  same Beanie Document models as the API.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from beanie import init_beanie
from pymongo import AsyncMongoClient

from app.core.config import settings

# Beanie 2.x drives MongoDB through PyMongo's native async client (Motor is retired).
_client: AsyncMongoClient | None = None


def get_client() -> AsyncMongoClient:
    global _client
    if _client is None:
        kwargs: dict = {"uuidRepresentation": "standard"}
        url = settings.MONGO_URL or ""
        if url.startswith("mongodb+srv://") or "tls=true" in url.lower():
            # Atlas is TLS-only. Point at certifi's bundle rather than the
            # platform store: the containers have ca-certificates, a bare
            # macOS/venv host often does not, and the failure is an opaque
            # CERTIFICATE_VERIFY_FAILED at connect time.
            import certifi

            kwargs["tlsCAFile"] = certifi.where()
        _client = AsyncMongoClient(url, **kwargs)
    return _client


async def init_db() -> None:
    """Initialize Beanie with all document models. Idempotent per process."""
    from app.models import document_models

    await init_beanie(
        database=get_client()[settings.MONGO_DB],
        document_models=document_models,
    )


_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_initialized = False


def run_async[T](coro: Awaitable[T]) -> T:
    """Run an async coroutine from sync Celery task code.

    Reuses one event loop per worker process and initializes Beanie once. Motor is
    bound to the loop it was created on, so we must reuse the same loop across tasks.
    """
    global _worker_loop, _worker_initialized
    if _worker_loop is None:
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    if not _worker_initialized:
        _worker_loop.run_until_complete(init_db())
        _worker_initialized = True
    return _worker_loop.run_until_complete(coro)
