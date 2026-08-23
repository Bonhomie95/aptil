"""Smoke tests that need no external services."""

from app.workers.tasks.discovery import fingerprint


def test_fingerprint_is_source_agnostic():
    # Same role, different boards/casing/punctuation -> same fingerprint.
    a = fingerprint("Acme Corp", "Senior Backend Engineer", "London, UK")
    b = fingerprint("acme corp", "senior  backend engineer", "london uk")
    assert a == b


def test_fingerprint_distinguishes_roles():
    a = fingerprint("Acme", "Backend Engineer", "Remote")
    b = fingerprint("Acme", "Frontend Engineer", "Remote")
    assert a != b
