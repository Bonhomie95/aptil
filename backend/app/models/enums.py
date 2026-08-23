"""Shared enums."""

from __future__ import annotations

from enum import StrEnum


class OnboardingStep(StrEnum):
    CV_UPLOAD = "cv_upload"
    PERSONAL_DETAILS = "personal_details"
    JOB_HISTORY = "job_history"
    JOB_TARGETS = "job_targets"
    RESUME_STRATEGY = "resume_strategy"
    VOLUNTARY_DISCLOSURES = "voluntary_disclosures"
    CREDENTIALS = "credentials"
    PLAN_SELECTION = "plan_selection"
    COMPLETED = "completed"


class ResumeStrategy(StrEnum):
    NONE = "none"                # apply without a résumé
    SAME = "same"               # reuse the uploaded résumé as-is
    TAILORED = "tailored"       # AI-tailor per job


class AutomationState(StrEnum):
    """Whether the engine may act on this user's behalf.

    The apply engine submits applications in the user's name, so there has to be
    an off switch they control. PAUSED and STOPPED both halt new work; they
    differ in what happens to work already queued.
    """

    RUNNING = "running"
    #: Temporary. Nothing new is matched or queued; anything already queued is
    #: left alone and will still go out.
    PAUSED = "paused"
    #: Deliberate end of the search — "I took a job". Also cancels anything
    #: queued but not yet submitted, so nothing goes out in the user's name
    #: after they said stop.
    STOPPED = "stopped"


class ApplicationStatus(StrEnum):
    DISCOVERED = "discovered"
    MATCHED = "matched"
    QUEUED = "queued"
    NEEDS_INFO = "needs_info"       # blocked awaiting user input/consent
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    FAILED = "failed"


class JobSource(StrEnum):
    ADZUNA = "adzuna"
    WEB_SEARCH = "web_search"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    USAJOBS = "usajobs"
    COMPANY_SITE = "company_site"
    OTHER = "other"


class SubscriptionStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class InterviewStatus(StrEnum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
