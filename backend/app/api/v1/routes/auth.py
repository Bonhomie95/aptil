"""Auth endpoints: register, verify, login, refresh, reset, me, Google OAuth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResendVerificationResponse,
    ResetPasswordRequest,
    TokenResponse,
    TwoFactorCodeRequest,
    TwoFactorVerifyRequest,
    UserRead,
    VerifyEmailRequest,
)
from app.services import auth_service

router = APIRouter()
log = get_logger(__name__)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=201,
    dependencies=[Depends(RateLimiter(times=5, seconds=300))],
)
async def register(payload: RegisterRequest):
    return await auth_service.register_user(
        payload.email, payload.password, payload.full_name, payload.accepted_terms
    )


@router.post(
    "/verify-email",
    response_model=UserRead,
    dependencies=[Depends(RateLimiter(times=20, seconds=300))],
)
async def verify_email(payload: VerifyEmailRequest):
    return await auth_service.verify_email(payload.token)


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=60))],
)
async def resend_verification(payload: ResendVerificationRequest):
    """Resend the verification email under a per-account doubling cooldown."""
    return await auth_service.resend_verification(payload.email)


@router.post(
    "/login",
    # No response_model: login returns EITHER a token pair OR a 2FA challenge.
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
)
async def login(payload: LoginRequest):
    user = await auth_service.authenticate(payload.email, payload.password)
    if user.two_factor_enabled:
        from app.core.security import create_2fa_challenge

        # Password step passed; withhold tokens until the second factor.
        return {"two_factor_required": True, "challenge": create_2fa_challenge(str(user.id))}
    return await auth_service.issue_tokens(user)


@router.post(
    "/token",
    response_model=TokenResponse,
    include_in_schema=False,
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
)
async def login_form(form: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password flow (for Swagger's Authorize button)."""
    user = await auth_service.authenticate(form.username, form.password)
    return await auth_service.issue_tokens(user)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(times=30, seconds=60))],
)
async def refresh(payload: RefreshRequest):
    """Exchange a refresh token for a new pair. The old token is revoked."""
    return await auth_service.rotate_refresh_token(payload.refresh_token)


@router.post("/logout", status_code=204)
async def logout(payload: LogoutRequest, user: User = Depends(get_current_user)):
    """Revoke the presented refresh token, or every session for the account."""
    if payload.all_devices:
        await auth_service.revoke_all_sessions(user.id)
    elif payload.refresh_token:
        await auth_service.revoke_session(payload.refresh_token)
    return None


@router.post(
    "/forgot-password",
    response_model=ResendVerificationResponse,
    dependencies=[Depends(RateLimiter(times=5, seconds=300))],
)
async def forgot_password(payload: ForgotPasswordRequest):
    """Send a reset link. The response is identical for unknown addresses."""
    return await auth_service.request_password_reset(payload.email)


@router.post(
    "/reset-password",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=300))],
)
async def reset_password(payload: ResetPasswordRequest):
    user = await auth_service.reset_password(payload.token, payload.password)
    return await auth_service.issue_tokens(user)


@router.post(
    "/change-password",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=300))],
)
async def change_password(
    payload: ChangePasswordRequest, user: User = Depends(get_current_user)
):
    """Change, or for a Google-only account SET, the local password.

    An account created through Google has no password to confirm, so requiring
    one meant such a user could never set one — Settings showed a form that
    always answered "Current password is incorrect". Where there is nothing to
    confirm, the authenticated session is the proof; the version bump below
    still signs every other device out.
    """
    if user.hashed_password:
        if not payload.current_password or not verify_password(
            payload.current_password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )
    auth_service.validate_password(payload.new_password)
    user.hashed_password = hash_password(payload.new_password)
    user.token_version += 1
    user.touch()
    await user.save()
    await auth_service.revoke_all_sessions(user.id)
    log.info("password_changed", user_id=str(user.id))
    # The bump above invalidated the caller's own token; hand back a fresh pair.
    return await auth_service.issue_tokens(user)


@router.post("/2fa/setup", dependencies=[Depends(RateLimiter(times=10, seconds=300))])
async def two_factor_setup(user: User = Depends(get_current_user)):
    """Begin TOTP enrolment: returns the secret + otpauth URI to show as a QR.
    Not active until /2fa/enable verifies a code."""
    from app.services import twofa

    secret, uri = await twofa.begin_setup(user)
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/2fa/enable", dependencies=[Depends(RateLimiter(times=10, seconds=300))])
async def two_factor_enable(
    payload: TwoFactorCodeRequest, user: User = Depends(get_current_user)
):
    """Verify the first code and switch 2FA on. Returns one-time backup codes."""
    from app.services import twofa

    try:
        backup_codes = await twofa.enable(user, payload.code)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return {"enabled": True, "backup_codes": backup_codes}


@router.post("/2fa/disable", dependencies=[Depends(RateLimiter(times=10, seconds=300))])
async def two_factor_disable(
    payload: TwoFactorCodeRequest, user: User = Depends(get_current_user)
):
    """Turn 2FA off. Requires a current code (or backup code) as proof."""
    from app.services import twofa

    if not await twofa.verify_login(user, payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_code"
        )
    await twofa.disable(user)
    return {"enabled": False}


@router.post(
    "/2fa/verify",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(times=10, seconds=300))],
)
async def two_factor_verify(payload: TwoFactorVerifyRequest):
    """Complete a login: exchange the challenge + a code for tokens."""
    from app.core.security import decode_2fa_challenge
    from app.services import twofa

    try:
        user_id = decode_2fa_challenge(payload.challenge)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="challenge_invalid"
        ) from exc
    import uuid as _uuid

    user = await User.get(_uuid.UUID(user_id))
    if user is None or not user.two_factor_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="challenge_invalid")
    if not await twofa.verify_login(user, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_code")
    return await auth_service.issue_tokens(user)


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_user)):
    return user


# Google OAuth lives in app/api/v1/routes/oauth.py (also mounted under /auth):
#   GET /auth/google/login  -> redirect to Google
#   GET /auth/google/callback -> exchange code, redirect back to the web app
