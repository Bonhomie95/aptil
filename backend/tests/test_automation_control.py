"""Start / pause / stop for the apply engine.

The engine submits applications in the user's name, so the off switch is a
correctness requirement rather than a convenience: after "stop", nothing may go
out. The distinction between pause and stop is the whole point of having both,
so it is asserted directly.
"""

from __future__ import annotations

import uuid

from app.models.enums import ApplicationStatus, AutomationState
from app.models.job import Job, JobApplication
from app.models.user import User
from tests.conftest import requires_mongo
from tests.test_security import _auth, _login, _register

pytestmark = [requires_mongo]


async def _queued_row(user: User) -> JobApplication:
    job = Job(
        fingerprint=uuid.uuid4().hex,
        source="lever",
        apply_url="https://jobs.lever.co/x/1",
        company="Acme",
        title="Engineer",
    )
    await job.insert()
    row = JobApplication(
        user_id=user.id,
        tenant_id=user.tenant_id,
        job_id=job.id,
        status=ApplicationStatus.QUEUED.value,
    )
    await row.insert()
    return row


async def test_automation_runs_by_default(client):
    """Finishing onboarding should start the search, not leave it idle."""
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.get("/api/v1/jobs/automation", headers=_auth(tokens))
    assert resp.status_code == 200
    assert resp.json()["state"] == AutomationState.RUNNING.value


async def test_pause_then_resume_round_trips(client):
    email = await _register(client)
    tokens = await _login(client, email)
    for state in ("paused", "running"):
        resp = await client.post(
            "/api/v1/jobs/automation", json={"state": state}, headers=_auth(tokens)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == state
        assert resp.json()["changed_at"] is not None


async def test_pause_leaves_already_queued_work_alone(client):
    """Work queued BEFORE the pause was authorised then, and the dashboard is
    already showing it. Silently dropping it would show applications that never
    happened."""
    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    row = await _queued_row(user)

    resp = await client.post(
        "/api/v1/jobs/automation", json={"state": "paused"}, headers=_auth(tokens)
    )
    assert resp.status_code == 200
    assert resp.json()["queued"] == 1

    await row.sync()
    assert row.status == ApplicationStatus.QUEUED.value


async def test_stop_cancels_queued_work_so_nothing_goes_out_after(client):
    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    row = await _queued_row(user)

    resp = await client.post(
        "/api/v1/jobs/automation", json={"state": "stopped"}, headers=_auth(tokens)
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "stopped"
    assert resp.json()["queued"] == 0

    await row.sync()
    # Back to `matched`, not `failed` — the user's own decision must not read as
    # an engine failure in their stats.
    assert row.status == ApplicationStatus.MATCHED.value


async def test_unknown_state_is_rejected(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post(
        "/api/v1/jobs/automation", json={"state": "off"}, headers=_auth(tokens)
    )
    assert resp.status_code == 422


async def test_paused_user_is_not_swept(client):
    """The gate has to be in the query, or a paused user is fanned out every
    tick and only discarded downstream."""
    from app.workers.tasks.scheduler import _eligible_users

    email = await _register(client)
    user = await User.find_one(User.email == email)
    user.onboarding_completed = True
    await user.save()
    assert user.id in {u.id for u in await _eligible_users()}

    user.automation_state = AutomationState.PAUSED.value
    await user.save()
    assert user.id not in {u.id for u in await _eligible_users()}

    user.automation_state = AutomationState.STOPPED.value
    await user.save()
    assert user.id not in {u.id for u in await _eligible_users()}

    user.automation_state = AutomationState.RUNNING.value
    await user.save()
    assert user.id in {u.id for u in await _eligible_users()}
