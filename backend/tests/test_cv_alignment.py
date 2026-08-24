"""End-to-end proof that a NON-dev CV yields CV-aligned, non-generic matches.

This is the "confirm the jobs aren't generic" check, run as code. It exercises
the real inference, query-building and ranking with a Registered Nurse profile
against a mixed-industry pool — the generic failure it guards against was a pool
of nothing but tech roles.

(The live Adzuna fetch itself needs the server's API keys and is not called
here; _queries_for_profile proves the correct nursing queries WOULD be sent.)
"""

from __future__ import annotations

import uuid

from app.models.job import Job
from app.models.profile import Profile
from app.services.matching import score_job
from app.workers.tasks.cv_parsing import _suggest_target_titles
from app.workers.tasks.sourcing import _queries_for_profile
from tests.conftest import requires_mongo

pytestmark = [requires_mongo]

NURSE_CV = {
    "headline": "Registered Nurse (RN), BSN",
    "work_history": [
        {"title": "Registered Nurse", "company": "St. Mary's Hospital"},
        {"title": "Staff Nurse", "company": "City Medical Center"},
    ],
    "skills": [
        "patient care", "triage", "IV therapy", "electronic health records",
        "medication administration", "wound care",
    ],
}


def _nurse_profile() -> Profile:
    uid = uuid.uuid4()
    return Profile(
        user_id=uid, tenant_id=uid,
        target_titles=["Registered Nurse", "Staff Nurse"],
        skills=NURSE_CV["skills"], city="Boston", country="us",
    )


def _job(company: str, title: str, description: str, source: str = "web_search") -> Job:
    return Job(
        fingerprint=uuid.uuid4().hex, source=source, apply_url="https://x/y",
        company=company, title=title, description=description,
    )


def test_targets_inferred_from_a_nursing_cv_are_nursing():
    titles = _suggest_target_titles(NURSE_CV)
    assert titles
    assert "nurse" in titles[0].lower()


def test_the_queries_actually_sent_are_nursing_and_located():
    queries = _queries_for_profile(_nurse_profile())
    assert queries
    assert all("nurse" in q["what"].lower() for q in queries)
    assert all(q["where"] == "Boston" for q in queries)
    assert all(q["country"] == "us" for q in queries)


def test_nursing_cv_ranks_every_nursing_job_above_every_tech_role():
    """The exact 'too generic, all software engineers' complaint, inverted: a
    nurse must see nursing at the top and tech nowhere near it."""
    prof = _nurse_profile()
    pool = [
        _job("Boston Medical", "Registered Nurse - ICU",
             "patient care triage IV therapy wound care"),
        _job("Mercy Hospital", "Staff Nurse, Emergency",
             "triage medication administration electronic health records"),
        _job("Care Clinic", "Registered Nurse",
             "patient care wound care IV therapy"),
        _job("Stripe", "Senior Backend Engineer",
             "python golang distributed systems kubernetes", source="greenhouse"),
        _job("Databricks", "Site Reliability Engineer",
             "terraform aws observability oncall", source="greenhouse"),
        _job("Acme Marketing", "Content Marketing Manager",
             "seo campaigns social copywriting"),
    ]
    scored = [(score_job(prof, j), j) for j in pool]
    for sc, j in sorted(scored, key=lambda t: t[0], reverse=True):
        tag = "  <- NURSING" if "nurse" in j.title.lower() else ""
        print(f"  {sc:.3f}  {j.title:34} @ {j.company}{tag}")
    nurse = [s for s, j in scored if "nurse" in j.title.lower()]
    other = [s for s, j in scored if "nurse" not in j.title.lower()]
    # Every nursing role outscores every non-nursing role.
    assert min(nurse) > max(other), f"nurse={nurse} other={other}"


# --- geography: choosing where to search ----------------------------------
def test_target_countries_drive_the_search_not_home_address():
    """A user in the US targeting Europe must get European queries, not US."""
    import uuid as _uuid

    from app.models.profile import Profile
    from app.workers.tasks.sourcing import _queries_for_profile

    uid = _uuid.uuid4()
    prof = Profile(
        user_id=uid, tenant_id=uid,
        target_titles=["Registered Nurse"],
        country="us", city="Boston",
        target_countries=["europe"],
    )
    queries = _queries_for_profile(prof)
    hit = {q["country"] for q in queries}
    assert "us" not in hit
    assert "gb" in hit and "de" in hit and "fr" in hit
    # The city is NOT used across a whole continent — "Boston" across Europe is
    # noise. Instead each query carries its country's name as the location, so
    # web search stays geo-targeted per country.
    assert all(q.get("where") != "Boston" for q in queries)
    wheres = {q.get("where") for q in queries}
    assert "United Kingdom" in wheres and "Germany" in wheres


def test_single_country_keeps_the_city_filter():
    import uuid as _uuid

    from app.models.profile import Profile
    from app.workers.tasks.sourcing import _queries_for_profile

    uid = _uuid.uuid4()
    prof = Profile(
        user_id=uid, tenant_id=uid,
        target_titles=["Registered Nurse"],
        city="Boston", target_countries=["us"],
    )
    queries = _queries_for_profile(prof)
    assert all(q["country"] == "us" for q in queries)
    assert all(q.get("where") == "Boston" for q in queries)


def test_no_target_country_falls_back_to_home():
    import uuid as _uuid

    from app.models.profile import Profile
    from app.workers.tasks.sourcing import _queries_for_profile

    uid = _uuid.uuid4()
    prof = Profile(
        user_id=uid, tenant_id=uid,
        target_titles=["Registered Nurse"], country="ca",
    )
    queries = _queries_for_profile(prof)
    assert {q["country"] for q in queries} == {"ca"}


def test_query_fanout_is_capped():
    """A whole-continent, many-title selection must not become dozens of API
    calls per sweep."""
    import uuid as _uuid

    from app.core.config import settings
    from app.models.profile import Profile
    from app.workers.tasks.sourcing import _queries_for_profile

    uid = _uuid.uuid4()
    prof = Profile(
        user_id=uid, tenant_id=uid,
        target_titles=["Nurse", "Staff Nurse", "Charge Nurse", "ICU Nurse"],
        target_countries=["europe", "north_america", "asia"],
    )
    assert len(_queries_for_profile(prof)) <= settings.MAX_DEMAND_QUERIES


# --- web-search discovery (the open-web, aggregator-independent source) ----
def test_websearch_routes_known_ats_and_parks_company_sites():
    """A greenhouse result must carry ats_type so the adapter applies; a random
    company career page must be ats_type=None so the engine parks it honestly."""
    from app.services.connectors.websearch import _ats_for_host

    assert _ats_for_host("boards.greenhouse.io") == "greenhouse"
    assert _ats_for_host("jobs.lever.co") == "lever"
    assert _ats_for_host("acme.myworkdayjobs.com") == "workday"
    assert _ats_for_host("careers.some-hospital.org") is None


def test_websearch_returns_nothing_without_a_key(monkeypatch):
    """No API key = no-op, never a crash, never a scrape fallback."""
    from app.core.config import settings
    from app.services.connectors.websearch import WebSearchConnector

    monkeypatch.setattr(settings, "WEB_SEARCH_API_KEY", "")
    assert WebSearchConnector().fetch({"what": "Registered Nurse"}) == []


def test_websearch_parses_a_brave_style_response(monkeypatch):
    from app.core.config import settings
    from app.services.connectors.websearch import WebSearchConnector

    monkeypatch.setattr(settings, "WEB_SEARCH_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SOURCING_WEB_SEARCH", True)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "brave")

    fake = {
        "web": {"results": [
            {"url": "https://boards.greenhouse.io/acme/jobs/1",
             "title": "Registered Nurse | Acme Health",
             "description": "ICU nurse"},
            {"url": "https://www.linkedin.com/jobs/view/123",   # aggregator, dropped
             "title": "Nurse", "description": "x"},
            {"url": "https://careers.mercy.org/rn",
             "title": "Staff Nurse at Mercy Hospital", "description": "ER"},
        ]}
    }
    conn = WebSearchConnector()
    monkeypatch.setattr(conn, "_get", lambda *a, **k: object())
    monkeypatch.setattr(conn, "_json", lambda _r: fake)

    posts = conn.fetch({"what": "Registered Nurse", "where": "Boston"})
    urls = [p["apply_url"] for p in posts]
    assert "https://boards.greenhouse.io/acme/jobs/1" in urls
    assert "https://careers.mercy.org/rn" in urls
    assert not any("linkedin" in u for u in urls)          # aggregator excluded
    gh = next(p for p in posts if "greenhouse" in p["apply_url"])
    assert gh["ats_type"] == "greenhouse"                   # routes to adapter
    company_site = next(p for p in posts if "mercy" in p["apply_url"])
    assert company_site["ats_type"] is None                 # parks for the user


# --- web-search providers (serper / tavily / searxng) ---------------------
def _install_fake(conn, payload):
    """Route the connector's HTTP layer to a fixed payload."""
    import types

    conn._get = types.MethodType(lambda self, *a, **k: object(), conn)
    conn._post = types.MethodType(lambda self, *a, **k: object(), conn)
    conn._json = types.MethodType(lambda self, _r: payload, conn)


def test_serper_provider_parses_organic_results(monkeypatch):
    from app.core.config import settings
    from app.services.connectors.websearch import WebSearchConnector

    monkeypatch.setattr(settings, "SOURCING_WEB_SEARCH", True)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "serper")
    monkeypatch.setattr(settings, "WEB_SEARCH_API_KEY", "k")
    conn = WebSearchConnector()
    _install_fake(conn, {"organic": [
        {"link": "https://boards.greenhouse.io/x/jobs/1",
         "title": "Registered Nurse", "snippet": "ICU"},
    ]})
    posts = conn.fetch({"what": "Registered Nurse"})
    assert posts and posts[0]["ats_type"] == "greenhouse"


def test_tavily_provider_parses_results(monkeypatch):
    from app.core.config import settings
    from app.services.connectors.websearch import WebSearchConnector

    monkeypatch.setattr(settings, "SOURCING_WEB_SEARCH", True)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(settings, "WEB_SEARCH_API_KEY", "k")
    conn = WebSearchConnector()
    _install_fake(conn, {"results": [
        {"url": "https://jobs.lever.co/y/2", "title": "Staff Nurse", "content": "ER"},
    ]})
    posts = conn.fetch({"what": "Staff Nurse"})
    assert posts and posts[0]["ats_type"] == "lever"


def test_searxng_provider_needs_no_api_key(monkeypatch):
    """Self-hosted SearXNG is keyless — an empty WEB_SEARCH_API_KEY must NOT
    disable it (that check is only for the hosted providers)."""
    from app.core.config import settings
    from app.services.connectors.websearch import WebSearchConnector

    monkeypatch.setattr(settings, "SOURCING_WEB_SEARCH", True)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(settings, "WEB_SEARCH_API_KEY", "")   # no key on purpose
    conn = WebSearchConnector()
    _install_fake(conn, {"results": [
        {"url": "https://careers.mercy.org/rn", "title": "Nurse at Mercy",
         "content": "x"},
    ]})
    posts = conn.fetch({"what": "Nurse"})
    assert posts  # keyless provider still returns results
    assert posts[0]["ats_type"] is None  # company site -> parks


def test_hosted_provider_without_key_is_a_noop(monkeypatch):
    from app.core.config import settings
    from app.services.connectors.websearch import WebSearchConnector

    monkeypatch.setattr(settings, "SOURCING_WEB_SEARCH", True)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "serper")
    monkeypatch.setattr(settings, "WEB_SEARCH_API_KEY", "")
    assert WebSearchConnector().fetch({"what": "Nurse"}) == []
