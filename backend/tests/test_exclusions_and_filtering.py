"""Company exclusion and the intervention-hiding dashboard filter.

Both are user-facing promises with a sharp failure mode: an excluded company
must NEVER produce an application, and the default dashboard must never surface
the "you need to act" pile as if it were progress.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import ApplicationStatus
from app.models.job import Job, JobApplication
from app.models.user import User
from app.services.matching import _company_key, _excluded_company_keys
from tests.conftest import requires_mongo
from tests.test_security import _auth, _login, _register

pytestmark = [requires_mongo]


# --- company key normalisation (pure) ------------------------------------
@pytest.mark.parametrize(
    "company,excluded,should_match",
    [
        ("Acme, Inc.", "Acme", True),
        ("Acme LLC", "acme", True),
        ("Acme Corporation", "ACME", True),
        ("The Walt Disney Company", "Walt Disney", True),
        ("Metabase", "Meta", False),        # substring must NOT match
        ("Google", "Meta", False),
    ],
)
def test_company_key_matching(company, excluded, should_match):
    assert (_company_key(company) == _company_key(excluded)) is should_match


def _profile(**kw):
    from app.models.profile import Profile

    uid = uuid.uuid4()
    return Profile(user_id=uid, tenant_id=uid, **kw)


def test_excluded_keys_ignore_blanks():
    p = _profile(excluded_companies=["Acme", "  ", "", "Globex"])
    assert _excluded_company_keys(p) == {"acme", "globex"}


# --- matching honours the exclusion (integration) ------------------------
async def test_excluded_company_never_becomes_an_application(client):
    from app.services.matching import match_jobs_for_user

    email = await _register(client)
    user = await User.find_one(User.email == email)
    from app.models.profile import Profile

    profile = await Profile.find_one(Profile.user_id == user.id)
    profile.target_titles = ["Registered Nurse"]
    profile.skills = ["patient care", "triage"]
    profile.excluded_companies = ["Bad Hospital"]
    await profile.save()

    good = Job(
        fingerprint=uuid.uuid4().hex, source="adzuna", ats_type="greenhouse",
        apply_url="https://x/1", company="Good Clinic",
        title="Registered Nurse", description="patient care triage",
    )
    bad = Job(
        fingerprint=uuid.uuid4().hex, source="adzuna", ats_type="greenhouse",
        apply_url="https://x/2", company="Bad Hospital, Inc.",
        title="Registered Nurse", description="patient care triage",
    )
    await good.insert()
    await bad.insert()

    await match_jobs_for_user(user.id, limit=20, min_score=0.0)

    apps = await JobApplication.find(JobApplication.user_id == user.id).to_list()
    companies = set()
    for a in apps:
        job = await Job.get(a.job_id)
        if job:
            companies.add(job.company)
    assert "Good Clinic" in companies
    assert "Bad Hospital, Inc." not in companies


# --- the dashboard filter -------------------------------------------------
async def test_dashboard_shows_only_applyable_and_successful(client):
    """A job Aptil could not apply to (parked / failed) is hidden entirely — no
    count, no toggle. The dashboard shows only the pipeline toward a real
    application and genuine employer outcomes."""
    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)

    async def _app(status, needs_action=None):
        job = Job(
            fingerprint=uuid.uuid4().hex, source="web_search", ats_type="greenhouse",
            apply_url="https://x/y", company="Acme", title="Nurse",
        )
        await job.insert()
        row = JobApplication(
            user_id=user.id, tenant_id=user.tenant_id, job_id=job.id,
            status=status, needs_action=needs_action,
        )
        await row.insert()
        return row

    await _app(ApplicationStatus.SUBMITTED.value)
    await _app(ApplicationStatus.QUEUED.value)
    await _app(ApplicationStatus.MATCHED.value)
    await _app(ApplicationStatus.INTERVIEW.value)
    # These must be hidden — Aptil could not complete them:
    await _app(ApplicationStatus.NEEDS_INFO.value, "add_credential")
    await _app(ApplicationStatus.NEEDS_INFO.value, "apply_on_employer_site")
    await _app(ApplicationStatus.FAILED.value)

    default = await client.get("/api/v1/jobs/applications", headers=_auth(tokens))
    statuses = sorted({a["status"] for a in default.json()})
    assert statuses == ["interview", "matched", "queued", "submitted"]
    assert "needs_info" not in statuses
    assert "failed" not in statuses

    # The parked/failed rows still exist and are reachable with include_all,
    # they are just never shown by default.
    allrows = await client.get(
        "/api/v1/jobs/applications?include_all=true", headers=_auth(tokens)
    )
    all_statuses = {a["status"] for a in allrows.json()}
    assert "needs_info" in all_statuses
    assert "failed" in all_statuses


async def test_stats_no_longer_advertises_a_needs_you_pile(client):
    """The 'N applications need a step from you' surface was removed — stats
    must not carry that count any more."""
    email = await _register(client)
    tokens = await _login(client, email)
    stats = await client.get("/api/v1/jobs/stats", headers=_auth(tokens))
    assert "needs_you" not in stats.json()
