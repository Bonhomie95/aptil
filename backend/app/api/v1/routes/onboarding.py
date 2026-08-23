"""Resumable onboarding wizard + profile management.

Every step autosaves to the Profile so a returning user resumes exactly where they
left off, with prior answers prefilled (spec point 3).
"""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.core.security import encrypt_secret, generate_site_password
from app.models.enums import OnboardingStep
from app.models.profile import Demographics, Profile, ResumeDocument, SiteCredential
from app.models.user import User
from app.schemas.onboarding import (
    CredentialRead,
    CredentialRequest,
    OnboardingState,
    ProfileRead,
    ProfileUpdate,
    ResumeRead,
    ResumeStrategyRequest,
    SetStepRequest,
)
from app.services import storage
from app.services.auth_service import ensure_profile

router = APIRouter()
log = get_logger(__name__)

# Ordered wizard steps. The frontend renders exactly this list, so a step can
# never exist server-side without a screen to render it.
STEP_ORDER = [
    OnboardingStep.CV_UPLOAD.value,
    OnboardingStep.PERSONAL_DETAILS.value,
    OnboardingStep.JOB_HISTORY.value,
    OnboardingStep.JOB_TARGETS.value,
    OnboardingStep.RESUME_STRATEGY.value,
    OnboardingStep.VOLUNTARY_DISCLOSURES.value,
    OnboardingStep.CREDENTIALS.value,
    OnboardingStep.PLAN_SELECTION.value,
]

ALLOWED_CV_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    # Some browsers send a generic type for .docx; the magic-byte check below is
    # what actually decides.
    "application/octet-stream": "",
}
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}

# Magic bytes: %PDF for PDF, PK.. for the zip container behind .docx,
# and the OLE2 signature for legacy .doc.
_MAGIC = {
    b"%PDF": "application/pdf",
    b"PK\x03\x04": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    b"\xd0\xcf\x11\xe0": "application/msword",
}


def _sniff_content_type(head: bytes) -> str | None:
    for magic, ctype in _MAGIC.items():
        if head.startswith(magic):
            return ctype
    return None


async def _latest_resume(user: User) -> ResumeDocument | None:
    return await ResumeDocument.find(
        ResumeDocument.user_id == user.id,
        ResumeDocument.kind == "uploaded",
    ).sort(-ResumeDocument.created_at).first_or_none()


async def _discard_superseded_resumes(user: User, keep: uuid.UUID) -> None:
    """Delete the user's older uploaded CVs, bytes included.

    Only ``kind == "uploaded"``. Tailored résumés are per-application artifacts
    and are what an employer actually received, so they are never touched here.

    A job application may still point at a document this removes; that is
    handled where it matters — ``ats.base.resolve_resume_path`` falls back to
    the newest upload when the linked document has gone, so a stale link
    degrades to "apply with the current CV" rather than "apply with none".
    """
    superseded = await ResumeDocument.find(
        ResumeDocument.user_id == user.id,
        ResumeDocument.kind == "uploaded",
        ResumeDocument.id != keep,
    ).to_list()
    for old in superseded:
        # Object first: a delete that fails leaves the row, so the next upload
        # tries again. Dropping the row first would orphan the bytes forever.
        storage.delete_object(old.storage_key)
        await old.delete()
    if superseded:
        log.info("resumes_superseded", user_id=str(user.id), count=len(superseded))


async def _state(user: User, profile: Profile | None = None) -> OnboardingState:
    profile = profile or await ensure_profile(user)
    resume = await _latest_resume(user)
    return OnboardingState(
        step=user.onboarding_step,
        completed=user.onboarding_completed,
        profile=ProfileRead.model_validate(profile),
        has_resume=resume is not None,
        resume_parse_status=resume.parse_status if resume else None,
        resume_parse_error=resume.parse_error if resume else None,
        steps=STEP_ORDER,
    )


@router.get("/state", response_model=OnboardingState)
async def get_state(user: User = Depends(get_current_user)):
    return await _state(user)


@router.put("/profile", response_model=ProfileRead)
async def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
):
    profile = await ensure_profile(user)
    # A field the user actually changed stops being ours, so a later CV parse
    # will not overwrite their answer. Compared by VALUE, not by presence: the
    # wizard re-sends every field on each step, so treating "sent" as "edited"
    # would drop provenance on the whole profile at the first Continue click.
    ours = set(profile.autofilled_fields)
    sent = payload.model_dump(exclude_unset=True)

    # `demographics` is a nested object and must be MERGED, not replaced.
    # model_dump(exclude_unset=True) recurses, so `sent["demographics"]` holds
    # only the answers this request actually carried — assigning it wholesale
    # would wipe every EEO answer the user had given on an earlier step.
    demographics = sent.pop("demographics", None)
    if demographics is not None:
        current = profile.demographics.model_dump()
        current.update(demographics)
        profile.demographics = Demographics(**current)

    for field, value in sent.items():
        if field in ours and value != getattr(profile, field, None):
            ours.discard(field)
        setattr(profile, field, value)
    profile.autofilled_fields = sorted(ours)
    profile.touch()
    await profile.save()

    # New targets mean the old pool slice is stale — fetch for them right away,
    # but only once onboarding is done (mid-wizard the CV-parse hook covers it).
    if "target_titles" in sent and user.onboarding_completed:
        try:
            from app.workers.tasks.sourcing import source_for_user

            source_for_user.delay(str(user.id))
        except Exception as exc:  # noqa: BLE001 - broker down; sweep catches up
            log.warning("target_change_sourcing_skipped", error=str(exc))
    return profile


@router.get("/resumes", response_model=list[ResumeRead])
async def list_resumes(user: User = Depends(get_current_user)):
    """Every résumé the user owns, uploaded or generated, with download links."""
    docs = await ResumeDocument.find(
        ResumeDocument.user_id == user.id
    ).sort(-ResumeDocument.created_at).to_list()
    out: list[ResumeRead] = []
    for doc in docs:
        item = ResumeRead.model_validate(doc)
        try:
            item.download_url = storage.presigned_get_url(
                doc.storage_key, filename=doc.filename
            )
        except Exception as exc:  # noqa: BLE001 - a link is a nice-to-have
            log.warning("presign_failed", resume_id=str(doc.id), error=str(exc))
        out.append(item)
    return out


@router.post(
    "/resume",
    response_model=OnboardingState,
    status_code=201,
    dependencies=[Depends(RateLimiter(times=10, seconds=300, scope="user"))],
)
async def upload_resume(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    declared = (file.content_type or "").split(";")[0].strip().lower()
    extension = ("." + (file.filename or "").rsplit(".", 1)[-1].lower()) if "." in (
        file.filename or ""
    ) else ""

    if declared not in ALLOWED_CV_TYPES and extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a PDF or Word document (.pdf, .doc, .docx)",
        )

    # Read with a hard ceiling: never buffer an unbounded request body.
    limit = settings.MAX_UPLOAD_BYTES
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is too large (limit {limit // (1024 * 1024)} MB)",
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File is empty"
        )

    # Trust the bytes, not the client-declared type.
    sniffed = _sniff_content_type(data[:8])
    if sniffed is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="That file isn't a readable PDF or Word document",
        )
    content_type = sniffed

    # Import here to avoid pulling storage/celery into request import path at boot.
    from app.workers.tasks.cv_parsing import parse_resume_document

    # The profile must exist BEFORE the parse task runs, or the worker finds no
    # profile and silently discards everything it extracted.
    profile = await ensure_profile(user)

    key = storage.build_object_key(user.tenant_id, "resumes", file.filename)
    storage.upload_fileobj(io.BytesIO(data), key, content_type)

    doc = ResumeDocument(
        user_id=user.id,
        tenant_id=user.tenant_id,
        kind="uploaded",
        filename=storage.safe_filename(file.filename, "resume"),
        storage_key=key,
        content_type=content_type,
        size_bytes=len(data),
        parse_status="pending",
    )
    await doc.insert()
    # An upload REPLACES the CV; it does not add another one. Done after the
    # insert, never before: for the moment in between, `has_resume` must not go
    # false and the apply engine must not find itself with nothing to attach.
    await _discard_superseded_resumes(user, keep=doc.id)

    # Background: extract text -> LLM parse -> populate profile (spec point 4).
    try:
        parse_resume_document.delay(str(doc.id))
    except Exception as exc:  # noqa: BLE001 - broker down shouldn't lose the upload
        log.error("cv_parse_enqueue_failed", resume_id=str(doc.id), error=str(exc))
        doc.parse_status = "failed"
        doc.parse_error = "Could not queue parsing. Fill your details manually."
        await doc.save()

    return await _state(user, profile)


@router.post(
    "/build-resume",
    response_model=OnboardingState,
    status_code=201,
    dependencies=[Depends(RateLimiter(times=10, seconds=300, scope="user"))],
)
async def build_resume(user: User = Depends(get_current_user)):
    """Generate a résumé from the user's profile for those without a CV.

    Deterministic build (no AI key required); stored like an uploaded résumé so the
    rest of the flow (apply engine, tailoring) treats it the same.
    """
    from app.services.resume_builder import build_markdown, has_minimum_content
    from app.services.resume_docx import DOCX_CONTENT_TYPE, markdown_to_docx

    profile = await ensure_profile(user)
    if not has_minimum_content(profile):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Add your name plus at least one role, skill, or summary before "
                "generating a résumé."
            ),
        )

    markdown = build_markdown(profile)
    # .docx, not .md: this file is attached to real ATS résumé fields, which
    # accept pdf/doc/docx/txt and reject markdown outright. The markdown is
    # still kept as `extracted_text` — that is what matching and tailoring read.
    data = markdown_to_docx(markdown)
    key = storage.build_object_key(user.tenant_id, "resumes", "aptil-resume.docx")
    storage.upload_bytes(data, key, DOCX_CONTENT_TYPE)

    doc = ResumeDocument(
        user_id=user.id,
        tenant_id=user.tenant_id,
        kind="uploaded",
        filename="aptil-resume.docx",
        storage_key=key,
        content_type=DOCX_CONTENT_TYPE,
        size_bytes=len(data),
        extracted_text=markdown,
        parse_status="done",
    )
    await doc.insert()
    # Same invariant as an upload: one current CV. Regenerating otherwise stacks
    # near-identical files that the user cannot tell apart in the résumé list.
    await _discard_superseded_resumes(user, keep=doc.id)
    return await _state(user, profile)


@router.post("/step", response_model=OnboardingState)
async def set_step(
    payload: SetStepRequest,
    user: User = Depends(get_current_user),
):
    valid = {s.value for s in OnboardingStep}
    if payload.step not in valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid step. One of {sorted(valid)}",
        )

    user.onboarding_step = payload.step
    # Completion is a two-way flag: stepping back into the wizard reopens it,
    # rather than leaving a stale "completed" that skips the remaining screens.
    user.onboarding_completed = payload.step == OnboardingStep.COMPLETED.value
    user.touch()
    await user.save()
    return await _state(user)


@router.post("/resume-strategy", response_model=ProfileRead)
async def set_resume_strategy(
    payload: ResumeStrategyRequest,
    user: User = Depends(get_current_user),
):
    profile = await ensure_profile(user)
    profile.resume_strategy = payload.strategy
    profile.touch()
    await profile.save()
    return profile


# --------------------------------------------------------------------------- #
# Site credentials (consent-based apply)
# --------------------------------------------------------------------------- #
@router.get("/credentials", response_model=list[CredentialRead])
async def list_credentials(user: User = Depends(get_current_user)):
    """List stored site credentials. Secrets are never returned."""
    creds = await SiteCredential.find(SiteCredential.user_id == user.id).to_list()
    return [
        CredentialRead(
            id=c.id,
            site_domain=c.site_domain,
            login_email=c.login_email,
            has_password=bool(c.encrypted_password),
        )
        for c in creds
    ]


@router.post("/credentials", response_model=CredentialRead, status_code=201)
async def add_credential(
    payload: CredentialRequest,
    user: User = Depends(get_current_user),
):
    """Store an ENCRYPTED, per-site credential for consent-based ATS apply.

    Password is unique per site and never stored in plaintext. If the user does not
    supply one, we generate a strong unique password for that site. Re-submitting
    the same domain updates the existing entry instead of stacking duplicates.
    """
    raw_password = payload.password or generate_site_password()
    existing = await SiteCredential.find_one(
        SiteCredential.user_id == user.id,
        SiteCredential.site_domain == payload.site_domain,
    )
    if existing is not None:
        existing.login_email = payload.login_email.lower()
        existing.encrypted_password = encrypt_secret(raw_password)
        existing.touch()
        await existing.save()
        cred = existing
    else:
        cred = SiteCredential(
            user_id=user.id,
            tenant_id=user.tenant_id,
            site_domain=payload.site_domain,
            login_email=payload.login_email.lower(),
            encrypted_password=encrypt_secret(raw_password),
        )
        try:
            await cred.insert()
        except DuplicateKeyError:
            cred = await SiteCredential.find_one(
                SiteCredential.user_id == user.id,
                SiteCredential.site_domain == payload.site_domain,
            )
            if cred is None:  # pragma: no cover - defensive
                raise
    return CredentialRead(
        id=cred.id,
        site_domain=cred.site_domain,
        login_email=cred.login_email,
        has_password=True,
    )


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: uuid.UUID,
    user: User = Depends(get_current_user),
):
    cred = await SiteCredential.find_one(
        SiteCredential.id == credential_id,
        SiteCredential.user_id == user.id,
    )
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    await cred.delete()
    return None
