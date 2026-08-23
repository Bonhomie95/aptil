"""CV parsing pipeline: extract text -> LLM parse -> populate profile (spec point 4)."""

from __future__ import annotations

import io
import re
import uuid

from app.ai import prompts
from app.core.logging import get_logger
from app.services.storage import download_bytes
from app.workers.celery_app import celery
from app.workers.db import run_async

log = get_logger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")


def _regex_extract(text: str) -> dict:
    """Deterministic baseline extraction — works with no AI key configured."""
    out: dict = {}
    if m := _EMAIL_RE.search(text):
        out["email"] = m.group(0)
    if p := _PHONE_RE.search(text):
        out["phone"] = re.sub(r"\s+", " ", p.group(0)).strip()
    # Name: first clean line of 2–4 alphabetic words, no digits/@.
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "@" in line or any(ch.isdigit() for ch in line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[:1].isalpha() for w in words):
            out["first_name"] = words[0]
            out["last_name"] = " ".join(words[1:])
            break
    return out


def _clean_str_list(value: object, limit: int = 200) -> list[str]:
    """Model output is untrusted shape — coerce to a list of short strings."""
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()[:80]
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _is_blank(value: object) -> bool:
    """Empty for merge purposes: unset, empty string, or empty list."""
    return value is None or value == "" or (isinstance(value, list) and not value)


def _blank_like(value: object) -> object:
    """The empty value for whatever shape this field holds."""
    return [] if isinstance(value, list) else None


def _clean_dict_list(value: object, limit: int = 50) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)][:limit]


def _extract_text(data: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if "word" in content_type or content_type.endswith("document"):
        import docx

        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    return data.decode("utf-8", errors="ignore")


@celery.task(
    name="cv.parse_resume_document",
    bind=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
)
def parse_resume_document(self, resume_document_id: str) -> dict:
    try:
        return run_async(_parse_async(resume_document_id))
    except _ParseNotFound:
        return {"status": "not_found"}
    except Exception as exc:  # noqa: BLE001
        log.error("cv_parse_failed", resume_id=resume_document_id, error=str(exc))
        try:
            raise self.retry(exc=exc, countdown=10)
        except self.MaxRetriesExceededError:
            # Out of retries: mark it failed so the UI stops waiting on a
            # status that would otherwise stay "pending" forever.
            run_async(
                _mark_failed(
                    resume_document_id,
                    "We couldn't read this file. Please fill your details manually.",
                )
            )
            return {"status": "failed"}


async def _mark_failed(resume_document_id: str, message: str) -> None:
    from app.models.profile import ResumeDocument

    try:
        doc = await ResumeDocument.get(uuid.UUID(resume_document_id))
    except (ValueError, TypeError):
        return
    if doc is None:
        return
    doc.parse_status = "failed"
    doc.parse_error = message
    doc.touch()
    await doc.save()


class _ParseNotFound(Exception):
    """Internal sentinel: résumé document row is missing (do not retry)."""


async def _parse_async(resume_document_id: str) -> dict:
    from app.models.profile import ResumeDocument

    doc = await ResumeDocument.get(uuid.UUID(resume_document_id))
    if doc is None:
        raise _ParseNotFound

    # Text extraction is required; a failure here is a real error (retry).
    try:
        data = download_bytes(doc.storage_key)
        text = _extract_text(data, doc.content_type)
    except Exception:
        doc.parse_status = "failed"
        doc.parse_error = "We couldn't read this file."
        doc.touch()
        await doc.save()
        raise

    if not (text or "").strip():
        # A scanned/image-only PDF yields no text. That is a real outcome, not a
        # transient error, so record it instead of burning retries.
        doc.parse_status = "failed"
        doc.parse_error = (
            "No readable text found (is this a scanned image?). "
            "Please fill your details manually."
        )
        doc.touch()
        await doc.save()
        return {"status": "failed", "reason": "no_text"}

    # Keep the stored text bounded; the LLM only sees the first slice anyway.
    doc.extracted_text = text[:200_000]

    # Deterministic baseline first (name/email/phone) — always available.
    merged = _regex_extract(text)
    # AI structuring on top (skills, work history, summary, ...) when a provider
    # key is configured. Best-effort: if it fails, we still prefill the baseline.
    ai_ok = False
    try:
        parsed = prompts.parse_cv(text)
        for key, value in parsed.items():
            if value:  # AI value wins where present
                merged[key] = value
        ai_ok = True
    except Exception as exc:  # noqa: BLE001 - keep the baseline result
        log.warning("cv_llm_parse_skipped", resume_id=resume_document_id, error=str(exc))

    await _apply_to_profile(doc.user_id, merged, trust_absent=ai_ok)
    doc.parse_status = "done"
    doc.parse_error = None
    doc.touch()
    await doc.save()
    log.info("cv_parsed", resume_id=resume_document_id, ai=ai_ok)

    # The CV just told us what this person does — immediately fetch jobs for it
    # rather than making them wait for the next half-hourly sweep of a pool
    # that may hold nothing in their field.
    try:
        from app.workers.tasks.sourcing import source_for_user

        source_for_user.delay(str(doc.user_id))
    except Exception as exc:  # noqa: BLE001 - broker down; sweep will catch up
        log.warning("post_parse_sourcing_skipped", error=str(exc))
    return {"status": "done"}


def _suggest_target_titles(parsed: dict) -> list[str]:
    """A starting guess at the roles the user wants, from their CV.

    Matching needs a target title to be any good, but making people type one is
    the kind of blank box that gets skipped — and a skipped target means we fall
    back to guessing from work history, which is the behaviour this field exists
    to fix. So we prefill the obvious answer (their most recent title, plus the
    headline if it names a different role) and let them correct it. The step
    becomes a confirmation rather than a chore.

    Only ever a SUGGESTION: it is recorded in autofilled_fields, so the moment
    the user edits it we stop touching it.
    """
    titles: list[str] = []
    for entry in _clean_dict_list(parsed.get("work_history")) or []:
        title = entry.get("title") or entry.get("job_title") or entry.get("position")
        if title and str(title).strip():
            titles.append(str(title).strip())
            break  # most recent only — older roles are usually the wrong target

    headline = (parsed.get("headline") or "").strip()
    # A headline is often the aspiration ("Aspiring Data Scientist") where the
    # work history is the past, so it is worth keeping when it differs.
    if headline and len(headline) <= 100:
        if not titles or headline.lower() != titles[0].lower():
            titles.append(headline)

    return titles[:2]


async def _apply_to_profile(
    user_id, parsed: dict, *, trust_absent: bool = False
) -> None:
    """Merge a parsed CV into the user's profile.

    ``trust_absent`` says whether a field missing from ``parsed`` means "this CV
    does not mention it" (so clear what an earlier CV put there) or merely "we
    did not manage to read it". Only the full AI parse can tell those apart: the
    regex baseline only ever finds name, email and phone, so trusting its
    silence would wipe skills, work history and summary off the profile every
    time the LLM provider had a bad minute.
    """
    from app.models.profile import Profile
    from app.models.user import User

    profile = await Profile.find_one(Profile.user_id == user_id)
    if profile is None:
        # The API creates the profile before enqueuing, but a task replayed
        # against an older row must not silently discard everything it parsed.
        user = await User.get(user_id)
        if user is None:
            log.warning("cv_parse_no_user", user_id=str(user_id))
            return
        from app.services.auth_service import ensure_profile

        profile = await ensure_profile(user)

    addr = parsed.get("address", {}) or {}
    candidates = {
        "first_name": parsed.get("first_name"),
        "last_name": parsed.get("last_name"),
        "phone": parsed.get("phone"),
        "email": parsed.get("email"),
        "address_line1": addr.get("line1"),
        "city": addr.get("city"),
        "region": addr.get("region"),
        "postal_code": addr.get("postal_code"),
        "country": addr.get("country"),
        "headline": parsed.get("headline"),
        "summary": parsed.get("summary"),
        "skills": _clean_str_list(parsed.get("skills")),
        "work_history": _clean_dict_list(parsed.get("work_history")),
        "education": _clean_dict_list(parsed.get("education")),
        "certifications": _clean_dict_list(parsed.get("certifications")),
        # Prefilled so the "what are you looking for?" step is a confirmation
        # rather than an empty box. Provenance-tracked like everything else, so
        # a user who edits it owns it from then on.
        "target_titles": _suggest_target_titles(parsed),
    }

    # Write a field when it is empty, or when the value sitting there is one we
    # put there ourselves. Never when the user typed it.
    #
    # The old rule was `profile.x = profile.x or parsed.get("x")`, which reads as
    # "don't clobber the user" but actually means "the first CV wins forever":
    # replacing a wrongly-uploaded CV left every detail from the old one in
    # place, because nothing was blank any more.
    ours = set(profile.autofilled_fields)
    still_ours: set[str] = set()
    for field, value in candidates.items():
        current = getattr(profile, field)
        if not _is_blank(current) and field not in ours:
            continue  # the user's own answer — leave it alone
        if not _is_blank(value):
            setattr(profile, field, value)
            still_ours.add(field)
        elif field in ours and not _is_blank(current):
            # An earlier CV filled this and the new one does not mention it.
            if trust_absent:
                # Replacing a CV should leave the profile describing the new CV,
                # not a union of both. Only ever clears a value we wrote — a
                # hand-typed one is excluded by the check above.
                setattr(profile, field, _blank_like(current))
            else:
                still_ours.add(field)

    profile.autofilled_fields = sorted(still_ours)

    profile.touch()
    await profile.save()
