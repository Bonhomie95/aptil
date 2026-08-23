"""Beanie document models. `document_models` is passed to init_beanie()."""

from app.models.billing import Plan, StripeEvent, Subscription
from app.models.interview import InterviewSession
from app.models.job import Job, JobApplication
from app.models.profile import InboundEmail, Profile, ResumeDocument, SiteCredential
from app.models.tenant import Tenant
from app.models.user import EmailVerificationToken, RefreshSession, User

document_models = [
    Tenant,
    User,
    EmailVerificationToken,
    RefreshSession,
    Profile,
    ResumeDocument,
    SiteCredential,
    InboundEmail,
    Plan,
    Subscription,
    StripeEvent,
    Job,
    JobApplication,
    InterviewSession,
]

__all__ = [
    "Tenant",
    "User",
    "EmailVerificationToken",
    "RefreshSession",
    "Profile",
    "ResumeDocument",
    "SiteCredential",
    "InboundEmail",
    "Plan",
    "Subscription",
    "StripeEvent",
    "Job",
    "JobApplication",
    "InterviewSession",
    "document_models",
]
