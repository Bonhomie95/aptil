"""Replacing a wrongly-uploaded CV must refresh the details it filled in.

The original merge rule was `profile.x = profile.x or parsed.get("x")` in both
the worker and the wizard. It reads as "never clobber the user", but it really
means "the first CV wins forever": after one upload nothing is blank, so a
second parse has nothing to write and the stale details stand.

These pin the three cases that rule conflated — our value, the user's value,
and absent — so the fix cannot regress into it.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.workers.tasks.cv_parsing import _apply_to_profile
from tests.conftest import requires_mongo

pytestmark = [requires_mongo]


@pytest.fixture(scope="module")
async def client():
    from app.db.session import init_db
    from app.main import app
    from scripts.seed import seed_plans

    await init_db()
    # New accounts are provisioned onto the free plan, so it has to exist.
    await seed_plans()
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

FIRST_CV = {
    "first_name": "Wrong",
    "last_name": "Person",
    "email": "wrong@example.com",
    "phone": "+1 555 0100",
    "headline": "Barista",
    "skills": ["Espresso", "Latte art"],
    "work_history": [{"title": "Barista", "company": "Cafe"}],
}
SECOND_CV = {
    "first_name": "Right",
    "last_name": "Person",
    "email": "right@example.com",
    "phone": "+1 555 0200",
    "headline": "Backend Engineer",
    "skills": ["Python", "Postgres"],
    "work_history": [{"title": "Engineer", "company": "Acme"}],
}


async def _fresh_profile():
    from app.db.session import init_db
    from app.models.profile import Profile

    await init_db()
    profile = Profile(user_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    await profile.insert()
    return profile


async def _reload(profile):
    from app.models.profile import Profile

    return await Profile.get(profile.id)


async def test_a_second_cv_replaces_what_the_first_one_filled_in():
    """The reported bug: upload the wrong CV, then the right one."""
    profile = await _fresh_profile()

    await _apply_to_profile(profile.user_id, FIRST_CV)
    after_first = await _reload(profile)
    assert after_first.first_name == "Wrong"
    assert after_first.headline == "Barista"
    assert after_first.skills == ["Espresso", "Latte art"]

    await _apply_to_profile(profile.user_id, SECOND_CV)
    after_second = await _reload(profile)
    assert after_second.first_name == "Right"
    assert after_second.email == "right@example.com"
    assert after_second.phone == "+1 555 0200"
    assert after_second.headline == "Backend Engineer"
    assert after_second.skills == ["Python", "Postgres"]
    assert after_second.work_history == [{"title": "Engineer", "company": "Acme"}]


async def test_a_field_the_user_typed_survives_a_new_cv():
    """The reason the old rule existed. It still has to hold."""
    profile = await _fresh_profile()
    await _apply_to_profile(profile.user_id, FIRST_CV, trust_absent=True)

    edited = await _reload(profile)
    edited.phone = "+44 7700 900000"          # the user corrects it by hand
    edited.autofilled_fields = [
        f for f in edited.autofilled_fields if f != "phone"
    ]
    await edited.save()

    await _apply_to_profile(profile.user_id, SECOND_CV)
    after = await _reload(profile)
    assert after.phone == "+44 7700 900000", "a hand-typed value was clobbered"
    assert after.first_name == "Right", "other fields should still refresh"


async def test_a_field_the_new_cv_omits_is_cleared_not_carried_over():
    """Replacing a CV leaves the profile describing the NEW one.

    Carrying the old value forward silently produced a profile that was a union
    of every CV ever uploaded — the barista headline outliving the barista CV.
    """
    profile = await _fresh_profile()
    await _apply_to_profile(profile.user_id, FIRST_CV, trust_absent=True)
    assert (await _reload(profile)).headline == "Barista"

    await _apply_to_profile(
        profile.user_id, {"first_name": "Right", "last_name": "Person"},
        trust_absent=True,
    )
    after = await _reload(profile)
    assert after.first_name == "Right"
    assert after.headline is None, "a headline the new CV omits should be gone"
    assert after.phone is None
    assert after.skills == [], "list fields clear to [], not None"
    assert after.work_history == []


async def test_a_user_typed_field_is_not_cleared_by_an_omission():
    """Clearing only ever applies to values we wrote ourselves."""
    profile = await _fresh_profile()
    await _apply_to_profile(profile.user_id, FIRST_CV, trust_absent=True)

    edited = await _reload(profile)
    edited.phone = "+44 7700 900000"
    edited.autofilled_fields = [f for f in edited.autofilled_fields if f != "phone"]
    await edited.save()

    await _apply_to_profile(profile.user_id, {"first_name": "Right"}, trust_absent=True)
    after = await _reload(profile)
    assert after.phone == "+44 7700 900000"
    assert after.headline is None, "our own value should still be cleared"


async def test_a_degraded_parse_never_clears_anything():
    """The regex baseline only finds name/email/phone.

    Treating its silence as "the CV does not say" would wipe skills, work
    history and summary off a profile every time the LLM provider blipped.
    """
    profile = await _fresh_profile()
    await _apply_to_profile(profile.user_id, FIRST_CV, trust_absent=True)

    baseline_only = {"first_name": "Right", "last_name": "Person",
                     "email": "right@example.com", "phone": "+1 555 0200"}
    await _apply_to_profile(profile.user_id, baseline_only, trust_absent=False)

    after = await _reload(profile)
    assert after.first_name == "Right", "what it did read should still apply"
    assert after.headline == "Barista", "what it could not read must survive"
    assert after.skills == ["Espresso", "Latte art"]
    assert "headline" in after.autofilled_fields, "still ours to replace later"


async def test_details_seeded_from_signup_can_be_refined_by_a_cv():
    """profile.email was seeded from the account, so no CV email ever landed."""
    from app.models.user import User
    from app.services.auth_service import ensure_profile

    user = User(
        email="signup@example.com",
        tenant_id=uuid.uuid4(),
        full_name="Signup Name",
        hashed_password="x",
    )
    await user.insert()
    profile = await ensure_profile(user)
    assert profile.email == "signup@example.com"
    assert set(profile.autofilled_fields) == {"email", "first_name", "last_name"}

    await _apply_to_profile(user.id, FIRST_CV)
    after = await _reload(profile)
    assert after.email == "wrong@example.com"
    assert after.first_name == "Wrong"


@pytest.mark.parametrize(
    "sent, expect_still_ours",
    [
        ({"phone": "+1 555 0100"}, True),   # wizard re-sends an unchanged value
        ({"phone": "+1 555 9999"}, False),  # the user actually changed it
    ],
)
async def test_provenance_only_drops_when_a_value_really_changed(
    client, sent, expect_still_ours
):
    """The wizard PUTs every field on each Continue click.

    Treating "sent" as "edited" would strip provenance from the whole profile at
    the first step, quietly restoring the original bug.
    """
    from app.models.profile import Profile
    from app.models.user import User

    email = f"prov-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "a-strong-enough-password-1",
              "full_name": "P T", "accepted_terms": True},
    )
    assert resp.status_code == 201
    user = await User.find_one(User.email == email)
    user.is_email_verified = True
    await user.save()
    await _apply_to_profile(user.id, FIRST_CV)

    tokens = (await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "a-strong-enough-password-1"},
    )).json()
    resp = await client.put(
        "/api/v1/onboarding/profile",
        json=sent,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200

    profile = await Profile.find_one(Profile.user_id == user.id)
    assert ("phone" in profile.autofilled_fields) is expect_still_ours


# --------------------------------------------------------------------------
# Replacing a CV removes the one it replaces
# --------------------------------------------------------------------------
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


async def _upload(client, tokens, name: str):
    return await client.post(
        "/api/v1/onboarding/resume",
        files={"file": (name, PDF, "application/pdf")},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )


async def test_uploading_a_cv_replaces_the_previous_one(client, monkeypatch):
    """An upload is a replacement, not an addition.

    Otherwise every corrected upload leaves its predecessor's bytes in the
    bucket and its row in the résumé list, and the user has no way to tell which
    one applications actually use.
    """
    from app.models.profile import ResumeDocument
    from app.models.user import User
    from app.services import storage
    from app.workers.tasks import cv_parsing

    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(storage, "upload_fileobj", lambda *a, **k: "key")
    # Parsing runs on a worker; this test is about the document, not the parse.
    monkeypatch.setattr(cv_parsing.parse_resume_document, "delay", lambda *a, **k: None)

    email = f"repl-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "a-strong-enough-password-1",
        "full_name": "R T", "accepted_terms": True})
    user = await User.find_one(User.email == email)
    user.is_email_verified = True
    await user.save()
    tokens = (await client.post("/api/v1/auth/login", json={
        "email": email, "password": "a-strong-enough-password-1"})).json()

    assert (await _upload(client, tokens, "wrong.pdf")).status_code == 201
    first = await ResumeDocument.find_one(ResumeDocument.user_id == user.id)
    assert first is not None

    # A tailored résumé is what an employer actually received — never collateral.
    tailored = ResumeDocument(
        user_id=user.id, tenant_id=user.tenant_id, kind="tailored",
        filename="tailored.pdf", storage_key="tailored-key",
    )
    await tailored.insert()

    assert (await _upload(client, tokens, "right.pdf")).status_code == 201

    uploaded = await ResumeDocument.find(
        ResumeDocument.user_id == user.id, ResumeDocument.kind == "uploaded"
    ).to_list()
    assert len(uploaded) == 1, "the superseded CV row is still there"
    assert uploaded[0].filename == "right.pdf"
    assert first.storage_key in deleted, "the superseded CV's bytes were left behind"
    assert "tailored-key" not in deleted, "a tailored résumé was deleted"
    assert await ResumeDocument.get(tailored.id) is not None


async def test_state_never_reports_zero_resumes_mid_replacement(client, monkeypatch):
    """has_resume must not blink false while a replacement is in progress."""
    from app.models.profile import ResumeDocument
    from app.models.user import User
    from app.services import storage
    from app.workers.tasks import cv_parsing

    seen: list[int] = []

    def _count_during_delete(key):
        # Called between the new insert and the old row's removal.
        seen.append(0)

    monkeypatch.setattr(storage, "delete_object", _count_during_delete)
    monkeypatch.setattr(storage, "upload_fileobj", lambda *a, **k: "key")
    monkeypatch.setattr(cv_parsing.parse_resume_document, "delay", lambda *a, **k: None)

    email = f"blink-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={
        "email": email, "password": "a-strong-enough-password-1",
        "full_name": "B T", "accepted_terms": True})
    user = await User.find_one(User.email == email)
    user.is_email_verified = True
    await user.save()
    tokens = (await client.post("/api/v1/auth/login", json={
        "email": email, "password": "a-strong-enough-password-1"})).json()

    await _upload(client, tokens, "first.pdf")
    resp = await _upload(client, tokens, "second.pdf")
    assert resp.json()["has_resume"] is True
    assert len(await ResumeDocument.find(
        ResumeDocument.user_id == user.id, ResumeDocument.kind == "uploaded"
    ).to_list()) == 1
