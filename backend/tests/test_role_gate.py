"""Role-relevance gate + cross-listing dedupe.

The bug this pins: an SRE/Platform/Cloud seeker seeing "Machine Learning
Infrastructure Engineer" and "Backend Engineer" at 86%, because matching
credited the shared word "Engineer". The gate requires a shared DOMAIN word.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.matching import _domain_tokens, role_relevant
from tests.conftest import requires_mongo
from tests.test_security import _register

pytestmark = [requires_mongo]


def _prof(**kw):
    from app.models.profile import Profile

    uid = uuid.uuid4()
    return Profile(user_id=uid, tenant_id=uid, **kw)


def _job(title, **kw):
    from app.models.job import Job

    return Job(
        fingerprint=uuid.uuid4().hex, source="web_search",
        apply_url="https://x/y", company=kw.pop("company", "Acme"),
        title=title, **kw,
    )


def test_engineer_alone_is_not_a_domain_match():
    assert "engineer" not in _domain_tokens("Platform Engineer")
    assert _domain_tokens("Platform Engineer") == {"platform"}


@pytest.mark.parametrize(
    "title,relevant",
    [
        ("Machine Learning Infrastructure Engineer", False),
        ("Backend Engineer", False),
        ("Data Scientist", False),
        ("Marketing Manager", False),
        # genuinely matches the SRE/Platform/Cloud targets:
        ("Site Reliability Engineer", True),
        ("Senior Software Engineer, Core Platform", True),
        ("Cloud Security Engineer", True),
        ("Problem Manager", True),
    ],
)
def test_role_gate_against_sre_platform_cloud(title, relevant):
    prof = _prof(target_titles=[
        "Site Reliability Engineering (SRE)", "Platform Engineer",
        "Cloud Engineer", "Problem Management",
    ])
    assert role_relevant(prof, _job(title)) is relevant


def test_sre_acronym_matches_full_title():
    prof = _prof(target_titles=["SRE"])
    assert role_relevant(prof, _job("Site Reliability Engineer")) is True


def test_no_targets_means_no_gate():
    prof = _prof(target_titles=[])
    assert role_relevant(prof, _job("Anything At All")) is True


# --- integration: unrelated + duplicate rows do not become applications ----
async def test_matching_gates_role_and_dedupes(client):
    from app.models.job import Job, JobApplication
    from app.models.profile import Profile
    from app.models.user import User
    from app.services.matching import match_jobs_for_user

    email = await _register(client)
    user = await User.find_one(User.email == email)
    profile = await Profile.find_one(Profile.user_id == user.id)
    profile.target_titles = ["Platform Engineer"]
    profile.skills = ["kubernetes", "terraform", "aws"]
    await profile.save()

    # two duplicate listings of the same platform role (different cities)
    for loc in ("Remote, USA", "New York, NY"):
        await _job("Senior Software Engineer, Core Platform",
                   description="kubernetes terraform aws", location=loc).insert()
    # an unrelated role that shares only "Engineer"
    await _job("Machine Learning Infrastructure Engineer",
               description="kubernetes terraform aws", location="Remote, USA").insert()

    await match_jobs_for_user(user.id, limit=20, min_score=0.0)

    apps = await JobApplication.find(JobApplication.user_id == user.id).to_list()
    titles = []
    for a in apps:
        job = await Job.get(a.job_id)
        if job:
            titles.append(job.title)
    # the ML role is gated out
    assert not any("Machine Learning" in t for t in titles)
    # the duplicated platform role appears exactly once
    assert sum("Core Platform" in t for t in titles) == 1
