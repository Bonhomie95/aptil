"""Apply-pipeline URL and host handling.

Every one of these covers a bug that shipped and silently parked real
applications as "application_form_not_recognised".
"""

from __future__ import annotations

import pytest

from app.services.ats.base import _host_matches
from app.services.connectors.greenhouse import GreenhouseConnector
from app.services.connectors.lever import LeverConnector


# --- host matching --------------------------------------------------------
@pytest.mark.parametrize(
    "host,expected",
    [
        ("job-boards.greenhouse.io", True),
        ("boards.greenhouse.io", True),
        ("greenhouse.io", True),
        # str.endswith("greenhouse.io") would have accepted this one.
        ("notgreenhouse.io", False),
        ("greenhouse.io.evil.com", False),
        ("stripe.com", False),
        ("", False),
    ],
)
def test_host_matches_rejects_lookalike_domains(host, expected):
    assert _host_matches(host, ("greenhouse.io",)) is expected


# --- Greenhouse: absolute_url is not the application form -----------------
def test_greenhouse_apply_url_is_the_canonical_form_not_the_employer_site(
    monkeypatch,
):
    """Stripe's absolute_url is stripe.com/jobs/... — a page with no form on it.

    The application form is always at job-boards.greenhouse.io/<board>/jobs/<id>,
    which returns 200 even for employers who redirect human visitors elsewhere.
    """
    conn = GreenhouseConnector()
    payload = {
        "jobs": [
            {
                "id": 8130725,
                "title": "Account Executive",
                "absolute_url": "https://stripe.com/jobs/search?gh_jid=8130725",
                "location": {"name": "Remote"},
                "content": "desc",
            }
        ]
    }
    monkeypatch.setattr(conn, "_get", lambda *a, **k: object())
    monkeypatch.setattr(conn, "_json", lambda _resp: payload)

    posting = conn.fetch({"board": "stripe"})[0]

    assert posting["apply_url"] == "https://job-boards.greenhouse.io/stripe/jobs/8130725"
    # The employer's own page is still kept, for the "view posting" link.
    assert posting["listing_url"] == "https://stripe.com/jobs/search?gh_jid=8130725"


def test_greenhouse_falls_back_to_absolute_url_without_an_id(monkeypatch):
    conn = GreenhouseConnector()
    payload = {
        "jobs": [
            {
                "id": None,
                "title": "Engineer",
                "absolute_url": "https://job-boards.greenhouse.io/x/jobs/1",
                "location": {"name": "Remote"},
            }
        ]
    }
    monkeypatch.setattr(conn, "_get", lambda *a, **k: object())
    monkeypatch.setattr(conn, "_json", lambda _resp: payload)

    posting = conn.fetch({"board": "x"})[0]
    assert posting["apply_url"] == "https://job-boards.greenhouse.io/x/jobs/1"


# --- Lever: hostedUrl is the description, applyUrl is the form ------------
def test_lever_prefers_the_apply_form_over_the_description_page(monkeypatch):
    conn = LeverConnector()
    payload = [
        {
            "id": "abc",
            "text": "Backend Engineer",
            "hostedUrl": "https://jobs.lever.co/acme/abc",
            "applyUrl": "https://jobs.lever.co/acme/abc/apply",
            "categories": {"location": "Remote"},
        }
    ]
    monkeypatch.setattr(conn, "_get", lambda *a, **k: object())
    monkeypatch.setattr(conn, "_json", lambda _resp: payload)

    posting = conn.fetch({"company": "acme"})[0]
    assert posting["apply_url"].endswith("/apply")
    assert posting["listing_url"] == "https://jobs.lever.co/acme/abc"


def test_lever_derives_the_apply_url_when_the_api_omits_it(monkeypatch):
    conn = LeverConnector()
    payload = [
        {
            "id": "abc",
            "text": "Backend Engineer",
            "hostedUrl": "https://jobs.lever.co/acme/abc/",
            "categories": {"location": "Remote"},
        }
    ]
    monkeypatch.setattr(conn, "_get", lambda *a, **k: object())
    monkeypatch.setattr(conn, "_json", lambda _resp: payload)

    posting = conn.fetch({"company": "acme"})[0]
    assert posting["apply_url"] == "https://jobs.lever.co/acme/abc/apply"


# --- matching intent ------------------------------------------------------
def _profile(**kw):
    import uuid

    from app.models.profile import Profile

    uid = uuid.uuid4()
    return Profile(user_id=uid, tenant_id=uid, **kw)


def _job(title, description="", location=None, remote=None):
    from app.models.job import Job

    return Job(
        fingerprint="f", source="greenhouse", apply_url="https://x/y",
        company="Acme", title=title, description=description,
        location=location, remote=remote,
    )


def test_stated_target_beats_cv_history():
    """Someone moving from support into SRE should be scored on where they are
    going, not on the job they are trying to leave."""
    from app.services.matching import _title_similarity

    moving = _profile(
        work_history=[{"title": "Customer Support Specialist"}],
        target_titles=["Site Reliability Engineer"],
    )
    sre = _job("Site Reliability Engineer")
    support = _job("Customer Support Specialist")

    assert _title_similarity(moving, sre) > _title_similarity(moving, support)


def test_falls_back_to_cv_when_no_target_is_stated():
    from app.services.matching import _title_similarity

    p = _profile(work_history=[{"title": "Backend Engineer"}])
    assert _title_similarity(p, _job("Backend Engineer")) > 0.8


def test_multiple_targets_are_scored_best_of_not_averaged():
    """Wanting either of two roles must not make both match worse."""
    from app.services.matching import _title_similarity

    one = _profile(target_titles=["Site Reliability Engineer"])
    two = _profile(target_titles=["Site Reliability Engineer", "Product Manager"])
    job = _job("Site Reliability Engineer")

    assert _title_similarity(two, job) == _title_similarity(one, job)


# --- CV prefill so the targets step is a confirmation, not a chore ---------
def test_target_titles_are_suggested_from_the_cv():
    from app.workers.tasks.cv_parsing import _suggest_target_titles

    assert _suggest_target_titles(
        {"work_history": [{"title": "Senior Backend Engineer"}], "headline": ""}
    ) == ["Senior Backend Engineer"]


def test_headline_is_kept_when_it_names_a_different_ambition():
    """A headline is often where someone states where they want to GO."""
    from app.workers.tasks.cv_parsing import _suggest_target_titles

    out = _suggest_target_titles(
        {
            "work_history": [{"title": "Customer Support Specialist"}],
            "headline": "Aspiring Site Reliability Engineer",
        }
    )
    assert out == ["Customer Support Specialist", "Aspiring Site Reliability Engineer"]


def test_duplicate_headline_is_not_suggested_twice():
    from app.workers.tasks.cv_parsing import _suggest_target_titles

    assert _suggest_target_titles(
        {"work_history": [{"title": "Product Manager"}], "headline": "product manager"}
    ) == ["Product Manager"]


def test_no_history_and_no_headline_suggests_nothing():
    from app.workers.tasks.cv_parsing import _suggest_target_titles

    assert _suggest_target_titles({"work_history": [], "headline": ""}) == []
