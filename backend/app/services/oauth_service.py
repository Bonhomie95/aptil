"""Google OAuth business logic (Authlib).

Flow:
- ``build_authorization_url`` creates the Google consent URL plus a signed CSRF
  state value. The router stores the signed state in an httpOnly cookie.
- ``verify_state`` re-checks that signed value against the ``state`` Google echoes
  back on the callback.
- ``exchange_code_for_userinfo`` swaps the authorization ``code`` for tokens and
  fetches the OpenID userinfo document.
- ``get_or_create_user`` mirrors ``auth_service.register_user`` for tenant
  creation and links the Google identity.

Security notes:
- Google's ``email_verified`` claim is REQUIRED before we trust the address.
  Without that check, anyone able to attach an unverified address to a Google
  identity could link to — and take over — an existing account with that email.
- Linking to a pre-existing local account only happens when the local account is
  already email-verified, i.e. its owner has proven control of the same inbox.
- CSRF state is signed with itsdangerous instead of a server-side session, so we
  do not need Starlette session middleware.
"""

from __future__ import annotations

from typing import Any

from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tenant import Tenant
from app.models.user import User

log = get_logger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - public URL
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPE = "openid email profile"

_STATE_SALT = "google-oauth-state"
STATE_MAX_AGE_SECONDS = 600  # signed-state / cookie lifetime


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_STATE_SALT)


def _client(**kwargs: Any) -> AsyncOAuth2Client:
    return AsyncOAuth2Client(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
        scope=GOOGLE_SCOPE,
        **kwargs,
    )


def is_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def build_authorization_url() -> tuple[str, str]:
    """Return ``(authorization_url, signed_state)``.

    The caller must round-trip ``signed_state`` (typically via a cookie) and hand
    it back to :func:`verify_state` on the callback.
    """
    if not is_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google sign-in is not configured on this server.",
        )
    client = _client()
    url, state = client.create_authorization_url(
        GOOGLE_AUTH_ENDPOINT,
        access_type="offline",
        prompt="consent",
    )
    return url, _serializer().dumps(state)


def verify_state(signed_state: str | None, returned_state: str | None) -> None:
    """Validate the CSRF state Google echoed back against our signed cookie value."""
    if not signed_state or not returned_state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    try:
        original = _serializer().loads(signed_state, max_age=STATE_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise HTTPException(status_code=400, detail="OAuth state expired") from exc
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc
    if not isinstance(original, str) or original != returned_state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch")


async def exchange_code_for_userinfo(code: str) -> dict[str, Any]:
    """Exchange the authorization ``code`` for tokens and fetch the userinfo doc."""
    async with _client() as client:
        try:
            await client.fetch_token(
                GOOGLE_TOKEN_ENDPOINT,
                code=code,
                grant_type="authorization_code",
            )
            resp = await client.get(GOOGLE_USERINFO_ENDPOINT)
            resp.raise_for_status()
        except HTTPException:
            raise
        except Exception as exc:  # network / OAuth errors
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google OAuth exchange failed",
            ) from exc
        return resp.json()


def _truthy(value: Any) -> bool:
    """Google returns email_verified as a bool, but tolerate the string form."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


async def get_or_create_user(userinfo: dict[str, Any]) -> User:
    """Find-or-create a ``User`` (and its ``Tenant``) from a Google userinfo doc."""
    from app.services.auth_service import (
        _provision_subscription,
        ensure_profile,
        normalize_email,
    )

    email = normalize_email(userinfo.get("email") or "")
    google_sub = userinfo.get("sub")
    if not email or not google_sub:
        raise HTTPException(
            status_code=400, detail="Google profile is missing an email address"
        )
    if not _truthy(userinfo.get("email_verified")):
        # Never trust an unverified address: it is the whole basis for matching
        # this identity to an account.
        log.warning("google_email_unverified", email=email)
        raise HTTPException(
            status_code=400,
            detail="Your Google account's email address is not verified.",
        )

    # Prefer matching on the immutable Google subject id; fall back to email.
    user = await User.find_one(User.google_sub == google_sub)
    if user is None:
        user = await User.find_one(User.email == email)

    if user is None:
        # Each new signup gets its own tenant (1:1 for now; teams later).
        full_name = (userinfo.get("name") or "").strip() or None
        tenant = Tenant(name=full_name or email.split("@")[0])
        await tenant.insert()
        from datetime import UTC, datetime

        user = User(
            tenant_id=tenant.id,
            email=email,
            full_name=full_name,
            google_sub=google_sub,
            is_email_verified=True,  # Google verified the address for us.
            accepted_terms_at=datetime.now(UTC),
        )
        try:
            await user.insert()
        except Exception:
            await tenant.delete()
            raise
        await ensure_profile(user)
        await _provision_subscription(user)
        return user

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    if user.google_sub and user.google_sub != google_sub:
        raise HTTPException(
            status_code=409,
            detail="This email is already linked to a different Google account.",
        )

    if not user.google_sub:
        # Auto-linking to a local account is only safe when that account has
        # itself proven control of the inbox. Otherwise an attacker who
        # pre-registered the address would be handed the session.
        if not user.is_email_verified:
            raise HTTPException(
                status_code=409,
                detail=(
                    "An unverified account already exists for this email. "
                    "Verify it by email first, then link Google from settings."
                ),
            )
        user.google_sub = google_sub
        user.touch()
        await user.save()

    await ensure_profile(user)
    await _provision_subscription(user)
    return user
