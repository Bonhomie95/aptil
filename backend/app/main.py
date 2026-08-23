"""FastAPI application entrypoint."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.services.storage import StorageUnavailable, ensure_bucket

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", environment=settings.ENVIRONMENT, project=settings.PROJECT_NAME)
    await init_db()  # connect Mongo + register Beanie document models
    try:
        ensure_bucket()
    except Exception as exc:  # storage may not be up yet in some dev flows
        log.warning("bucket_init_failed", error=str(exc))
    yield
    log.info("shutdown")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    # Interactive docs are useful in development and needless attack surface in
    # production, where the OpenAPI schema is still available to authenticated
    # tooling if needed.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Request-ID", "X-RateLimit-Remaining", "Retry-After"],
    max_age=600,
)

if settings.is_production:
    # Reject Host headers we do not serve, which blocks host-header poisoning of
    # absolute URLs.
    allowed_hosts = {
        h.split("//")[-1].split("/")[0]
        for h in [*settings.cors_origins, settings.frontend_base_url]
        if h
    }
    # The container healthcheck runs `curl http://127.0.0.1:8000/health` from
    # inside the container, so its Host header is the loopback address. Without
    # these two entries the middleware answers it "Invalid host header" (400)
    # and Docker marks a container unhealthy that is serving real traffic
    # perfectly — which then fails `compose up --wait` and blocks deploys.
    # Starlette strips the port before matching, so bare names are correct here.
    # Loopback is only reachable from within the container, so allowing it does
    # not widen the host-header poisoning surface this middleware exists to
    # close.
    allowed_hosts |= {"127.0.0.1", "localhost"}
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=sorted(allowed_hosts) or ["*"]
    )


class SecurityHeadersMiddleware:
    """Attach a request id and baseline security headers to every response.

    Implemented as pure ASGI rather than ``BaseHTTPMiddleware`` on purpose:
    BaseHTTPMiddleware re-raises exceptions from the inner app *before* the
    registered exception handlers produce a response, which turned
    ``RequestValidationError`` into a 500 instead of a 422.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id")
        request_id = (
            incoming.decode("latin-1")[:64] if incoming else uuid.uuid4().hex[:16]
        )
        # Put the id back on the scope so handlers report the SAME value the
        # response header carries. Reading it from the request headers meant a
        # client that sent none got "request_id": "-" in the error body while
        # the header held a real id — the one thing that id exists to correlate.
        scope["state"] = {**scope.get("state", {}), "request_id": request_id}

        extra: list[tuple[bytes, bytes]] = [
            (b"x-request-id", request_id.encode("latin-1")),
            # This API returns JSON, never HTML — lock the browser down.
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"no-referrer"),
            (b"cross-origin-opener-policy", b"same-origin"),
            (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
        ]
        if settings.is_production:
            extra.append(
                (
                    b"strict-transport-security",
                    b"max-age=31536000; includeSubDomains",
                )
            )

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                present = {k.lower() for k, _ in existing}
                existing.extend((k, v) for k, v in extra if k not in present)
                if b"cache-control" not in present:
                    existing.append((b"cache-control", b"no-store"))
                message["headers"] = existing
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(StorageUnavailable)
async def storage_unavailable_handler(request: Request, exc: StorageUnavailable):
    """File storage is down — say so, rather than returning an opaque 500."""
    log.error("storage_unavailable", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": (
                "File storage is temporarily unavailable, so we couldn't save "
                "that. Please try again in a moment."
            )
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """Last resort: log the detail, return an opaque body with a trace id.

    Internal exception text can carry connection strings and keys, so it never
    reaches the client.
    """
    request_id = getattr(request.state, "request_id", None) or request.headers.get(
        "X-Request-ID", "-"
    )
    log.exception("unhandled_error", path=request.url.path, request_id=request_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "request_id": request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Return a single human-readable message instead of Pydantic's raw array.

    Clients render `detail` directly; an array of error objects showed up in the
    UI as "[object Object]".
    """
    def _describe(error: dict) -> tuple[str, str]:
        location = [str(p) for p in error.get("loc", []) if p not in ("body", "query")]
        field = " → ".join(location) if location else ""
        message = str(error.get("msg", "Invalid value")).removeprefix("Value error, ")
        return field, message

    raw = exc.errors()
    # Pydantic puts the original exception object in `ctx`, which is not JSON
    # serializable — build a plain, safe projection instead of echoing `raw`.
    fields = [
        {"field": field or "request", "message": message}
        for field, message in (_describe(e) for e in raw)
    ]
    if fields:
        first = fields[0]
        detail = (
            f"{first['field']}: {first['message']}"
            if first["field"] != "request"
            else first["message"]
        )
    else:  # pragma: no cover - defensive
        detail = "Invalid request"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": detail, "errors": fields},
    )


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> JSONResponse:
    """Readiness probe over every dependency a request can actually need.

    Mongo alone was not enough to call this instance ready: with Redis down
    every rate-limited route fails open and background work cannot be queued,
    and with object storage down uploads 503. A probe that stays green through
    either is worse than no probe — it routes traffic at a broken instance.

    Redis and storage are reported but do NOT fail the probe on their own: the
    app degrades rather than stops without them, and flapping an instance out of
    the pool for a slow bucket would cause the outage it is meant to prevent.
    """
    checks: dict[str, str] = {}
    ok = True

    try:
        from app.db.session import get_client

        await get_client().admin.command("ping")
        checks["mongo"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["mongo"] = f"error: {type(exc).__name__}"
        ok = False

    try:
        from app.core.ratelimit import _get_redis

        await _get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {type(exc).__name__}"

    try:
        from anyio import to_thread

        from app.services.storage import head_bucket

        await to_thread.run_sync(head_bucket)
        checks["storage"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["storage"] = f"error: {type(exc).__name__}"

    # Informational: without a provider key, CV parsing quietly falls back to
    # the regex baseline (name/email/phone only). Worth surfacing rather than
    # leaving an operator to wonder why profiles come back thin.
    from app.ai.router import has_any_provider

    checks["ai"] = "ok" if has_any_provider() else "not configured"

    degraded = ok and any(v != "ok" for v in checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ok" if not degraded and ok else "degraded" if ok else "down",
            "checks": checks,
        },
    )
