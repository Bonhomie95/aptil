"""User profile, résumé documents, and encrypted site credentials."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from app.db.base import TenantDocument

# --- Voluntary self-identification -------------------------------------------
#
# US employers ask these on nearly every application (Greenhouse ships them as
# `gender`, `hispanic_ethnicity`, `veteran_status`, `disability_status`). They
# are VOLUNTARY: every field defaults to unanswered, "decline_to_self_identify"
# is a first-class value rather than an absence, and nothing here is ever used
# for matching, scoring, ranking or prompting — it is only ever replayed into a
# form the user has chosen to submit.
#
# Kept in its own model so it can be excluded wholesale from logs and exports.

DECLINE = "decline_to_self_identify"

GENDER_CHOICES = ("male", "female", "non_binary", DECLINE)
HISPANIC_CHOICES = ("yes", "no", DECLINE)

# EEO-1 race/ethnicity. Every non-Hispanic category is qualified "(Not Hispanic
# or Latino)" on the official taxonomy — the qualifier is part of the category,
# not decoration, because Hispanic/Latino is collected as ETHNICITY and takes
# precedence over race on the EEO-1 report.
RACE_CHOICES = (
    "hispanic_or_latino",
    "white",
    "black_or_african_american",
    "native_hawaiian_or_pacific_islander",
    "asian",
    "american_indian_or_alaska_native",
    "two_or_more_races",
    DECLINE,
)

# VEVRAA single-choice question, as most ATS forms render it.
VETERAN_CHOICES = ("protected_veteran", "not_a_veteran", DECLINE)

# The four protected-veteran classifications under VEVRAA (38 U.S.C. 4212).
# A person can hold SEVERAL at once — a disabled veteran discharged last year is
# both "disabled" and "recently separated" — so this is a list, not a choice.
# Forms that ask a single question get VETERAN_CHOICES above; forms that ask
# "check all that apply" get these.
VETERAN_CATEGORY_CHOICES = (
    "disabled_veteran",
    "recently_separated_veteran",
    "active_duty_wartime_or_campaign_badge_veteran",
    "armed_forces_service_medal_veteran",
)

# OFCCP Form CC-305 (OMB 1250-0005, expires 07/31/2029). The three options are
# fixed by the form and must not be reworded or extended — it is a standardized
# federal form, and "I do not want to answer" is a substantive answer rather
# than a blank. Stored separately from DECLINE for exactly that reason.
DISABILITY_CHOICES = ("yes", "no", "do_not_want_to_answer")

class Demographics(BaseModel):
    """Voluntary EEO self-identification. Every field is optional."""

    gender: str | None = None
    hispanic_or_latino: str | None = None
    race: str | None = None
    veteran_status: str | None = None
    #: Which VEVRAA classifications apply. Only meaningful when
    #: veteran_status == "protected_veteran".
    veteran_categories: list[str] = Field(default_factory=list)
    disability_status: str | None = None

    def answered(self) -> bool:
        """True if the user has made any choice at all, including declining."""
        return any(
            getattr(self, f) for f in self.model_fields  # noqa: PLC0206
        )


class Profile(TenantDocument):
    """One profile per user. Populated from CV parsing, editable by the user."""

    user_id: uuid.UUID

    first_name: str | None = None
    last_name: str | None = None
    # Contact email used on application forms. Seeded from the account email at
    # profile creation; the user may override it (ATS forms require an email —
    # without this the apply engine submits blank contact details).
    email: str | None = None
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None

    headline: str | None = None
    summary: str | None = None

    # CV-derived structured data — source of truth for matching + tailoring.
    work_history: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)

    # What the user actually WANTS, as opposed to what they last did. Matching
    # previously inferred intent solely from the newest work_history title, so a
    # developer wanting to move into SRE or product got shown more of the job
    # they were trying to leave. These are the primary title signal; the CV is
    # only the fallback.
    target_titles: list[str] = Field(default_factory=list)
    #: entry | mid | senior | lead | executive — free-form, matched loosely.
    target_seniority: str | None = None
    # Companies the user never wants to see or apply to — current employer,
    # somewhere they were rejected, a competitor, anywhere. Matched case- and
    # punctuation-insensitively against Job.company, so "Acme, Inc." entered as
    # "acme" still excludes it.
    excluded_companies: list[str] = Field(default_factory=list)
    # Where the user wants jobs, independent of their home address. ISO-2
    # country codes and/or continent names ("europe"), expanded by the search
    # layer. Empty = fall back to their address country / the deployment
    # default. Choosing countries here IS how a user excludes the rest.
    target_countries: list[str] = Field(default_factory=list)
    # Voluntary EEO answers, replayed into application forms that ask. Never
    # used for matching or fed to the LLM — see Demographics above.
    demographics: Demographics = Field(default_factory=Demographics)
    resume_strategy: str = "same"  # none | same | tailored
    preferences: dict[str, Any] = Field(default_factory=dict)

    # Which fields currently hold a value Aptil wrote (CV parse, or the account
    # details we seed at creation) rather than one the user typed.
    #
    # Without this, "only fill blanks" is the only safe merge rule — and it
    # makes the profile write-once: upload the wrong CV, upload the right one,
    # and the second parse has nothing blank left to fill, so the stale details
    # stand. Tracking provenance lets a re-parse replace what an earlier parse
    # put there while still never touching what the user edited by hand.
    autofilled_fields: list[str] = Field(default_factory=list)

    class Settings:
        name = "profiles"
        indexes = [IndexModel([("user_id", ASCENDING)], unique=True)]


class ResumeDocument(TenantDocument):
    """An uploaded CV or a generated/tailored résumé, stored in MinIO."""

    user_id: uuid.UUID
    kind: str = "uploaded"  # uploaded | tailored
    filename: str
    storage_key: str
    content_type: str = "application/pdf"
    size_bytes: int | None = None

    extracted_text: str | None = None
    parse_status: str = "pending"  # pending | done | failed
    parse_error: str | None = None

    class Settings:
        name = "resume_documents"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("kind", ASCENDING)]),
            IndexModel([("tenant_id", ASCENDING)]),
        ]


class SiteCredential(TenantDocument):
    """Encrypted per-site credentials for consent-based ATS apply.

    Passwords are unique per site and ENVELOPE-ENCRYPTED at rest: a random
    per-secret data key encrypts the password and CREDENTIAL_ENCRYPTION_KEY
    encrypts that data key, so rotating the outer key re-wraps 32 bytes per row
    instead of re-encrypting the table. Never plaintext, never one reused
    secret. See core.security.encrypt_secret.
    """

    user_id: uuid.UUID
    site_domain: str
    login_email: str
    encrypted_password: str  # v2.<key id>.<wrapped data key>.<ciphertext>
    # True when Aptil created this account with the user's managed alias, as
    # opposed to the user storing an account they made themselves. Managed
    # credentials start unverified: most sites won't accept a sign-in (or an
    # application) until the address is confirmed via the email they send.
    managed: bool = False
    #: active | pending_verification
    status: str = "active"

    class Settings:
        name = "site_credentials"
        indexes = [
            # One credential per user per site: re-submitting updates in place
            # instead of silently stacking duplicates.
            IndexModel(
                [("user_id", ASCENDING), ("site_domain", ASCENDING)], unique=True
            ),
            IndexModel([("tenant_id", ASCENDING)]),
        ]


class InboundEmail(TenantDocument):
    """Mail received on a user's managed apply alias.

    This is both plumbing and product: verification links for accounts we
    created arrive here, and so do the employer's own confirmations, rejections
    and interview invites — which the dashboard surfaces as application status
    the user never has to forward to us.
    """

    user_id: uuid.UUID
    alias: str
    from_address: str
    subject: str = ""
    #: Plain-text body (HTML is stripped by the inbound worker; we never store
    #: or render foreign HTML).
    body_text: str = ""
    #: verification | confirmation | interview | rejection | other
    kind: str = "other"
    #: Registrable domain the sender resolves to, e.g. "greenhouse.io".
    sender_domain: str = ""
    #: First same-domain verification link found, when kind == "verification".
    verification_url: str | None = None
    processed: bool = False

    class Settings:
        name = "inbound_emails"
        indexes = [
            IndexModel([("user_id", ASCENDING), ("created_at", ASCENDING)]),
            IndexModel([("alias", ASCENDING)]),
        ]
