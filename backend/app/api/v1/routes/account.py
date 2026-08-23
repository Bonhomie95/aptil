"""Account self-service: data export and account deletion.

`docs/compliance.md` §5 requires an export path and a deletion path for the
personal data we hold (CVs, profiles, application history). These implement both
for the authenticated caller, scoped strictly to their own tenant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.core.security import verify_password
from app.models.billing import Subscription
from app.models.interview import InterviewSession
from app.models.job import Job, JobApplication
from app.models.profile import Profile, ResumeDocument, SiteCredential
from app.models.tenant import Tenant
from app.models.user import EmailVerificationToken, RefreshSession, User
from app.services import storage

router = APIRouter()
log = get_logger(__name__)


class DeleteAccountRequest(BaseModel):
    # Password is required for local accounts; OAuth-only accounts confirm by
    # typing their email instead.
    password: str | None = Field(default=None, max_length=128)
    confirm_email: str | None = Field(default=None, max_length=320)


def _dump(doc: Any, drop: set[str]) -> dict:
    data = doc.model_dump(mode="json")
    for key in drop:
        data.pop(key, None)
    return data


@router.get(
    "/export",
    dependencies=[Depends(RateLimiter(times=3, seconds=3600, scope="user"))],
)
async def export_my_data(user: User = Depends(get_current_user)) -> dict:
    """Everything we hold for this account, as JSON.

    Secrets are excluded by design: the password hash and the encrypted site
    credentials are not personal data the user needs back, and returning them
    would only widen the blast radius of a leaked export.
    """
    profile = await Profile.find_one(Profile.user_id == user.id)
    resumes = await ResumeDocument.find(ResumeDocument.user_id == user.id).to_list()
    credentials = await SiteCredential.find(SiteCredential.user_id == user.id).to_list()
    applications = await JobApplication.find(
        JobApplication.user_id == user.id
    ).to_list()
    interviews = await InterviewSession.find(
        InterviewSession.user_id == user.id
    ).to_list()
    subscriptions = await Subscription.find(
        Subscription.tenant_id == user.tenant_id
    ).to_list()

    job_ids = list({a.job_id for a in applications})
    jobs = await Job.find({"_id": {"$in": job_ids}}).to_list() if job_ids else []
    jobs_by_id = {j.id: j for j in jobs}

    resume_entries = []
    for doc in resumes:
        entry = _dump(doc, {"extracted_text"})
        try:
            entry["download_url"] = storage.presigned_get_url(
                doc.storage_key, expires=3600, filename=doc.filename
            )
        except Exception:  # noqa: BLE001 - export should not fail on storage
            entry["download_url"] = None
        resume_entries.append(entry)

    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": _dump(user, {"hashed_password", "token_version"}),
        # autofilled_fields records which values we wrote vs the user typed —
        # internal merge bookkeeping, not personal data they asked us to hold.
        "profile": _dump(profile, {"autofilled_fields"}) if profile else None,
        "resumes": resume_entries,
        # Domain + login only; the encrypted secret stays server-side.
        "site_credentials": [
            {"site_domain": c.site_domain, "login_email": c.login_email}
            for c in credentials
        ],
        "applications": [
            {
                **_dump(a, set()),
                "job": _dump(jobs_by_id[a.job_id], {"raw"})
                if a.job_id in jobs_by_id
                else None,
            }
            for a in applications
        ],
        "interviews": [_dump(i, set()) for i in interviews],
        "subscriptions": [_dump(s, set()) for s in subscriptions],
    }


@router.delete(
    "",
    status_code=204,
    dependencies=[Depends(RateLimiter(times=5, seconds=3600, scope="user"))],
)
async def delete_my_account(
    payload: DeleteAccountRequest,
    user: User = Depends(get_current_user),
):
    """Permanently delete the account and every record attached to it."""
    if user.hashed_password:
        if not payload.password or not verify_password(
            payload.password, user.hashed_password
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is incorrect",
            )
    else:
        # OAuth-only account: confirm by typing the account email.
        if (payload.confirm_email or "").strip().lower() != user.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Type your account email to confirm deletion",
            )

    # Remove stored objects first: a dangling DB row is recoverable, an
    # unreferenced CV sitting in object storage is not.
    resumes = await ResumeDocument.find(ResumeDocument.user_id == user.id).to_list()
    for doc in resumes:
        storage.delete_object(doc.storage_key)

    await ResumeDocument.find(ResumeDocument.user_id == user.id).delete()
    await SiteCredential.find(SiteCredential.user_id == user.id).delete()
    await JobApplication.find(JobApplication.user_id == user.id).delete()
    await InterviewSession.find(InterviewSession.user_id == user.id).delete()
    await Profile.find(Profile.user_id == user.id).delete()
    await EmailVerificationToken.find(
        EmailVerificationToken.user_id == user.id
    ).delete()
    await RefreshSession.find(RefreshSession.user_id == user.id).delete()
    await Subscription.find(Subscription.tenant_id == user.tenant_id).delete()

    tenant_id = user.tenant_id
    await user.delete()
    tenant = await Tenant.get(tenant_id)
    if tenant is not None:
        await tenant.delete()

    log.info("account_deleted", user_id=str(user.id), tenant_id=str(tenant_id))
    return None


class AutoCreateRequest(BaseModel):
    enabled: bool


@router.post("/auto-create-accounts")
async def set_auto_create_accounts(
    payload: AutoCreateRequest,
    user: User = Depends(get_current_user),
):
    """Consent switch for creating job-site accounts with the managed alias."""
    user.auto_create_accounts = payload.enabled
    user.touch()
    await user.save()
    return {"enabled": user.auto_create_accounts}
