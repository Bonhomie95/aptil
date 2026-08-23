"""Security regression tests.

Each test pins a specific vulnerability or hardening measure so a future change
cannot silently reintroduce it. Runs against a real MongoDB via the ASGI app.
"""

from __future__ import annotations

import uuid

from tests.conftest import requires_mongo

# asyncio_mode=auto (pyproject) runs these; do NOT add pytest.mark.anyio as well —
# the two plugins would each spin up their own loop and the Mongo client,
# which binds to its creating loop, breaks.
pytestmark = [requires_mongo]

PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def _register(client, email: str | None = None, verify: bool = True):
    email = email or _email()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": "Test User",
            "accepted_terms": True,
        },
    )
    assert resp.status_code == 201, resp.text
    if verify:
        from app.models.user import User

        user = await User.find_one(User.email == email)
        user.is_email_verified = True
        await user.save()
    return email


async def _login(client, email: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
async def test_malformed_jwt_subject_returns_401_not_500(client):
    """A non-UUID `sub` used to raise ValueError -> HTTP 500."""
    import jwt

    from app.core.config import settings

    token = jwt.encode(
        {"sub": "not-a-uuid", "type": "access", "ver": 0},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_refresh_token_cannot_be_used_as_access_token(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert resp.status_code == 401


async def test_token_signed_with_wrong_secret_rejected(client):
    import jwt

    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "ver": 0},
        "an-attacker-controlled-secret",
        algorithm="HS256",
    )
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_alg_none_token_rejected(client):
    """Classic JWT downgrade: unsigned token must never authenticate."""
    import jwt

    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "ver": 0},
        key="",
        algorithm="none",
    )
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_unauthenticated_access_is_401(client):
    for path in (
        "/api/v1/auth/me",
        "/api/v1/onboarding/state",
        "/api/v1/jobs/applications",
        "/api/v1/jobs/stats",
        "/api/v1/billing/subscription",
        "/api/v1/account/export",
    ):
        resp = await client.get(path)
        assert resp.status_code == 401, f"{path} returned {resp.status_code}"


async def test_refresh_rotation_revokes_the_old_token(client):
    email = await _register(client)
    tokens = await _login(client, email)

    first = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 200

    # Replaying the now-rotated token must fail (and kill the family).
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401

    # Reuse detection revokes every session, including the new one.
    after = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first.json()["refresh_token"]},
    )
    assert after.status_code == 401


async def test_disabled_account_cannot_refresh(client):
    from app.models.user import User

    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    user.is_active = False
    await user.save()

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401


async def test_password_change_invalidates_existing_tokens(client):
    email = await _register(client)
    tokens = await _login(client, email)

    changed = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password-1"},
        headers=_auth(tokens),
    )
    assert changed.status_code == 200

    # The old access token must stop working immediately.
    stale = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert stale.status_code == 401
    # The freshly returned pair must work.
    fresh = await client.get("/api/v1/auth/me", headers=_auth(changed.json()))
    assert fresh.status_code == 200


async def test_logout_revokes_refresh_token(client):
    email = await _register(client)
    tokens = await _login(client, email)
    out = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=_auth(tokens),
    )
    assert out.status_code == 204
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Account enumeration & registration
# --------------------------------------------------------------------------
async def test_forgot_password_does_not_leak_account_existence(client):
    email = await _register(client)
    known = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    unknown = await client.post(
        "/api/v1/auth/forgot-password", json={"email": _email()}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


async def test_duplicate_registration_is_409_not_500(client):
    email = await _register(client, verify=False)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "accepted_terms": True},
    )
    assert resp.status_code == 409


async def test_registration_requires_terms_acceptance(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": _email(), "password": PASSWORD, "accepted_terms": False},
    )
    assert resp.status_code == 422


async def test_registration_rejects_short_password(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": _email(), "password": "short", "accepted_terms": True},
    )
    assert resp.status_code == 422
    # The client renders `detail` directly — it must be a string, not an array.
    assert isinstance(resp.json()["detail"], str)


async def test_unverified_user_gets_distinct_login_error(client):
    email = await _register(client, verify=False)
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "email_not_verified"


async def test_registration_creates_profile_and_subscription(client):
    """The CV-parse worker races the request; the profile must already exist."""
    from app.models.profile import Profile
    from app.models.user import User
    from app.services import billing

    email = await _register(client)
    user = await User.find_one(User.email == email)
    assert await Profile.find_one(Profile.user_id == user.id) is not None
    sub = await billing.get_active_subscription(user.tenant_id)
    assert sub is not None, "new accounts must land on the free plan"


# --------------------------------------------------------------------------
# Tenant isolation
# --------------------------------------------------------------------------
async def test_user_cannot_read_another_users_interview(client):
    from app.models.interview import InterviewSession
    from app.models.user import User

    victim_email = await _register(client)
    attacker_email = await _register(client)
    victim = await User.find_one(User.email == victim_email)

    session = InterviewSession(
        user_id=victim.id,
        tenant_id=victim.tenant_id,
        questions=[{"question": "secret", "type": "general"}],
    )
    await session.insert()

    attacker_tokens = await _login(client, attacker_email)
    for method, path in (
        ("get", f"/api/v1/interviews/{session.id}"),
        ("post", f"/api/v1/interviews/{session.id}/complete"),
        ("delete", f"/api/v1/interviews/{session.id}"),
    ):
        resp = await getattr(client, method)(path, headers=_auth(attacker_tokens))
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"


async def test_user_cannot_mutate_another_users_application(client):
    from app.models.job import Job, JobApplication
    from app.models.user import User

    victim_email = await _register(client)
    attacker_email = await _register(client)
    victim = await User.find_one(User.email == victim_email)

    job = Job(
        fingerprint=uuid.uuid4().hex,
        source="greenhouse",
        apply_url="https://boards.greenhouse.io/x/jobs/1",
        company="Acme",
        title="Engineer",
    )
    await job.insert()
    app_row = JobApplication(
        user_id=victim.id, tenant_id=victim.tenant_id, job_id=job.id, status="matched"
    )
    await app_row.insert()

    attacker_tokens = await _login(client, attacker_email)
    resp = await client.patch(
        f"/api/v1/jobs/applications/{app_row.id}",
        json={"status": "offer"},
        headers=_auth(attacker_tokens),
    )
    assert resp.status_code == 404

    resp = await client.post(
        f"/api/v1/jobs/applications/{app_row.id}/apply",
        headers=_auth(attacker_tokens),
    )
    assert resp.status_code == 404


async def test_user_cannot_delete_another_users_credential(client):
    from app.core.security import encrypt_secret
    from app.models.profile import SiteCredential
    from app.models.user import User

    victim_email = await _register(client)
    attacker_email = await _register(client)
    victim = await User.find_one(User.email == victim_email)

    cred = SiteCredential(
        user_id=victim.id,
        tenant_id=victim.tenant_id,
        site_domain="greenhouse.io",
        login_email=victim_email,
        encrypted_password=encrypt_secret("hunter2"),
    )
    await cred.insert()

    attacker_tokens = await _login(client, attacker_email)
    resp = await client.delete(
        f"/api/v1/onboarding/credentials/{cred.id}", headers=_auth(attacker_tokens)
    )
    assert resp.status_code == 404
    assert await SiteCredential.get(cred.id) is not None


async def test_credentials_endpoint_never_returns_secrets(client):
    email = await _register(client)
    tokens = await _login(client, email)
    created = await client.post(
        "/api/v1/onboarding/credentials",
        json={
            "site_domain": "boards.greenhouse.io",
            "login_email": email,
            "password": "super-secret-value",
        },
        headers=_auth(tokens),
    )
    assert created.status_code == 201
    body = created.text
    assert "super-secret-value" not in body
    assert "encrypted_password" not in body

    listed = await client.get("/api/v1/onboarding/credentials", headers=_auth(tokens))
    assert listed.status_code == 200
    assert "super-secret-value" not in listed.text


async def test_export_excludes_secrets(client):
    from app.core.security import encrypt_secret
    from app.models.profile import SiteCredential
    from app.models.user import User

    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    await SiteCredential(
        user_id=user.id,
        tenant_id=user.tenant_id,
        site_domain="lever.co",
        login_email=email,
        encrypted_password=encrypt_secret("top-secret"),
    ).insert()

    resp = await client.get("/api/v1/account/export", headers=_auth(tokens))
    assert resp.status_code == 200
    body = resp.text
    assert "hashed_password" not in body
    assert "encrypted_password" not in body
    assert "top-secret" not in body
    assert resp.json()["site_credentials"][0]["site_domain"] == "lever.co"


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------
async def test_negative_question_index_rejected(client):
    """`-1` used to pass the bounds check and score the LAST question."""
    from app.models.interview import InterviewSession
    from app.models.user import User

    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    session = InterviewSession(
        user_id=user.id,
        tenant_id=user.tenant_id,
        questions=[{"question": "q0", "type": "general"}],
    )
    await session.insert()

    resp = await client.post(
        f"/api/v1/interviews/{session.id}/answer",
        json={"question_index": -1, "answer": "attempted wrap-around"},
        headers=_auth(tokens),
    )
    assert resp.status_code == 422


async def test_interview_question_count_is_bounded(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post(
        "/api/v1/interviews",
        json={"question_count": 10_000},
        headers=_auth(tokens),
    )
    assert resp.status_code == 422


async def test_job_listing_limit_is_bounded(client):
    email = await _register(client)
    tokens = await _login(client, email)
    for bad in ("999999", "-1", "0"):
        resp = await client.get(
            f"/api/v1/jobs/available?limit={bad}", headers=_auth(tokens)
        )
        assert resp.status_code == 422, f"limit={bad} accepted"


async def test_job_search_treats_input_as_text_not_regex(client):
    """A regex metacharacter payload must not become a catastrophic pattern."""
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.get(
        "/api/v1/jobs/available",
        params={"search": "(a+)+$"},
        headers=_auth(tokens),
    )
    assert resp.status_code == 200


async def test_upload_rejects_non_document(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post(
        "/api/v1/onboarding/resume",
        files={"file": ("evil.pdf", b"<?php system($_GET[0]); ?>", "application/pdf")},
        headers=_auth(tokens),
    )
    # Declared as PDF but the bytes are not — magic-byte check must reject.
    assert resp.status_code == 415


async def test_upload_rejects_oversized_file(client):
    from app.core.config import settings

    email = await _register(client)
    tokens = await _login(client, email)
    payload = b"%PDF-1.4" + b"\x00" * (settings.MAX_UPLOAD_BYTES + 1024)
    resp = await client.post(
        "/api/v1/onboarding/resume",
        files={"file": ("big.pdf", payload, "application/pdf")},
        headers=_auth(tokens),
    )
    assert resp.status_code == 413


async def test_onboarding_step_rejects_unknown_value(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post(
        "/api/v1/onboarding/step",
        json={"step": "'; DROP COLLECTION users; --"},
        headers=_auth(tokens),
    )
    assert resp.status_code == 422


async def test_resume_strategy_rejects_unknown_value(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post(
        "/api/v1/onboarding/resume-strategy",
        json={"strategy": "exfiltrate"},
        headers=_auth(tokens),
    )
    assert resp.status_code == 422


async def test_application_status_transition_is_restricted(client):
    """A user must not be able to mark their own application as submitted."""
    from app.models.job import Job, JobApplication
    from app.models.user import User

    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    job = Job(
        fingerprint=uuid.uuid4().hex,
        source="lever",
        apply_url="https://jobs.lever.co/x/1",
        company="Acme",
        title="Engineer",
    )
    await job.insert()
    row = JobApplication(
        user_id=user.id, tenant_id=user.tenant_id, job_id=job.id, status="matched"
    )
    await row.insert()

    resp = await client.patch(
        f"/api/v1/jobs/applications/{row.id}",
        json={"status": "submitted"},
        headers=_auth(tokens),
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------
# Webhooks & billing
# --------------------------------------------------------------------------
async def test_stripe_webhook_rejects_unsigned_payload(client):
    resp = await client.post(
        "/api/v1/billing/webhook",
        content=b'{"id":"evt_forged","type":"checkout.session.completed"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


async def test_stripe_webhook_rejects_forged_signature(client):
    resp = await client.post(
        "/api/v1/billing/webhook",
        content=b'{"id":"evt_forged","type":"customer.subscription.updated"}',
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
    )
    assert resp.status_code == 400


async def test_checkout_requires_verified_email(client):
    email = await _register(client, verify=False)
    from app.models.user import User

    user = await User.find_one(User.email == email)
    user.is_email_verified = True
    await user.save()
    tokens = await _login(client, email)
    user.is_email_verified = False
    await user.save()

    resp = await client.post(
        "/api/v1/billing/checkout",
        json={"plan_code": "pro"},
        headers=_auth(tokens),
    )
    assert resp.status_code == 403


async def test_free_plan_cannot_be_checked_out(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post(
        "/api/v1/billing/checkout", json={"plan_code": "free"}, headers=_auth(tokens)
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------
# Response hygiene
# --------------------------------------------------------------------------
async def test_security_headers_present(client):
    resp = await client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "x-request-id" in resp.headers


async def test_validation_errors_are_human_readable_strings(client):
    """The frontend renders `detail` directly; an array showed as [object Object]."""
    resp = await client.post("/api/v1/auth/login", json={"email": "not-an-email"})
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str)
    assert resp.json()["detail"]


# --------------------------------------------------------------------------
# Credential reveal (re-authentication required)
# --------------------------------------------------------------------------
async def test_credential_reveal_requires_the_account_password(client):
    """A valid session alone must not be enough to read a stored secret."""
    email = await _register(client)
    tokens = await _login(client, email)
    created = await client.post(
        "/api/v1/onboarding/credentials",
        json={"site_domain": "boards.greenhouse.io", "login_email": email},
        headers=_auth(tokens),
    )
    cred_id = created.json()["id"]

    wrong = await client.post(
        f"/api/v1/onboarding/credentials/{cred_id}/reveal",
        json={"password": "not-the-right-password"},
        headers=_auth(tokens),
    )
    assert wrong.status_code == 403
    assert "password" not in wrong.text.lower() or "incorrect" in wrong.text.lower()

    right = await client.post(
        f"/api/v1/onboarding/credentials/{cred_id}/reveal",
        json={"password": PASSWORD},
        headers=_auth(tokens),
    )
    assert right.status_code == 200
    body = right.json()
    assert body["site_domain"] == "boards.greenhouse.io"
    assert body["password"], "a generated password should come back"


async def test_cannot_reveal_another_users_credential(client):
    from app.core.security import encrypt_secret
    from app.models.profile import SiteCredential
    from app.models.user import User

    victim_email = await _register(client)
    attacker_email = await _register(client)
    victim = await User.find_one(User.email == victim_email)
    cred = SiteCredential(
        user_id=victim.id,
        tenant_id=victim.tenant_id,
        site_domain="lever.co",
        login_email=victim_email,
        encrypted_password=encrypt_secret("victim-secret-value"),
    )
    await cred.insert()

    attacker_tokens = await _login(client, attacker_email)
    resp = await client.post(
        f"/api/v1/onboarding/credentials/{cred.id}/reveal",
        json={"password": PASSWORD},
        headers=_auth(attacker_tokens),
    )
    assert resp.status_code == 404
    assert "victim-secret-value" not in resp.text


async def test_reveal_is_unauthenticated_safe(client):
    resp = await client.post(
        f"/api/v1/onboarding/credentials/{uuid.uuid4()}/reveal",
        json={"password": PASSWORD},
    )
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Search cancellation
# --------------------------------------------------------------------------
async def test_match_status_and_cancel_require_auth(client):
    assert (await client.get("/api/v1/jobs/match/status")).status_code == 401
    assert (await client.post("/api/v1/jobs/match/cancel")).status_code == 401


async def test_cancel_with_no_running_search_is_not_an_error(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post("/api/v1/jobs/match/cancel", headers=_auth(tokens))
    assert resp.status_code == 200
    assert resp.json()["queued"] == 0
    assert "No search" in resp.json()["detail"]


async def test_match_status_reports_idle_by_default(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.get("/api/v1/jobs/match/status", headers=_auth(tokens))
    assert resp.status_code == 200
    assert resp.json()["running"] is False


# --------------------------------------------------------------------------
# Response shape
#
# These endpoints project straight out of Mongo for speed. A projection model
# is easy to get subtly wrong in two ways that no unit test on the model
# catches: it can fail to parse `_id` (500 on every request that returns rows),
# or it can serialise the field back out AS `_id`, leaving every `job.id` in
# the client undefined. Both shipped. Assert on the JSON the browser receives.
# --------------------------------------------------------------------------
async def test_available_jobs_returns_rows_with_a_usable_id(client):
    from app.models.job import Job

    email = await _register(client)
    tokens = await _login(client, email)
    job = Job(
        fingerprint=uuid.uuid4().hex,
        source="greenhouse",
        apply_url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme",
        title="Backend Engineer",
        location="Remote",
        description="x" * 5000,
        raw={"padding": "y" * 5000},
    )
    await job.insert()

    resp = await client.get("/api/v1/jobs/available?limit=50", headers=_auth(tokens))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert rows, "the pool has a job but the endpoint returned nothing"

    row = next((r for r in rows if r.get("id") == str(job.id)), None)
    assert row is not None, f"no row carried a usable `id`; keys were {sorted(rows[0])}"
    assert "_id" not in row, "the projection alias leaked into the response"
    # The point of projecting: the heavy fields must not travel.
    for heavy in ("raw", "description", "fingerprint"):
        assert heavy not in row, f"{heavy} should not be serialised to the client"


async def test_applications_embed_a_job_with_a_usable_id(client):
    """The same model is reused for the job embedded in an application."""
    from app.models.job import Job, JobApplication
    from app.models.user import User

    email = await _register(client)
    tokens = await _login(client, email)
    user = await User.find_one(User.email == email)
    job = Job(
        fingerprint=uuid.uuid4().hex,
        source="lever",
        apply_url="https://jobs.lever.co/acme/1",
        company="Acme",
        title="Staff Engineer",
        raw={"padding": "y" * 5000},
    )
    await job.insert()
    await JobApplication(
        user_id=user.id, tenant_id=user.tenant_id, job_id=job.id, status="matched"
    ).insert()
    # A row whose posting was purged must survive, with job=null — /stats counts
    # every application, so dropping it would make the two disagree.
    await JobApplication(
        user_id=user.id, tenant_id=user.tenant_id, job_id=uuid.uuid4(), status="matched"
    ).insert()

    resp = await client.get("/api/v1/jobs/applications", headers=_auth(tokens))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 2

    embedded = [r["job"] for r in rows if r.get("job")]
    assert len(embedded) == 1, "the application lost its job"
    assert embedded[0]["id"] == str(job.id)
    assert "_id" not in embedded[0]
    assert "raw" not in embedded[0]
    assert any(r.get("job") is None for r in rows), "a purged job dropped the row"
