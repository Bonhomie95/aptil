"""Shared FastAPI dependencies: current user resolution.

Multi-tenancy: MongoDB has no RLS. Every tenant-scoped query filters by the current
user's `tenant_id` (`user.tenant_id`) in the route/service layer.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.security import decode_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/token", auto_error=False
)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(token: str | None = Depends(oauth2_scheme)) -> User:
    if not token:
        raise CREDENTIALS_ERROR
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise CREDENTIALS_ERROR
        subject = payload.get("sub")
        if not subject:
            raise CREDENTIALS_ERROR
        # Parsed inside the guard: a malformed `sub` is a bad token (401),
        # not an unhandled ValueError (500).
        user_id = uuid.UUID(str(subject))
    except HTTPException:
        raise
    except Exception as exc:  # jwt errors, malformed uuid
        raise CREDENTIALS_ERROR from exc

    user = await User.get(user_id)
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR
    # Password resets / "sign out everywhere" bump token_version, retiring every
    # token minted before that point.
    if int(payload.get("ver", 0)) != int(user.token_version):
        raise CREDENTIALS_ERROR
    return user


async def get_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="email_not_verified"
        )
    return user


async def get_onboarded_user(user: User = Depends(get_verified_user)) -> User:
    if not user.onboarding_completed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="onboarding_incomplete"
        )
    return user


async def get_superuser(user: User = Depends(get_current_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required"
        )
    return user
