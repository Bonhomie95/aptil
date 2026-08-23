"""Pure unit tests — no external services required."""

from __future__ import annotations

import pytest

from app.api.v1.routes.interviews import _clean_feedback, _normalize_questions
from app.core.security import (
    hash_lookup_token,
    hash_password,
    verify_password,
)
from app.services.auth_service import cooldown_for, normalize_email
from app.services.storage import safe_filename
from app.workers.tasks.discovery import fingerprint


# --- fingerprint / dedupe -------------------------------------------------
def test_fingerprint_is_source_agnostic():
    a = fingerprint("Acme Corp", "Senior Backend Engineer", "London, UK")
    b = fingerprint("acme corp", "senior  backend engineer", "london uk")
    assert a == b


def test_fingerprint_distinguishes_roles():
    a = fingerprint("Acme", "Backend Engineer", "Remote")
    b = fingerprint("Acme", "Frontend Engineer", "Remote")
    assert a != b


# --- filename sanitisation (path traversal) -------------------------------
@pytest.mark.parametrize(
    "given",
    [
        "../../../etc/passwd",
        "..\\..\\windows\\system32\\cfg.ini",
        "/absolute/path/cv.pdf",
        "....//....//escape.pdf",
    ],
)
def test_safe_filename_strips_traversal(given):
    cleaned = safe_filename(given)
    assert "/" not in cleaned
    assert "\\" not in cleaned
    assert not cleaned.startswith(".")
    assert ".." not in cleaned


def test_safe_filename_keeps_reasonable_names():
    assert safe_filename("Jane_Doe-CV.pdf") == "Jane_Doe-CV.pdf"


def test_safe_filename_falls_back_when_empty():
    assert safe_filename("") == "resume"
    assert safe_filename("...") == "resume"


def test_safe_filename_truncates_but_keeps_extension():
    out = safe_filename("a" * 400 + ".pdf")
    assert len(out) <= 120
    assert out.endswith(".pdf")


# --- password hashing -----------------------------------------------------
def test_password_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_verify_password_handles_missing_hash():
    # Must not raise, and must still burn a hash cycle (no user enumeration).
    assert verify_password("anything", None) is False


def test_verify_password_handles_corrupt_hash():
    assert verify_password("anything", "not-a-real-hash") is False


def test_link_tokens_are_hashed_for_storage():
    token = "a-secret-link-token"
    assert hash_lookup_token(token) != token
    assert hash_lookup_token(token) == hash_lookup_token(token)


# --- resend cooldown ------------------------------------------------------
def test_cooldown_doubles_then_caps():
    assert cooldown_for(0) == 30
    assert cooldown_for(1) == 60
    assert cooldown_for(2) == 120
    # Must not grow without bound: 30 * 2**10 would be 8.5 hours.
    assert cooldown_for(10) == 30 * 60
    assert cooldown_for(999) == 30 * 60


def test_normalize_email():
    assert normalize_email("  Jane.Doe@Example.COM ") == "jane.doe@example.com"


# --- interview response hardening ----------------------------------------
def test_normalize_questions_drops_garbage():
    raw = [
        {"question": "Tell me about yourself", "type": "behavioural"},
        {"question": "   "},          # blank
        "A bare string question",       # tolerated
        42,                              # nonsense
        None,
    ]
    out = _normalize_questions(raw, 10)
    assert len(out) == 2
    assert out[0]["question"] == "Tell me about yourself"
    assert out[1]["type"] == "general"


def test_normalize_questions_respects_limit():
    raw = [{"question": f"q{i}"} for i in range(50)]
    assert len(_normalize_questions(raw, 5)) == 5


def test_normalize_questions_handles_non_list():
    assert _normalize_questions(None, 5) == []
    assert _normalize_questions({"nope": 1}, 5) == []


def test_clean_feedback_clamps_score():
    assert _clean_feedback({"score": 99})["score"] == 10.0
    assert _clean_feedback({"score": -5})["score"] == 0.0
    assert _clean_feedback({"score": "not a number"})["score"] == 0.0
    assert _clean_feedback("garbage")["score"] == 0.0


def test_clean_feedback_normalises_lists():
    out = _clean_feedback({"score": 7, "strengths": "just one", "improvements": None})
    assert out["strengths"] == ["just one"]
    assert out["improvements"] == []
