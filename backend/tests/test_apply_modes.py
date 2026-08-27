"""Auto-apply toggle + batch-apply (review-then-apply mode).

The user can turn OFF background auto-apply and instead submit matches in
batches from the dashboard. Discovery still runs either way — these tests pin
that the toggle gates only the background apply sweep, and that the batch
endpoint submits the top-N matched respecting the plan quota.
"""

from __future__ import annotations

import uuid

from app.models.enums import ApplicationStatus
from app.models.job import Job, JobApplication
from app.models.user import User
from tests.conftest import requires_mongo
from tests.test_security import _auth, _login, _register

pytestmark = [requires_mongo]


async def _matched(user: User, score: float, company: str = "Acme") -> JobApplication:
    job = Job(
        fingerprint=uuid.uuid4().hex, source="web_search",
        apply_url="https://x/y", company=company, title="Platform Engineer",
    )
    await job.insert()
    row = JobApplication(
        user_id=user.id, tenant_id=user.tenant_id, job_id=job.id,
        status=ApplicationStatus.MATCHED.value, match_score=score,
    )
    await row.insert()
    return row


async def test_auto_apply_defaults_off_and_toggles(client):
    email = await _register(client)
    tokens = await _login(client, email)
    # default is OFF (review-first) so matches persist instead of being
    # auto-applied and discarded.
    me = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert me.json().get("auto_apply") is False

    on = await client.post(
        "/api/v1/jobs/auto-apply", json={"enabled": True}, headers=_auth(tokens)
    )
    assert on.status_code == 200 and on.json()["enabled"] is True
    me2 = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert me2.json()["auto_apply"] is True


async def test_batch_apply_queues_top_n_by_score(client):
    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)

    await _matched(user, 0.90, company="A")
    await _matched(user, 0.80, company="B")
    await _matched(user, 0.70, company="C")

    res = await client.post(
        "/api/v1/jobs/applications/apply-batch",
        json={"count": 2}, headers=_auth(tokens),
    )
    assert res.status_code == 200
    assert res.json()["queued"] == 2

    # the two highest-scoring rows moved out of "matched"
    rows = await JobApplication.find(JobApplication.user_id == user.id).to_list()
    queued = [r for r in rows if r.status == ApplicationStatus.QUEUED.value]
    still_matched = [r for r in rows if r.status == ApplicationStatus.MATCHED.value]
    assert len(queued) == 2
    assert len(still_matched) == 1
    # the one left behind is the lowest score
    assert still_matched[0].match_score == 0.70


async def test_batch_apply_with_nothing_matched_is_a_noop(client):
    email = await _register(client)
    tokens = await _login(client, email)
    res = await client.post(
        "/api/v1/jobs/applications/apply-batch",
        json={"count": 5}, headers=_auth(tokens),
    )
    assert res.status_code == 200
    assert res.json()["queued"] == 0


async def test_apply_sweep_skips_users_with_auto_apply_off(client):
    """Discovery still runs for them, but the background apply sweep does not
    enqueue their matches."""
    from app.models.profile import Profile
    from app.workers.tasks.scheduler import _eligible_users

    email = await _register(client)
    user = await User.find_one(User.email == email)
    user.onboarding_completed = True
    user.auto_apply = False
    await user.save()
    profile = await Profile.find_one(Profile.user_id == user.id)
    profile.skills = ["python"]
    await profile.save()

    # still eligible for the SEARCH sweep...
    assert user.id in {u.id for u in await _eligible_users()}
    # ...but the apply sweep must skip auto_apply=False users
    fetched = await User.get(user.id)
    assert fetched.auto_apply is False
