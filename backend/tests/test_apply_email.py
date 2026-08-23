"""Managed apply-email: alias mail handling and its safety gates.

The dangerous capability here is "follow a link that arrived by email and open
it in a browser". Every test below pins a gate that keeps that from being
abusable: HMAC on the webhook, and same-registrable-domain matching before any
verification link is ever visited.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.services import apply_email as ae


# --- registrable domain ---------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        ("no-reply@mail.greenhouse.io", "greenhouse.io"),
        ("careers@boards.greenhouse.io", "greenhouse.io"),
        ("x@acme.co.uk", "acme.co.uk"),
        ("https://app.greenhouse.io/confirm?t=1", "greenhouse.io"),
        ("greenhouse.io", "greenhouse.io"),
    ],
)
def test_registrable_domain(value, expected):
    assert ae.registrable_domain(value) == expected


# --- the verification-link gate (the important one) -----------------------
def test_verification_url_must_share_the_sender_domain():
    """A link to anywhere other than the sender's own domain is ignored — that
    is exactly what a planted link in unsolicited mail would look like."""
    body = "Confirm here https://app.greenhouse.io/users/confirm?tok=abc thanks"
    assert (
        ae.extract_verification_url(body, "greenhouse.io")
        == "https://app.greenhouse.io/users/confirm?tok=abc"
    )
    evil = "Confirm here https://evil.example.com/verify?tok=abc thanks"
    assert ae.extract_verification_url(evil, "greenhouse.io") is None


def test_verification_url_requires_a_verification_shaped_link():
    body = "Welcome! Visit https://app.greenhouse.io/dashboard to start."
    assert ae.extract_verification_url(body, "greenhouse.io") is None


# --- classification -------------------------------------------------------
@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Please verify your email address", "verification"),
        ("You're invited to interview at Acme", "interview"),
        ("Update on your application", "other"),
        ("Thank you for applying to Acme", "confirmation"),
        ("Unfortunately we are moving forward with other candidates", "rejection"),
    ],
)
def test_classify(subject, expected):
    assert ae.classify(subject, "") == expected


# --- webhook signature ----------------------------------------------------
def test_signature_roundtrip(monkeypatch):
    monkeypatch.setattr(ae.settings, "INBOUND_EMAIL_SECRET", "s3cret")
    body = b'{"to":"u-abc@apply.example.com"}'
    good = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert ae.verify_signature(body, good) is True
    assert ae.verify_signature(body, "deadbeef") is False
    assert ae.verify_signature(body, None) is False


def test_signature_fails_closed_without_a_secret(monkeypatch):
    monkeypatch.setattr(ae.settings, "INBOUND_EMAIL_SECRET", "")
    body = b"{}"
    # With no configured secret, NOTHING verifies — never accept-all.
    assert ae.verify_signature(body, "anything") is False


def test_alias_shape(monkeypatch):
    monkeypatch.setattr(ae.settings, "APPLY_EMAIL_DOMAIN", "apply.example.com")
    monkeypatch.setattr(ae.settings, "INBOUND_EMAIL_SECRET", "x")
    alias = ae.new_alias()
    assert ae._ALIAS_RE.match(alias)
    assert alias.endswith("@apply.example.com")
    assert ae.aliases_enabled() is True
