"""Job discovery + dedupe.

Discovery pulls from LEGITIMATE sources only (official APIs / public ATS endpoints /
job feeds) — see docs/compliance.md. Each posting is fingerprinted so the same role
seen on multiple boards counts once (spec point 11): apply once per fingerprint.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.core.logging import get_logger
from app.models.job import Job
from app.workers.celery_app import celery
from app.workers.db import run_async

log = get_logger(__name__)

# Descriptions are stored and later fed to the LLM; cap them so one enormous
# posting cannot bloat the document or the prompt.
MAX_DESCRIPTION_CHARS = 20_000
MAX_RAW_BYTES = 64_000


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def fingerprint(company: str, title: str, location: str | None) -> str:
    """Stable hash of normalized company + title + location.

    Same role across Indeed/LinkedIn/company site -> identical fingerprint.
    """
    basis = f"{normalize(company)}|{normalize(title)}|{normalize(location or '')}"
    return hashlib.sha256(basis.encode()).hexdigest()[:64]


def _clean_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_raw(raw: Any) -> dict:
    """Keep the provider payload only when it is small enough to be worth it."""
    if not isinstance(raw, dict):
        return {}
    try:
        import json

        if len(json.dumps(raw, default=str)) > MAX_RAW_BYTES:
            return {"_truncated": True}
    except (TypeError, ValueError):
        return {}
    return raw


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


async def upsert_job(posting: dict) -> tuple[Job | None, bool]:
    """Insert a discovered posting, deduped on fingerprint.

    Returns ``(job, created)``; ``(None, False)`` when the posting is unusable.
    Never raises on a malformed payload — one bad record must not abort a batch.
    """
    company = str(posting.get("company") or "").strip()
    title = str(posting.get("title") or "").strip()
    apply_url = str(posting.get("apply_url") or "").strip()
    if not company or not title or not apply_url:
        log.warning(
            "posting_skipped_incomplete",
            source=posting.get("source"),
            has_company=bool(company),
            has_title=bool(title),
            has_apply_url=bool(apply_url),
        )
        return None, False
    if not apply_url.startswith(("http://", "https://")):
        log.warning("posting_skipped_bad_url", url=apply_url[:120])
        return None, False

    fp = fingerprint(company, title, posting.get("location"))
    existing = await Job.find_one(Job.fingerprint == fp)
    if existing:
        # Re-seeing a posting keeps it alive: refresh updated_at so the
        # retention TTL (which expires jobs not seen for JOB_RETENTION_DAYS)
        # only reaps postings that have genuinely gone stale.
        existing.touch()
        try:
            await existing.save()
        except Exception as exc:  # noqa: BLE001 - a failed refresh is not fatal
            log.debug("job_refresh_failed", fingerprint=fp, error=str(exc)[:120])
        return existing, False

    description = posting.get("description")
    if isinstance(description, str):
        description = description[:MAX_DESCRIPTION_CHARS]

    job = Job(
        fingerprint=fp,
        source=posting.get("source", "other"),
        source_job_id=posting.get("source_job_id"),
        apply_url=apply_url,
        ats_type=posting.get("ats_type"),
        company=company,
        title=title,
        location=posting.get("location"),
        remote=posting.get("remote"),
        description=description,
        # These were collected by every connector and then silently dropped.
        salary_min=_clean_int(posting.get("salary_min")),
        salary_max=_clean_int(posting.get("salary_max")),
        currency=(posting.get("currency") or None),
        posted_at=_parse_dt(posting.get("posted_at")),
        raw=_clean_raw(posting.get("raw")),
    )
    try:
        await job.insert()
    except DuplicateKeyError:
        # Another worker inserted the same fingerprint between our read and write.
        found = await Job.find_one(Job.fingerprint == fp)
        return found, False
    return job, True


@celery.task(name="discovery.ingest_postings", acks_late=True)
def ingest_postings(postings: list[dict]) -> dict:
    """Ingest a batch of already-fetched postings from a connector.

    Connectors (web search, Greenhouse, Lever, Ashby, remote boards, ...) live in
    app/services/connectors/ and hand normalized postings to this task.
    """
    result = run_async(_ingest_async(postings or []))
    log.info(
        "postings_ingested",
        received=result["received"],
        new=result["new"],
        skipped=result["skipped"],
    )
    return result


async def _ingest_async(postings: list[dict]) -> dict:
    inserted = 0
    skipped = 0
    for posting in postings:
        if not isinstance(posting, dict):
            skipped += 1
            continue
        try:
            job, created = await upsert_job(posting)
        except Exception as exc:  # noqa: BLE001 - one bad row must not kill the batch
            log.warning("posting_ingest_failed", error=str(exc))
            skipped += 1
            continue
        if job is None:
            skipped += 1
        elif created:
            inserted += 1
    return {"received": len(postings), "new": inserted, "skipped": skipped}
