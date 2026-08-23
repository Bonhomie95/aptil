"""Google OAuth endpoints: /google/login and /google/callback.

Included under the ``/auth`` prefix (see app/api/v1/router.py), so the public
paths are ``/api/v1/auth/google/login`` and ``/api/v1/auth/google/callback`` —
the latter must match ``settings.GOOGLE_REDIRECT_URI``.

The callback is a *browser navigation*, not an XHR: Google redirects the user
agent here. It therefore redirects on to the web app rather than returning JSON
(which would just render as text in the address bar and strand the user).
Tokens are handed over in the URL fragment, which is never sent to a server and
is stripped by the frontend immediately after it reads them.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.services import auth_service, oauth_service

router = APIRouter()
log = get_logger(__name__)

_STATE_COOKIE = "g_oauth_state"


def _frontend_redirect(path: str, fragment: dict[str, str] | None = None,
                       query: dict[str, str] | None = None) -> RedirectResponse:
    url = f"{settings.frontend_base_url}{path}"
    if query:
        url += f"?{urlencode(query)}"
    if fragment:
        url += f"#{urlencode(fragment)}"
    response = RedirectResponse(url, status_code=303)
    response.delete_cookie(_STATE_COOKIE, path="/")
    return response


@router.get(
    "/google/login",
    dependencies=[Depends(RateLimiter(times=20, seconds=60))],
)
async def google_login() -> RedirectResponse:
    """Redirect the browser to Google's consent screen."""
    if not oauth_service.is_configured():
        return _frontend_redirect(
            "/login", query={"error": "google_not_configured"}
        )
    url, signed_state = oauth_service.build_authorization_url()
    response = RedirectResponse(url, status_code=307)
    response.set_cookie(
        _STATE_COOKIE,
        signed_state,
        max_age=oauth_service.STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )
    return response


@router.get(
    "/google/callback",
    include_in_schema=False,
    dependencies=[Depends(RateLimiter(times=20, seconds=60))],
)
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Google's redirect: verify state, exchange code, hand back tokens."""
    if error:
        log.warning("google_oauth_denied", error=error)
        return _frontend_redirect("/login", query={"error": "google_denied"})
    if not code:
        return _frontend_redirect("/login", query={"error": "google_no_code"})

    try:
        oauth_service.verify_state(request.cookies.get(_STATE_COOKIE), state)
        userinfo = await oauth_service.exchange_code_for_userinfo(code)
        user = await oauth_service.get_or_create_user(userinfo)
        tokens = await auth_service.issue_tokens(user)
    except Exception as exc:  # noqa: BLE001 - always land the user somewhere useful
        detail = getattr(exc, "detail", None)
        log.warning("google_oauth_failed", error=str(detail or exc))
        return _frontend_redirect(
            "/login",
            query={"error": "google_failed", "message": str(detail or "Sign-in failed")},
        )

    # Fragment, not query: never logged by proxies, never sent to any server.
    return _frontend_redirect(
        "/auth/callback",
        fragment={
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        },
    )
