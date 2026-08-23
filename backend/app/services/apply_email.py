"""Managed apply-email aliases and inbound-mail handling.

Each user gets a unique alias (``u-<12 hex>@APPLY_EMAIL_DOMAIN``). Accounts we
create on job sites use it, so registration needs neither the user's password
nor access to their inbox — and everything the site or employer sends
(verification links, confirmations, interview invites, rejections) arrives
where we can act on it and show it on the dashboard.

Inbound path: Cloudflare Email Routing catch-all -> Worker (infra/email/) ->
``POST /api/v1/inbound/email`` with an HMAC signature over the raw body.

Safety properties, in order of importance:
- The webhook is authenticated (constant-time HMAC check) — otherwise anyone
  could inject "verification" links we would then open.
- Verification links are only ever followed when their registrable domain
  matches a credential we are actually waiting to verify for that user.
- HTML is never stored or rendered; the worker sends stripped text.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid as uuid_mod

from app.core.config import settings
from app.core.logging import get_logger
from app.models.profile import InboundEmail, SiteCredential
from app.models.user import User

log = get_logger(__name__)

_ALIAS_RE = re.compile(r"^u-[0-9a-f]{12}@", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Substrings that mark a link as the account-verification click-through.
_VERIFY_HINTS = ("verify", "confirm", "activate", "validation", "email_confirmation")

_KIND_HINTS = (
    ("verification", ("verify your email", "confirm your email", "activate your account",
                      "confirm your account", "email verification")),
    ("interview", ("interview", "schedule a call", "availability", "phone screen")),
    ("rejection", ("unfortunately", "not moving forward", "other candidates",
                   "decided not to", "will not be progressing")),
    ("confirmation", ("application received", "thank you for applying",
                      "we received your application", "application submitted",
                      "thanks for applying")),
)


def aliases_enabled() -> bool:
    return bool(settings.APPLY_EMAIL_DOMAIN.strip() and settings.INBOUND_EMAIL_SECRET.strip())


def new_alias() -> str:
    return f"u-{secrets.token_hex(6)}@{settings.APPLY_EMAIL_DOMAIN.strip().lower()}"


async def ensure_alias(user: User) -> str | None:
    """The user's managed alias, creating it on first use."""
    if user.apply_email_alias:
        return user.apply_email_alias
    if not aliases_enabled():
        return None
    user.apply_email_alias = new_alias()
    user.touch()
    await user.save()
    return user.apply_email_alias


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Constant-time HMAC-SHA256 check of the webhook body."""
    secret = settings.INBOUND_EMAIL_SECRET.strip()
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def registrable_domain(host_or_email: str) -> str:
    """Cheap eTLD+1: last two labels (three for known two-part suffixes).

    Enough for matching a sender/link to a stored site_domain; NOT a general
    public-suffix implementation.
    """
    value = host_or_email.strip().lower()
    # Drop a URL scheme so "https://app.greenhouse.io/..." resolves to the host,
    # not "https:". Without this a raw link's "domain" is the scheme and the
    # same-domain verification gate compares the wrong thing.
    if "://" in value:
        value = value.split("://", 1)[1]
    host = value.rsplit("@", 1)[-1].rstrip(".")
    host = host.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    labels = [part for part in host.split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    two_part = {"co.uk", "org.uk", "ac.uk", "com.au", "co.jp", "co.in", "com.br"}
    tail2 = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if tail2 in two_part else tail2


def classify(subject: str, body: str) -> str:
    haystack = f"{subject}\n{body}".lower()
    for kind, hints in _KIND_HINTS:
        if any(h in haystack for h in hints):
            return kind
    return "other"


def extract_verification_url(body: str, sender_domain: str) -> str | None:
    """The verification click-through, if the mail carries one WE may follow.

    Same registrable domain as the sender only: a link to anywhere else in a
    message we did not ask for is exactly the thing an attacker would plant.
    """
    for url in _URL_RE.findall(body or ""):
        try:
            host = url.split("://", 1)[1]
        except IndexError:
            continue
        if registrable_domain(host) != sender_domain:
            continue
        if any(h in url.lower() for h in _VERIFY_HINTS):
            return url.rstrip(").,>]'\"")
    return None


async def ingest(payload: dict) -> InboundEmail | None:
    """Store one inbound message and kick off verification when relevant."""
    to_addr = str(payload.get("to") or "").strip().lower()
    if not _ALIAS_RE.match(to_addr):
        log.info("inbound_email_unroutable", to=to_addr[:60])
        return None
    user = await User.find_one(User.apply_email_alias == to_addr)
    if user is None:
        log.info("inbound_email_unknown_alias", to=to_addr[:60])
        return None

    from_address = str(payload.get("from") or "").strip()[:320]
    subject = str(payload.get("subject") or "").strip()[:500]
    body = str(payload.get("text") or "")[:50_000]
    sender_domain = registrable_domain(from_address)
    kind = classify(subject, body)
    verification_url = (
        extract_verification_url(body, sender_domain)
        if kind == "verification"
        else None
    )

    row = InboundEmail(
        user_id=user.id,
        tenant_id=user.tenant_id,
        alias=to_addr,
        from_address=from_address,
        subject=subject,
        body_text=body,
        kind=kind,
        sender_domain=sender_domain,
        verification_url=verification_url,
    )
    await row.insert()

    if verification_url:
        pending = await SiteCredential.find_one(
            SiteCredential.user_id == user.id,
            SiteCredential.status == "pending_verification",
            SiteCredential.site_domain == sender_domain,
        )
        if pending is not None:
            try:
                from app.workers.tasks.apply import verify_managed_account

                verify_managed_account.delay(str(row.id), str(pending.id))
            except Exception as exc:  # noqa: BLE001 - broker down
                log.warning("verification_enqueue_failed", error=str(exc))
        else:
            log.info("verification_mail_without_pending_credential",
                     domain=sender_domain)
    return row


async def create_managed_credential(
    user: User, site_domain: str
) -> tuple[SiteCredential, str] | None:
    """A fresh managed account credential for ``site_domain``.

    Returns (credential row, plaintext password) — the caller types the password
    into the signup form and must not persist it anywhere else. None when the
    user has no alias (feature unconfigured) or already has a credential there.
    """
    from app.core.security import encrypt_secret

    alias = await ensure_alias(user)
    if alias is None:
        return None
    domain = registrable_domain(site_domain)
    existing = await SiteCredential.find_one(
        SiteCredential.user_id == user.id,
        SiteCredential.site_domain == domain,
    )
    if existing is not None:
        return None
    password = secrets.token_urlsafe(24)
    row = SiteCredential(
        user_id=user.id,
        tenant_id=user.tenant_id,
        site_domain=domain,
        login_email=alias,
        encrypted_password=encrypt_secret(password),
        managed=True,
        status="pending_verification",
    )
    await row.insert()
    return row, password


_UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


def looks_like_id(value: str) -> bool:
    try:
        uuid_mod.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
