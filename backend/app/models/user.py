"""User accounts, authentication, email verification, and refresh sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.db.base import TimestampedDocument
from app.models.enums import AutomationState


class User(TimestampedDocument):
    tenant_id: uuid.UUID

    # Always stored lower-cased; see auth_service.normalize_email.
    email: str
    full_name: str | None = None
    # None for OAuth-only accounts (no local password).
    hashed_password: str | None = None

    is_email_verified: bool = False
    is_active: bool = True
    is_superuser: bool = False

    google_sub: str | None = None

    # Whether the engine may source, match and apply for this user. Defaults to
    # running so finishing onboarding starts the search, but the user can pause
    # or stop it at any time — see enums.AutomationState.
    automation_state: str = AutomationState.RUNNING.value
    automation_changed_at: datetime | None = None

    # Managed per-user address (u-<id>@APPLY_EMAIL_DOMAIN). Job-site accounts we
    # create use it, so registration needs no password or inbox access from the
    # user, and employer replies land where the dashboard can show them.
    # Whether matched jobs are submitted automatically in the background, or
    # wait for the user to apply them in batches from the dashboard. Defaults to
    # OFF (review-first): unattended ATS apply frequently hits CAPTCHAs/login
    # walls and gets discarded, which would leave the dashboard empty. With this
    # off, matches persist as "pending" for the user to review and apply, and
    # only a real submission (or a user-triggered apply) ever changes them.
    auto_apply: bool = False
    apply_email_alias: str | None = None
    # Consent flag for creating job-site accounts on the user's behalf with the
    # managed alias. Defaulted from AUTO_CREATE_ACCOUNTS_DEFAULT at signup and
    # editable in Settings.
    auto_create_accounts: bool = True

    # Where confirmations are delivered; defaults to `email` when unset.
    notification_email: str | None = None

    # Bumped whenever every previously issued token must stop working
    # (password reset, "sign out everywhere", account disable). Mirrored into
    # the JWT `ver` claim and checked on every authenticated request.
    token_version: int = 0

    # --- Two-factor auth (TOTP) ---
    # Encrypted TOTP secret (envelope-encrypted like site credentials). Present
    # once setup starts; two_factor_enabled flips true only after a code is
    # verified, so a half-finished setup never locks anyone out.
    totp_secret_enc: str | None = None
    two_factor_enabled: bool = False
    # Argon2 hashes of one-time backup codes (single use; removed as consumed).
    backup_codes: list[str] = Field(default_factory=list)

    # Email-verification resend throttling. Cooldown doubles each resend:
    # 30s, 60s, 120s, ... capped at MAX_COOLDOWN_SECONDS.
    verification_sent_at: datetime | None = None
    verification_resend_count: int = 0
    password_reset_sent_at: datetime | None = None

    # Consent record (compliance §5: signed Terms/Privacy at signup).
    accepted_terms_at: datetime | None = None

    onboarding_step: str = "cv_upload"
    onboarding_completed: bool = False

    @property
    def has_password(self) -> bool:
        """Whether a local password exists at all.

        Google-only accounts have none, and every flow that asks the user to
        confirm one has to branch on this or it asks for something that cannot
        be given.
        """
        return bool(self.hashed_password)

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("email", ASCENDING)], unique=True),
            IndexModel([("tenant_id", ASCENDING)]),
            IndexModel([("google_sub", ASCENDING)]),
        ]


class EmailVerificationToken(TimestampedDocument):
    """A single-use link token for email verification or password reset.

    Only the SHA-256 of the token is stored, so a database leak does not yield
    usable links.
    """

    user_id: uuid.UUID
    token_hash: str
    purpose: str = "verify_email"  # or password_reset
    expires_at: datetime
    used_at: datetime | None = None

    class Settings:
        name = "email_verification_tokens"
        indexes = [
            IndexModel([("token_hash", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING), ("purpose", ASCENDING)]),
            # Let MongoDB reap expired rows on its own.
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=86400),
        ]


class RefreshSession(TimestampedDocument):
    """One issued refresh token. Enables rotation, logout, and reuse detection."""

    user_id: uuid.UUID
    jti: str
    expires_at: datetime
    revoked_at: datetime | None = None
    # Set when this token was rotated into a successor, for reuse detection.
    replaced_by: str | None = None

    class Settings:
        name = "refresh_sessions"
        indexes = [
            IndexModel([("jti", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=604800),
        ]
