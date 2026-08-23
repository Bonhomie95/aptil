"""Redis-backed fixed-window rate limiting for FastAPI routes.

Compliance section 6 ("be a polite automated client") asks us to rate-limit our
own endpoints to prevent abuse of the platform. This provides a small dependency
factory:

    from app.core.ratelimit import RateLimiter

    @router.post("/login", dependencies=[Depends(RateLimiter(times=5, seconds=60))])
    async def login(...):
        ...

The limiter keys on ``client IP + route`` and raises HTTP 429 once the window
budget is exhausted. It uses a fixed window implemented with an atomic Lua
script: the TTL is set ONLY when the counter is first created, so a client that
keeps hammering the endpoint still sees the window roll over instead of being
locked out forever.

``X-Forwarded-For`` is honoured only when the direct peer is a configured
trusted proxy (``TRUSTED_PROXY_IPS``); otherwise the header is attacker-supplied
and would let anyone bypass the limit by rotating it.

It FAILS OPEN: if Redis is unreachable we log a warning and allow the request
rather than locking users out.
"""

from __future__ import annotations

import ipaddress

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Module-level singleton client (redis.asyncio pools connections internally).
_redis_client = None

# INCR the key, and set the TTL only on creation so the window is fixed rather
# than sliding forward with every request. Returns {count, ttl}.
_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""

_script_handle = None


def _get_redis():
    """Lazily create the shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis  # imported lazily; redis is installed

        _redis_client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    return _redis_client


def _get_script():
    """Register (once) and return the fixed-window Lua script handle."""
    global _script_handle
    if _script_handle is None:
        _script_handle = _get_redis().register_script(_WINDOW_SCRIPT)
    return _script_handle


def reset_clients() -> None:
    """Drop cached Redis handles. Used by tests between event loops."""
    global _redis_client, _script_handle
    _redis_client = None
    _script_handle = None


def _is_trusted_peer(peer: str | None) -> bool:
    """True if the direct connection comes from a configured trusted proxy."""
    if not peer:
        return False
    trusted = settings.trusted_proxy_ips
    if not trusted:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """Best-effort client IP.

    ``X-Forwarded-For`` is trusted only when the direct peer is a configured
    trusted proxy — otherwise the header is caller-controlled and rate limits
    could be bypassed by rotating it.
    """
    peer = request.client.host if request.client is not None else None
    if _is_trusted_peer(peer):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                log.warning("ratelimit_bad_forwarded_for", value=candidate[:64])
    return peer or "unknown"


class RateLimiter:
    """FastAPI dependency factory: allow ``times`` requests per ``seconds`` window.

    Instances are callable and used as a dependency, e.g.
    ``Depends(RateLimiter(5, 60))``.

    Pass ``scope="ip"`` (default) to bucket by caller IP, or ``scope="user"`` to
    additionally bucket by the authenticated subject when a bearer token is
    present — useful for expensive per-account endpoints.
    """

    def __init__(
        self,
        times: int,
        seconds: int,
        *,
        prefix: str = "ratelimit",
        scope: str = "ip",
    ) -> None:
        if times < 1:
            raise ValueError("times must be >= 1")
        if seconds < 1:
            raise ValueError("seconds must be >= 1")
        self.times = times
        self.seconds = seconds
        self.prefix = prefix
        self.scope = scope

    def _subject(self, request: Request) -> str:
        """Authenticated subject id when resolvable, else the caller IP."""
        if self.scope != "user":
            return client_ip(request)
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            from app.core.security import decode_token

            try:
                claims = decode_token(auth.split(" ", 1)[1].strip())
                subject = claims.get("sub")
                if subject:
                    return f"user:{subject}"
            except Exception as exc:  # noqa: BLE001 - fall back to IP bucketing
                # An unreadable token is normal here (expired, malformed); the
                # request will be rejected by the auth dependency anyway.
                log.debug("ratelimit_token_unreadable", error=str(exc)[:120])
        return client_ip(request)

    def _key(self, request: Request) -> str:
        # Scope the window to the route (path template) so different endpoints
        # get independent budgets, and to the caller.
        route = request.scope.get("route")
        route_id = getattr(route, "path", None) or request.url.path
        return f"{self.prefix}:{route_id}:{self._subject(request)}"

    async def __call__(self, request: Request, response: Response) -> None:
        key = self._key(request)
        try:
            script = _get_script()
            count, ttl = await script(keys=[key], args=[self.seconds])
            count, ttl = int(count), int(ttl)
        except Exception as exc:
            # Fail open: never block traffic because the limiter backend is down.
            log.warning("ratelimit_backend_unavailable", error=str(exc), key=key)
            return

        remaining = max(self.times - count, 0)
        retry_after = ttl if ttl > 0 else self.seconds
        response.headers["X-RateLimit-Limit"] = str(self.times)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(retry_after)

        if count > self.times:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.times),
                    "X-RateLimit-Remaining": "0",
                },
            )


__all__ = ["RateLimiter", "client_ip", "reset_clients"]
