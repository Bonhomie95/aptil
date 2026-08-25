"""Nothing Aptil couldn't complete is kept: parked/failed applications are
deleted, and a periodic purge clears any legacy rows. The user only ever sees
real applications."""

from __future__ import annotations

import uuid

from app.models.enums import ApplicationStatus
from app.models.job import Job, JobApplication
from app.models.user import User
from tests.conftest import requires_mongo
from tests.test_security import _register

pytestmark = [requires_mongo]


async def _app(user: User, status: str, needs_action: str | None = None):
    job = Job(
        fingerprint=uuid.uuid4().hex, source="web_search", ats_type="greenhouse",
        apply_url="https://x/y", company="Acme", title="Platform Engineer",
    )
    await job.insert()
    row = JobApplication(
        user_id=user.id, tenant_id=user.tenant_id, job_id=job.id,
        status=status, needs_action=needs_action,
    )
    await row.insert()
    return row


async def test_purge_deletes_parked_and_failed_but_keeps_the_rest(client):
    email = await _register(client)
    user = await User.find_one(User.email == email)

    keep = [
        await _app(user, ApplicationStatus.MATCHED.value),
        await _app(user, ApplicationStatus.SUBMITTED.value),
        await _app(user, ApplicationStatus.INTERVIEW.value),
        # in-progress managed-account verification is NOT a failure:
        await _app(user, ApplicationStatus.NEEDS_INFO.value,
                   "awaiting_email_verification"),
    ]
    drop = [
        await _app(user, ApplicationStatus.NEEDS_INFO.value, "add_credential"),
        await _app(user, ApplicationStatus.NEEDS_INFO.value, "apply_on_employer_site"),
        await _app(user, ApplicationStatus.FAILED.value),
    ]

    from app.workers.tasks.scheduler import _purge_unapplicable

    res = await _purge_unapplicable()
    assert res["deleted"] == len(drop)

    remaining = await JobApplication.find(
        JobApplication.user_id == user.id
    ).to_list()
    ids = {r.id for r in remaining}
    assert all(k.id in ids for k in keep)
    assert not any(d.id in ids for d in drop)


def test_skip_marker_roundtrip(monkeypatch):
    from app.services import job_cache

    monkeypatch.setattr(job_cache.settings, "JOB_CACHE_TTL_HOURS", 24)
    store: dict[str, str] = {}

    class _R:
        def set(self, k, v, ex=None):
            store[k] = v

        def exists(self, k):
            return 1 if k in store else 0

    monkeypatch.setattr(job_cache, "_redis", lambda: _R())
    assert job_cache.is_unapplicable("u1", "j1") is False
    job_cache.mark_unapplicable("u1", "j1")
    assert job_cache.is_unapplicable("u1", "j1") is True
    assert job_cache.is_unapplicable("u1", "j2") is False
