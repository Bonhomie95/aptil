"""Jobs (shared discovery pool) and per-user applications."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.core.config import settings
from app.db.base import TenantDocument, TimestampedDocument


class Job(TimestampedDocument):
    """A discovered job posting. SHARED across tenants (spec point 9).

    `fingerprint` deduplicates the same role across boards (spec point 11):
    normalized(company + title + location) hashed. Same fingerprint => apply once.
    """

    fingerprint: str

    source: str  # enums.JobSource
    source_job_id: str | None = None
    # Where the automation goes to fill the form. For Greenhouse this is the
    # canonical job-boards.greenhouse.io URL, which is NOT necessarily where the
    # employer sends human visitors.
    apply_url: str
    # The employer's own posting page, for the "view posting" link in the UI.
    # Optional: aggregators and most boards only have the one URL.
    listing_url: str | None = None
    ats_type: str | None = None  # greenhouse / lever / ashby / ...

    company: str
    title: str
    location: str | None = None
    remote: bool | None = None
    description: str | None = None

    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None

    raw: dict[str, Any] = Field(default_factory=dict)
    posted_at: datetime | None = None

    class Settings:
        name = "jobs"
        indexes = [
            IndexModel([("fingerprint", ASCENDING)], unique=True),
            IndexModel([("company", ASCENDING)]),
            IndexModel([("title", ASCENDING)]),
            IndexModel([("created_at", ASCENDING)]),
            # Retention TTL: expire a posting this long after it was last seen
            # (updated_at is refreshed on every re-discovery). Keeps the shared
            # pool fresh and bounded. 7 days by default; see JOB_RETENTION_DAYS.
            IndexModel(
                [("updated_at", ASCENDING)],
                # 0 = disabled -> ~100 years, so it never expires (an
                # expireAfterSeconds of 0 would delete everything immediately).
                expireAfterSeconds=(settings.JOB_RETENTION_DAYS or 36500) * 86400,
            ),
        ]


class JobApplication(TenantDocument):
    """A user's application to a specific job. Drives the dashboard stats."""

    user_id: uuid.UUID
    job_id: uuid.UUID
    resume_document_id: uuid.UUID | None = None
    # Cover letter tailored to this job, generated alongside the tailored résumé.
    # Plain text; the apply engine fills it into a cover-letter field when the
    # form has one.
    cover_letter: str | None = None

    status: str = "discovered"
    match_score: float | None = None
    match_reasons: list[str] = Field(default_factory=list)

    # What the apply engine actually put on the form, so the user can see the
    # automation worked and exactly what is still missing. Values only, never
    # secrets.
    submitted_fields: dict[str, Any] = Field(default_factory=dict)
    # Which stored site credential (if any) was used for this submission.
    credential_id: uuid.UUID | None = None
    # Machine-readable reason the row needs attention, for the UI to act on.
    needs_action: str | None = None

    # Audit trail: every state transition + what the engine did.
    events: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    submitted_at: datetime | None = None

    class Settings:
        name = "job_applications"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("job_id", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING), ("status", ASCENDING)]),
            IndexModel([("tenant_id", ASCENDING)]),
        ]
