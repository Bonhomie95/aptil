"""Mock interview sessions, grounded in the user's CV and a target job."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field
from pymongo import ASCENDING, IndexModel

from app.db.base import TenantDocument


class InterviewSession(TenantDocument):
    user_id: uuid.UUID
    # Optional job grounding: questions/tone adapt to this role (spec point 19).
    job_id: uuid.UUID | None = None

    status: str = "created"
    role_context: str | None = None

    questions: list[dict[str, Any]] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    feedback: dict[str, Any] = Field(default_factory=dict)
    overall_score: float | None = None
    completed_at: datetime | None = None

    class Settings:
        name = "interview_sessions"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("tenant_id", ASCENDING)]),
        ]
