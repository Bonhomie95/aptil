"""Authentication business logic: registration, verification, login, reset."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from math import ceil

from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_url_safe_token,
    hash_lookup_token,
    hash_password,
    verify_password,
)
from app.models.profile import Profile
from app.models.tenant import Tenant
from app.models.user import EmailVerificationToken, RefreshSession, User
from app.services.email import send_password_reset_email, send_verification_email

log = get_logger(__name__)

BASE_COOLDOWN_SECONDS = 30
# Without a ceiling the doubling reaches hours after a handful of clicks and
# locks a legitimate user out of their own signup.
MAX_COOLDOWN_SECONDS = 30 * 60
VERIFICATION_TTL_HOURS = 24
PASSWORD_RESET_TTL_MINUTES = 60
MIN_PASSWORD_LENGTH = 8


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def cooldown_for(resend_count: int) -> int:
    """30s doubling per resend, capped at MAX_COOLDOWN_SECONDS."""
    # Cap the exponent first so a large stored count cannot overflow into a
    # gigantic intermediate integer.
    exponent = min(resend_count, 16)
    return min(BASE_COOLDOWN_SECONDS * (2**exponent), MAX_COOLDOWN_SECONDS)


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    if len(password) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at most 128 characters",
        )


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
async def register_user(
    email: str, password: str, full_name: str | None, accepted_terms: bool = True
) -> User:
    """Create tenant + user + profile, then send the verification email.

    The unique index on ``users.email`` is the real guard against a concurrent
    duplicate signup; the pre-check just gives a nicer error in the common case.
    """
    email = normalize_email(email)
    validate_password(password)
    if not accepted_terms:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="You must accept the Terms and Privacy Policy to create an account",
        )

    existing = await User.find_one(User.email == email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    full_name = (full_name or "").strip() or None
    tenant = Tenant(name=full_name or email.split("@")[0])
    await tenant.insert()

    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        verification_sent_at=datetime.now(UTC),
        accepted_terms_at=datetime.now(UTC),
        auto_create_accounts=settings.AUTO_CREATE_ACCOUNTS_DEFAULT,
    )
    try:
        await user.insert()
    except DuplicateKeyError as exc:
        # Lost the race against a concurrent signup — clean up the tenant we
        # created so it does not linger unreferenced.
        await tenant.delete()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc
    except Exception:
        await tenant.delete()
        raise

    # Create the profile up front: the CV-parsing worker fills it in and would
    # otherwise race the request and silently drop everything it parsed.
    await ensure_profile(user)
    # Provision the free plan so entitlement checks have real quota to read and
    # "start without a credit card" is actually true.
    await _provision_subscription(user)

    await _issue_verification(user)
    return user


async def _provision_subscription(user: User) -> None:
    from app.services import billing

    try:
        await billing.ensure_subscription(user.tenant_id)
    except Exception as exc:  # noqa: BLE001 - signup must not fail on billing
        log.warning("subscription_provision_failed", user_id=str(user.id), error=str(exc))


async def ensure_profile(user: User) -> Profile:
    """Get-or-create the user's profile, tolerating a concurrent creator."""
    profile = await Profile.find_one(Profile.user_id == user.id)
    if profile is not None:
        return profile
    first_name = (
        (user.full_name or "").split(" ")[0] or None if user.full_name else None
    )
    last_name = (
        " ".join((user.full_name or "").split(" ")[1:]) or None
        if user.full_name and " " in user.full_name
        else None
    )
    profile = Profile(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        first_name=first_name,
        last_name=last_name,
        # These are our guesses from the signup form, not the user's own answers
        # to these questions. Marking them lets a CV parse refine them — the
        # contact email in particular was previously seeded here and could then
        # never be replaced, so a CV's address was extracted and thrown away.
        autofilled_fields=[
            name
            for name, value in (
                ("email", user.email),
                ("first_name", first_name),
                ("last_name", last_name),
            )
            if value
        ],
    )
    try:
        await profile.insert()
    except DuplicateKeyError:
        existing = await Profile.find_one(Profile.user_id == user.id)
        if existing is None:  # pragma: no cover - defensive
            raise
        return existing
    return profile


# --------------------------------------------------------------------------- #
# Email verification
# --------------------------------------------------------------------------- #
async def _issue_verification(user: User) -> None:
    token = create_url_safe_token()
    # Retire any outstanding verification links so only the newest one works.
    await EmailVerificationToken.find(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.purpose == "verify_email",
        EmailVerificationToken.used_at == None,  # noqa: E711
    ).set({"used_at": datetime.now(UTC)})

    verification = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_lookup_token(token),
        purpose="verify_email",
        expires_at=datetime.now(UTC) + timedelta(hours=VERIFICATION_TTL_HOURS),
    )
    await verification.insert()
    await send_verification_email(user.email, token)


async def _consume_token(raw_token: str, purpose: str) -> User:
    row = await EmailVerificationToken.find_one(
        EmailVerificationToken.token_hash == hash_lookup_token(raw_token),
        EmailVerificationToken.purpose == purpose,
    )
    if not row or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or used token")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Token expired")

    user = await User.get(row.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or used token")

    row.used_at = datetime.now(UTC)
    row.touch()
    await row.save()
    return user


async def verify_email(token: str) -> User:
    user = await _consume_token(token, "verify_email")
    if not user.is_email_verified:
        user.is_email_verified = True
        user.touch()
        await user.save()
    return user


async def resend_verification(email: str) -> dict:
    """Resend the verification email under a doubling (capped) cooldown.

    Returns ``{"sent": bool, "next_cooldown_seconds": int}``. Neutral for unknown or
    already-verified emails (no send) so the endpoint doesn't leak account state.
    """
    user = await User.find_one(User.email == normalize_email(email))
    if not user or user.is_email_verified or not user.is_active:
        return {"sent": False, "next_cooldown_seconds": BASE_COOLDOWN_SECONDS}

    now = datetime.now(UTC)
    required = cooldown_for(user.verification_resend_count)
    last = user.verification_sent_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        elapsed = (now - last).total_seconds()
        if elapsed < required:
            return {"sent": False, "next_cooldown_seconds": ceil(required - elapsed)}

    await _issue_verification(user)
    user.verification_resend_count += 1
    user.verification_sent_at = now
    user.touch()
    await user.save()
    return {
        "sent": True,
        "next_cooldown_seconds": cooldown_for(user.verification_resend_count),
    }


# --------------------------------------------------------------------------- #
# Password reset
# --------------------------------------------------------------------------- #
async def request_password_reset(email: str) -> dict:
    """Email a reset link. Always reports the same result (no account probing)."""
    user = await User.find_one(User.email == normalize_email(email))
    neutral = {"sent": True, "next_cooldown_seconds": BASE_COOLDOWN_SECONDS}
    if not user or not user.is_active:
        return neutral

    now = datetime.now(UTC)
    last = user.password_reset_sent_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if (now - last).total_seconds() < BASE_COOLDOWN_SECONDS:
            return neutral

    token = create_url_safe_token()
    await EmailVerificationToken.find(
        EmailVerificationToken.user_id == user.id,
        EmailVerificationToken.purpose == "password_reset",
        EmailVerificationToken.used_at == None,  # noqa: E711
    ).set({"used_at": now})
    await EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_lookup_token(token),
        purpose="password_reset",
        expires_at=now + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES),
    ).insert()

    user.password_reset_sent_at = now
    user.touch()
    await user.save()
    await send_password_reset_email(user.email, token)
    return neutral


async def reset_password(token: str, new_password: str) -> User:
    validate_password(new_password)
    user = await _consume_token(token, "password_reset")

    user.hashed_password = hash_password(new_password)
    # Retire every token issued before the reset — the whole point of a reset is
    # that whoever held the old credentials loses access.
    user.token_version += 1
    if not user.is_email_verified:
        # Proving control of the inbox is exactly what verification asks for.
        user.is_email_verified = True
    user.touch()
    await user.save()
    await revoke_all_sessions(user.id)
    log.info("password_reset", user_id=str(user.id))
    return user


# --------------------------------------------------------------------------- #
# Login / sessions
# --------------------------------------------------------------------------- #
async def authenticate(email: str, password: str) -> User:
    user = await User.find_one(User.email == normalize_email(email))
    # verify_password hashes even when the user is missing, so a bad email and a
    # bad password take the same time and cannot be told apart.
    if not verify_password(password, user.hashed_password if user else None):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    assert user is not None  # narrowed by the check above
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    if not user.is_email_verified:
        # Distinct code the frontend keys on to show the "verify your email" screen.
        raise HTTPException(status_code=403, detail="email_not_verified")
    return user


async def issue_tokens(user: User) -> dict:
    """Mint an access + refresh pair and record the refresh session."""
    access = create_access_token(str(user.id), str(user.tenant_id), user.token_version)
    refresh, jti, expires_at = create_refresh_token(str(user.id), user.token_version)
    await RefreshSession(user_id=user.id, jti=jti, expires_at=expires_at).insert()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


async def rotate_refresh_token(raw_token: str) -> dict:
    """Validate a refresh token, revoke it, and issue a fresh pair.

    Presenting an already-rotated token is treated as theft: every session for
    that user is revoked.
    """
    from app.core.security import decode_token

    invalid = HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        claims = decode_token(raw_token)
    except Exception as exc:
        raise invalid from exc
    if claims.get("type") != "refresh":
        raise invalid
    jti = claims.get("jti")
    subject = claims.get("sub")
    if not jti or not subject:
        raise invalid
    try:
        user_id = uuid.UUID(str(subject))
    except ValueError as exc:
        raise invalid from exc

    session = await RefreshSession.find_one(RefreshSession.jti == jti)
    if session is None:
        raise invalid
    if session.revoked_at is not None:
        # Reuse of a rotated token: assume the token was stolen and cut off all
        # sessions for the account.
        log.warning("refresh_token_reuse_detected", user_id=str(user_id))
        await revoke_all_sessions(user_id)
        raise invalid

    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise invalid

    user = await User.get(user_id)
    if user is None or not user.is_active:
        raise invalid
    if int(claims.get("ver", 0)) != int(user.token_version):
        raise invalid

    tokens = await issue_tokens(user)
    session.revoked_at = datetime.now(UTC)
    session.touch()
    await session.save()
    return tokens


async def revoke_session(raw_token: str) -> None:
    """Best-effort logout: revoke the presented refresh token if it is ours."""
    from app.core.security import decode_token

    try:
        claims = decode_token(raw_token)
    except Exception:  # noqa: BLE001 - logout must never fail loudly
        return
    jti = claims.get("jti")
    if not jti:
        return
    session = await RefreshSession.find_one(RefreshSession.jti == jti)
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        session.touch()
        await session.save()


async def revoke_all_sessions(user_id: uuid.UUID) -> None:
    await RefreshSession.find(
        RefreshSession.user_id == user_id,
        RefreshSession.revoked_at == None,  # noqa: E711
    ).set({"revoked_at": datetime.now(UTC)})
