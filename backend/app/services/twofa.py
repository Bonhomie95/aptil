"""Two-factor authentication (TOTP) — enrolment, verification, backup codes.

The TOTP secret is envelope-encrypted at rest with the same mechanism as site
credentials (core.security.encrypt_secret). Backup codes are stored only as
Argon2 hashes and consumed on use, so a database read never yields a usable
second factor.
"""

from __future__ import annotations

import secrets

import pyotp

from app.core.config import settings
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_password,
    verify_password,
)
from app.models.user import User

ISSUER = "Aptil"
_N_BACKUP_CODES = 8


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account: str) -> str:
    """otpauth:// URI the user's authenticator app scans (as a QR)."""
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=ISSUER)


def code_valid(secret: str, code: str) -> bool:
    """True if ``code`` is valid now (±1 step, for small clock drift)."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_backup_codes() -> tuple[list[str], list[str]]:
    """Return (plaintext codes to show ONCE, their hashes to store)."""
    plain = [f"{secrets.randbelow(10**8):08d}" for _ in range(_N_BACKUP_CODES)]
    return plain, [hash_password(c) for c in plain]


async def begin_setup(user: User) -> tuple[str, str]:
    """Create a pending secret and return (secret, provisioning_uri).

    Not enabled yet — the user must verify a code first (enable_2fa).
    """
    secret = new_secret()
    user.totp_secret_enc = encrypt_secret(secret)
    user.touch()
    await user.save()
    return secret, provisioning_uri(secret, user.email)


async def enable(user: User, code: str) -> list[str]:
    """Verify a code against the pending secret and switch 2FA on.

    Returns fresh backup codes (shown once). Raises ValueError on a bad code.
    """
    if not user.totp_secret_enc:
        raise ValueError("no_setup_in_progress")
    secret = decrypt_secret(user.totp_secret_enc)
    if not code_valid(secret, code):
        raise ValueError("invalid_code")
    plain, hashes = generate_backup_codes()
    user.two_factor_enabled = True
    user.backup_codes = hashes
    user.touch()
    await user.save()
    return plain


async def verify_login(user: User, code: str) -> bool:
    """Second-factor check at login: a TOTP code OR a one-time backup code."""
    if not (user.two_factor_enabled and user.totp_secret_enc):
        return True  # 2FA not on -> nothing to check
    secret = decrypt_secret(user.totp_secret_enc)
    if code_valid(secret, code):
        return True
    # Fall back to a backup code, consuming it on success.
    for i, h in enumerate(user.backup_codes):
        if verify_password((code or "").strip(), h):
            user.backup_codes.pop(i)
            user.touch()
            await user.save()
            return True
    return False


async def disable(user: User) -> None:
    user.two_factor_enabled = False
    user.totp_secret_enc = None
    user.backup_codes = []
    user.touch()
    await user.save()


# settings referenced only to keep import parity with other services
_ = settings
