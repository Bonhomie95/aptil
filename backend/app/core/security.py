"""Password hashing, JWT tokens, and at-rest credential encryption.

Design notes:
- Passwords: Argon2id via passlib.
- Session tokens: short-lived access JWT + longer refresh JWT. Both carry a
  ``jti`` (so a refresh token can be revoked individually) and a ``ver`` claim
  mirroring ``User.token_version`` (so a password reset invalidates every token
  already issued to that account).
- Site credentials (for consent-based ATS autofill) are NEVER stored in plaintext.
  They use envelope encryption: a random per-secret data key encrypts the
  password, and CREDENTIAL_ENCRYPTION_KEY encrypts that data key. Rotating the
  outer key then re-wraps 32 bytes per row instead of re-encrypting the whole
  table. A password is generated per site; we never reuse one across sites.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

ALGORITHM = "HS256"

# Precomputed hash of an unguessable value. Verified against when an account does
# not exist so that "unknown email" and "wrong password" cost the same time and
# the endpoint cannot be used to enumerate accounts.
_DUMMY_HASH = pwd_context.hash("aptil-nonexistent-account-timing-equalizer")


# --- Passwords ---
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Verify a password. Always performs a hash comparison, even for a missing
    hash, so callers cannot distinguish "no such user" by response time."""
    if not hashed:
        pwd_context.verify(plain, _DUMMY_HASH)
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:  # noqa: BLE001 - malformed stored hash is a failed login
        return False


def generate_site_password(length: int = 20) -> str:
    """Generate a unique, strong password for a single third-party site."""
    return secrets.token_urlsafe(length)


# --- JWT ---
def _create_token(
    subject: str,
    expires: timedelta,
    token_type: str,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(encoded_jwt, jti)``."""
    now = datetime.now(UTC)
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "jti": jti,
        "iat": now,
        "exp": now + expires,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM), jti


def create_2fa_challenge(user_id: str) -> str:
    """A short-lived token proving 'password step passed, 2FA pending'.

    Deliberately NOT an access token: it carries a distinct type claim and a
    tight expiry, so it can only be exchanged at the 2FA-verify endpoint and
    never used as a bearer credential.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "type": "2fa_challenge",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_2fa_challenge(token: str) -> str:
    """Return the user id from a valid 2FA challenge token, else raise."""
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    if claims.get("type") != "2fa_challenge":
        raise ValueError("not a 2fa challenge token")
    return str(claims["sub"])


def create_access_token(
    subject: str, tenant_id: str | None = None, token_version: int = 0
) -> str:
    extra: dict[str, Any] = {"ver": token_version}
    if tenant_id:
        extra["tenant_id"] = tenant_id
    token, _jti = _create_token(
        subject,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
        extra,
    )
    return token


def create_refresh_token(subject: str, token_version: int = 0) -> tuple[str, str, datetime]:
    """Return ``(token, jti, expires_at)`` so the caller can persist the session."""
    expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    token, jti = _create_token(subject, expires, "refresh", {"ver": token_version})
    return token, jti, datetime.now(UTC) + expires


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def create_url_safe_token(nbytes: int = 32) -> str:
    """Opaque token for email verification / password reset links."""
    return secrets.token_urlsafe(nbytes)


def hash_lookup_token(token: str) -> str:
    """Hash a link token for storage.

    Verification / reset links are bearer secrets. Storing only their SHA-256
    means a database leak does not hand out working links. Lookup stays a single
    indexed equality query.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time comparison for opaque tokens."""
    return hmac.compare_digest(a, b)


# --- Credential encryption (envelope) -------------------------------------
#
# Site passwords are wrapped twice:
#
#     plaintext --Fernet(DEK)--> ciphertext        (DEK is random, per secret)
#     DEK       --Fernet(KEK)--> wrapped DEK       (KEK is the env-var key)
#
# stored as  v2.<kek_id>.<wrapped DEK>.<ciphertext>
#
# Why bother, when a single key would also encrypt the data? Because rotation
# is otherwise a whole-table re-encryption: every secret has to be decrypted
# and re-encrypted under the new key, which means holding every plaintext in
# memory during the migration. With an envelope, rotating the KEK only re-wraps
# a 32-byte DEK per row — the ciphertext is never touched and no plaintext is
# ever materialised. Compromise of one DEK also exposes exactly one secret.
#
# `kek_id` is a fingerprint of the key that wrapped the DEK, so rotation can
# tell finished rows from stragglers without trial decryption.
#
# v1 (a bare Fernet token under the KEK) is still accepted on read: rows written
# before this existed must keep working, and `rewrap_secret` upgrades them.

_ENVELOPE_PREFIX = "v2"
_FIELD_SEP = "."  # Fernet tokens are urlsafe-base64, so a dot cannot collide.


def _normalise_key(raw: str | bytes) -> bytes:
    """Coerce a configured key into 32 urlsafe-base64 bytes Fernet accepts."""
    material = raw.encode() if isinstance(raw, str) else raw
    try:
        Fernet(material)
        return material
    except (ValueError, TypeError):
        # Not already a Fernet key: derive one from the raw secret.
        return base64.urlsafe_b64encode(material[:32].ljust(32, b"0"))


def _kek_id(key: bytes) -> str:
    """Short, stable fingerprint of a KEK. Not secret — it identifies, not proves."""
    return hashlib.sha256(key).hexdigest()[:8]


def _primary_kek() -> bytes:
    key = settings.CREDENTIAL_ENCRYPTION_KEY
    if not key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is not set")
    return _normalise_key(key)


def _all_keks() -> list[bytes]:
    """Primary first, then retired keys. Retired keys are never used to write."""
    keys = [_primary_kek()]
    for retired in settings.retired_credential_keys:
        candidate = _normalise_key(retired)
        if candidate not in keys:
            keys.append(candidate)
    return keys


def current_kek_id() -> str:
    """Fingerprint of the key new secrets are being written under."""
    return _kek_id(_primary_kek())


def encrypt_secret(plaintext: str) -> str:
    """Envelope-encrypt a secret under the current KEK."""
    kek = _primary_kek()
    dek = Fernet.generate_key()
    wrapped = Fernet(kek).encrypt(dek).decode()
    ciphertext = Fernet(dek).encrypt(plaintext.encode()).decode()
    return _FIELD_SEP.join([_ENVELOPE_PREFIX, _kek_id(kek), wrapped, ciphertext])


def _decrypt_envelope(parts: list[str]) -> str:
    _, kek_id, wrapped, ciphertext = parts
    keks = _all_keks()
    # Try the key the record names first; fall back to every configured key so a
    # fingerprint collision or a mislabelled row still opens.
    ordered = [k for k in keks if _kek_id(k) == kek_id] + [
        k for k in keks if _kek_id(k) != kek_id
    ]
    for kek in ordered:
        try:
            dek = Fernet(kek).decrypt(wrapped.encode())
        except InvalidToken:
            continue
        return Fernet(dek).decrypt(ciphertext.encode()).decode()
    raise InvalidToken("no configured key could unwrap this credential")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a secret written by any version, under any configured key."""
    parts = ciphertext.split(_FIELD_SEP)
    if len(parts) == 4 and parts[0] == _ENVELOPE_PREFIX:
        return _decrypt_envelope(parts)
    # v1: a bare Fernet token encrypted directly under a KEK.
    return MultiFernet([Fernet(k) for k in _all_keks()]).decrypt(
        ciphertext.encode()
    ).decode()


def needs_rewrap(ciphertext: str) -> bool:
    """True if this record is not already wrapped under the current KEK."""
    parts = ciphertext.split(_FIELD_SEP)
    if len(parts) != 4 or parts[0] != _ENVELOPE_PREFIX:
        return True  # v1
    return parts[1] != current_kek_id()


def rewrap_secret(ciphertext: str) -> str:
    """Move a record onto the current KEK.

    For an envelope this only re-wraps the DEK — the encrypted payload is
    copied verbatim and the plaintext is never decrypted. A v1 record has no
    DEK to re-wrap, so it is decrypted once and re-encrypted as an envelope.
    """
    parts = ciphertext.split(_FIELD_SEP)
    if len(parts) == 4 and parts[0] == _ENVELOPE_PREFIX:
        _, kek_id, wrapped, payload = parts
        keks = _all_keks()
        ordered = [k for k in keks if _kek_id(k) == kek_id] + [
            k for k in keks if _kek_id(k) != kek_id
        ]
        for kek in ordered:
            try:
                dek = Fernet(kek).decrypt(wrapped.encode())
            except InvalidToken:
                continue
            primary = _primary_kek()
            rewrapped = Fernet(primary).encrypt(dek).decode()
            return _FIELD_SEP.join(
                [_ENVELOPE_PREFIX, _kek_id(primary), rewrapped, payload]
            )
        raise InvalidToken("no configured key could unwrap this credential")
    return encrypt_secret(decrypt_secret(ciphertext))
