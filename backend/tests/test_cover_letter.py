"""Cover-letter view/edit endpoints. Generation itself needs the LLM and is not
called here; these pin the ownership, the edit round-trip, and the lock after
submission."""

from __future__ import annotations

import uuid

from app.models.enums import ApplicationStatus
from app.models.job import Job, JobApplication
from app.models.user import User
from tests.conftest import requires_mongo
from tests.test_security import _auth, _login, _register

pytestmark = [requires_mongo]


async def _app(user: User, status="matched", cover_letter=None):
    job = Job(
        fingerprint=uuid.uuid4().hex, source="web_search", ats_type="greenhouse",
        apply_url="https://x/y", company="Acme", title="Platform Engineer",
    )
    await job.insert()
    row = JobApplication(
        user_id=user.id, tenant_id=user.tenant_id, job_id=job.id,
        status=status, cover_letter=cover_letter,
    )
    await row.insert()
    return row


async def test_get_and_edit_cover_letter(client):
    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    row = await _app(user, cover_letter="Original letter.")

    got = await client.get(
        f"/api/v1/jobs/applications/{row.id}/cover-letter", headers=_auth(tokens)
    )
    assert got.json()["cover_letter"] == "Original letter."

    edited = await client.put(
        f"/api/v1/jobs/applications/{row.id}/cover-letter",
        json={"cover_letter": "My own words."},
        headers=_auth(tokens),
    )
    assert edited.status_code == 200
    assert edited.json()["cover_letter"] == "My own words."

    fresh = await JobApplication.get(row.id)
    assert fresh.cover_letter == "My own words."


async def test_cannot_edit_after_submission(client):
    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    row = await _app(user, status=ApplicationStatus.SUBMITTED.value, cover_letter="Sent.")

    resp = await client.put(
        f"/api/v1/jobs/applications/{row.id}/cover-letter",
        json={"cover_letter": "too late"},
        headers=_auth(tokens),
    )
    assert resp.status_code == 409


async def test_cover_letter_shows_on_the_application_list(client):
    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    await _app(user, cover_letter="Visible letter.")

    apps = await client.get("/api/v1/jobs/applications", headers=_auth(tokens))
    assert any(a.get("cover_letter") == "Visible letter." for a in apps.json())


async def test_cannot_touch_another_users_cover_letter(client):
    email = await _register(client)
    tokens = await _login(client, email)
    other_email = await _register(client)
    other = await User.find_one(User.email == other_email)
    row = await _app(other, cover_letter="secret")

    resp = await client.get(
        f"/api/v1/jobs/applications/{row.id}/cover-letter", headers=_auth(tokens)
    )
    assert resp.status_code == 404
