"""Résumé tailoring pipeline: profile + job -> tailored markdown -> MinIO.

Generates a job-specific résumé for a JobApplication, stores it in object
storage, records a ResumeDocument(kind="tailored"), and links it back on the
application. DB access is async (Beanie), bridged from the sync Celery task
with ``app.workers.db.run_async``.
"""

from __future__ import annotations

import io
import uuid

from app.ai import prompts
from app.core.logging import get_logger
from app.models.job import Job, JobApplication
from app.models.profile import Profile, ResumeDocument
from app.services.resume_docx import DOCX_CONTENT_TYPE, markdown_to_docx
from app.services.storage import safe_filename, upload_fileobj
from app.workers.celery_app import celery
from app.workers.db import run_async

log = get_logger(__name__)


def _profile_dict(profile: Profile) -> dict:
    """Flatten a Profile into the shape prompts.tailor_resume expects."""
    return {
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "phone": profile.phone,
        "headline": profile.headline,
        "summary": profile.summary,
        "address": {
            "line1": profile.address_line1,
            "line2": profile.address_line2,
            "city": profile.city,
            "region": profile.region,
            "postal_code": profile.postal_code,
            "country": profile.country,
        },
        "skills": profile.skills or [],
        "work_history": profile.work_history or [],
        "education": profile.education or [],
        "certifications": profile.certifications or [],
    }


def _job_dict(job: Job) -> dict:
    return {
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "description": job.description or "",
    }


@celery.task(
    name="tailoring.tailor_for_application",
    bind=True,
    max_retries=2,
    acks_late=True,
)
def tailor_for_application(self, application_id: str) -> dict:
    try:
        return run_async(_tailor_async(application_id))
    except Exception as exc:  # noqa: BLE001
        log.error("tailor_failed", application_id=application_id, error=str(exc))
        try:
            raise self.retry(exc=exc, countdown=30)
        except self.MaxRetriesExceededError:
            # Tailoring is an enhancement: the apply engine falls back to the
            # user's base résumé, so a permanent failure is not fatal.
            return {"status": "failed"}


async def _tailor_async(application_id: str) -> dict:
    application = await JobApplication.get(uuid.UUID(application_id))
    if application is None:
        return {"status": "not_found"}

    job = await Job.get(application.job_id)
    profile = await Profile.find_one(Profile.user_id == application.user_id)
    if job is None or profile is None:
        log.error(
            "tailor_missing_inputs",
            application_id=application_id,
            has_job=job is not None,
            has_profile=profile is not None,
        )
        return {"status": "missing_inputs"}

    if (profile.resume_strategy or "same") != "tailored":
        return {"status": "skipped", "reason": "strategy_not_tailored"}

    markdown = prompts.tailor_resume(_profile_dict(profile), _job_dict(job))
    if not (markdown or "").strip():
        return {"status": "failed", "reason": "empty_output"}

    tenant_id = application.tenant_id
    # .docx, not .md — this is the file the apply engine attaches to the
    # employer's résumé field, and those reject markdown. See services/resume_docx.
    data = markdown_to_docx(markdown)
    key = f"{tenant_id}/resumes/tailored-{uuid.uuid4()}.docx"
    upload_fileobj(io.BytesIO(data), key, DOCX_CONTENT_TYPE)
    # Keep the extension intact when the company/title make the name long.
    stem = safe_filename(f"tailored-{job.company}-{job.title}", "tailored-resume")
    filename = f"{stem[:92]}.docx"

    document = ResumeDocument(
        tenant_id=tenant_id,
        user_id=application.user_id,
        kind="tailored",
        filename=filename,
        storage_key=key,
        content_type=DOCX_CONTENT_TYPE,
        extracted_text=markdown,
        size_bytes=len(data),
        parse_status="done",
    )
    await document.insert()

    application.resume_document_id = document.id
    application.touch()
    await application.save()
    log.info(
        "resume_tailored",
        application_id=application_id,
        resume_id=str(document.id),
    )
    return {"status": "done", "resume_document_id": str(document.id)}
