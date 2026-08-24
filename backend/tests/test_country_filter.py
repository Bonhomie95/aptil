"""Country filtering: choosing USA must not surface other countries.

This is the exact bug from the dashboard screenshot — a US-targeted user seeing
Singapore, Vietnam and India roles. The filter is HARD (drop, not down-rank) and
applies at match time, on the dashboard list, and on the Jobs browse page.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.geo import detect_countries, location_allowed


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Singapore, Singapore", {"sg"}),
        ("Ho Chi Minh City, Vietnam", {"vn"}),
        ("Remote - India", {"in"}),
        ("Bangalore", {"in"}),
        ("Remote, USA", {"us"}),
        ("New York, NY", set()),      # US city, no country named -> ambiguous
        ("London, UK", {"gb"}),
        ("Austin, TX", set()),        # must NOT detect a country ("us" in Austin)
        ("", set()),
    ],
)
def test_detect_countries(location, expected):
    assert detect_countries(location) == expected


def test_us_target_rejects_other_countries():
    us = {"us"}
    assert location_allowed("Remote, USA", us) is True
    assert location_allowed("New York, NY", us) is True        # ambiguous -> keep
    assert location_allowed("Singapore, Singapore", us) is False
    assert location_allowed("Ho Chi Minh City, Vietnam", us) is False
    assert location_allowed("Remote - India", us) is False
    assert location_allowed("London, UK", us) is False


def test_no_targets_allows_everything():
    assert location_allowed("Singapore, Singapore", set()) is True


def test_continent_target_expands():
    from app.models.profile import Profile
    from app.services.matching import _target_country_codes

    uid = uuid.uuid4()
    prof = Profile(user_id=uid, tenant_id=uid, target_countries=["europe"])
    codes = _target_country_codes(prof)
    assert "de" in codes and "fr" in codes and "us" not in codes
    assert location_allowed("Berlin, Germany", codes) is True
    assert location_allowed("Remote, USA", codes) is False


# --- integration: matching drops out-of-country jobs ----------------------
@pytest.mark.parametrize("_", [0])  # keeps pytest-anyio happy with the fixture
async def test_matching_excludes_other_countries(client, _):
    from app.models.job import Job, JobApplication
    from app.models.profile import Profile
    from app.models.user import User
    from app.services.matching import match_jobs_for_user
    from tests.test_security import _register

    email = await _register(client)
    user = await User.find_one(User.email == email)
    profile = await Profile.find_one(Profile.user_id == user.id)
    profile.target_titles = ["Site Reliability Engineer"]
    profile.skills = ["kubernetes", "terraform", "observability"]
    profile.target_countries = ["us"]
    await profile.save()

    us_job = Job(
        fingerprint=uuid.uuid4().hex, source="web_search", ats_type="greenhouse", apply_url="https://x/1",
        company="Acme", title="Site Reliability Engineer",
        description="kubernetes terraform observability", location="Remote, USA",
    )
    sg_job = Job(
        fingerprint=uuid.uuid4().hex, source="web_search", ats_type="greenhouse", apply_url="https://x/2",
        company="Globex", title="Site Reliability Engineer",
        description="kubernetes terraform observability",
        location="Singapore, Singapore",
    )
    await us_job.insert()
    await sg_job.insert()

    await match_jobs_for_user(user.id, limit=20, min_score=0.0)

    apps = await JobApplication.find(JobApplication.user_id == user.id).to_list()
    locs = set()
    for a in apps:
        job = await Job.get(a.job_id)
        if job:
            locs.add(job.location)
    assert "Remote, USA" in locs
    assert "Singapore, Singapore" not in locs


def test_comprehensive_country_detection_catches_latam_and_europe():
    """Regression: the original list missed Ecuador/Peru so LatAm jobs leaked
    through a US filter. Detection must cover countries beyond the search
    targets, precisely so they can be excluded."""
    for loc, code in [
        ("Ecuador, Ecuador; Lima, Peru", "ec"),
        ("Lima, Peru", "pe"),
        ("Quito, Ecuador", "ec"),
        ("Toronto, Canada", "ca"),
        ("Berlin, Germany", "de"),
        ("Bogotá, Colombia", "co"),
        ("Manila, Philippines", "ph"),
    ]:
        assert code in detect_countries(loc), loc
        # ...and each is excluded for a US-only target.
        assert location_allowed(loc, {"us"}) is False, loc
