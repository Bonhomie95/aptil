"""Onboarding + profile schemas."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.profile import (
    DISABILITY_CHOICES,
    GENDER_CHOICES,
    HISPANIC_CHOICES,
    RACE_CHOICES,
    VETERAN_CATEGORY_CHOICES,
    VETERAN_CHOICES,
)

# Bounds that keep a single profile from becoming unbounded storage / prompt input.
MAX_LIST_ITEMS = 50
MAX_SKILLS = 200
MAX_TEXT = 5000
# More than a handful of target titles stops being intent and starts being
# "show me everything", which is what the generic-results complaint was about.
MAX_TARGET_TITLES = 8


class DemographicsUpdate(BaseModel):
    """Voluntary EEO self-identification. Every field optional and nullable.

    Values are constrained so a typo cannot silently become an unmatchable
    answer on a real employer's form.
    """

    # from_attributes so ProfileRead can serialize the models.profile
    # Demographics instance straight off the document.
    model_config = {"from_attributes": True}

    gender: str | None = None
    hispanic_or_latino: str | None = None
    race: str | None = None
    veteran_status: str | None = None
    veteran_categories: list[str] | None = Field(
        default=None, max_length=len(VETERAN_CATEGORY_CHOICES)
    )
    disability_status: str | None = None

    @field_validator("gender")
    @classmethod
    def _gender(cls, v: str | None) -> str | None:
        return _one_of(v, GENDER_CHOICES, "gender")

    @field_validator("hispanic_or_latino")
    @classmethod
    def _hispanic(cls, v: str | None) -> str | None:
        return _one_of(v, HISPANIC_CHOICES, "hispanic_or_latino")

    @field_validator("race")
    @classmethod
    def _race(cls, v: str | None) -> str | None:
        return _one_of(v, RACE_CHOICES, "race")

    @field_validator("veteran_status")
    @classmethod
    def _veteran(cls, v: str | None) -> str | None:
        return _one_of(v, VETERAN_CHOICES, "veteran_status")

    @field_validator("disability_status")
    @classmethod
    def _disability(cls, v: str | None) -> str | None:
        return _one_of(v, DISABILITY_CHOICES, "disability_status")

    @field_validator("veteran_categories")
    @classmethod
    def _vet_categories(cls, v: list[str] | None) -> list[str] | None:
        """The four VEVRAA classifications, deduped and order-stable.

        A user can hold several at once — a disabled veteran discharged last
        year is both "disabled" and "recently separated".
        """
        if v is None:
            return None
        out: list[str] = []
        for raw in v:
            item = str(raw).strip()
            if item and item not in VETERAN_CATEGORY_CHOICES:
                raise ValueError(
                    "veteran_categories must be from: "
                    + ", ".join(VETERAN_CATEGORY_CHOICES)
                )
            if item and item not in out:
                out.append(item)
        return out


def _one_of(value: str | None, allowed: tuple[str, ...], field: str) -> str | None:
    if value is None or value == "":
        return None
    if value not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(allowed)}")
    return value


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, max_length=100)
    headline: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=MAX_TEXT)
    work_history: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_LIST_ITEMS)
    certifications: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_LIST_ITEMS)
    education: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_LIST_ITEMS)
    skills: list[str] | None = Field(default=None, max_length=MAX_SKILLS)
    target_titles: list[str] | None = Field(default=None, max_length=MAX_TARGET_TITLES)
    target_seniority: str | None = Field(default=None, max_length=40)
    excluded_companies: list[str] | None = Field(default=None, max_length=200)
    target_countries: list[str] | None = Field(default=None, max_length=30)
    demographics: DemographicsUpdate | None = None
    resume_strategy: str | None = None
    preferences: dict[str, Any] | None = None

    @field_validator("target_titles")
    @classmethod
    def _clean_targets(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for raw in v:
            title = str(raw).strip()[:100]
            if title and title.lower() not in {t.lower() for t in out}:
                out.append(title)
        return out

    @field_validator("excluded_companies")
    @classmethod
    def _clean_excluded(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out: list[str] = []
        for raw in v:
            name = str(raw).strip()[:120]
            if name and name.lower() not in {c.lower() for c in out}:
                out.append(name)
        return out

    @field_validator("target_countries")
    @classmethod
    def _clean_countries(cls, v: list[str] | None) -> list[str] | None:
        """Keep only codes/continents the search supports; a bad value silently
        widening the search to a country the user did not pick would be worse
        than dropping it."""
        if v is None:
            return None
        from app.services.geo import CONTINENTS, SEARCH_COUNTRIES

        allowed = set(SEARCH_COUNTRIES) | set(CONTINENTS)
        out: list[str] = []
        for raw in v:
            key = str(raw).strip().lower()
            if key in allowed and key not in out:
                out.append(key)
        return out

    @field_validator("resume_strategy")
    @classmethod
    def _valid_strategy(cls, v: str | None) -> str | None:
        if v is not None and v not in {"none", "same", "tailored"}:
            raise ValueError("resume_strategy must be one of: none, same, tailored")
        return v

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        seen: list[str] = []
        for raw in v:
            skill = str(raw).strip()[:80]
            if skill and skill.lower() not in {s.lower() for s in seen}:
                seen.append(skill)
        return seen


class ProfileRead(ProfileUpdate):
    id: uuid.UUID
    model_config = {"from_attributes": True}


class ResumeRead(BaseModel):
    id: uuid.UUID
    kind: str
    filename: str
    content_type: str
    parse_status: str
    parse_error: str | None = None
    size_bytes: int | None = None
    download_url: str | None = None

    model_config = {"from_attributes": True}


class OnboardingState(BaseModel):
    step: str
    completed: bool
    profile: ProfileRead | None = None
    has_resume: bool = False
    resume_parse_status: str | None = None
    resume_parse_error: str | None = None
    steps: list[str] = Field(default_factory=list)


class SetStepRequest(BaseModel):
    step: str


class ResumeStrategyRequest(BaseModel):
    strategy: str  # none | same | tailored

    @field_validator("strategy")
    @classmethod
    def _valid(cls, v: str) -> str:
        if v not in {"none", "same", "tailored"}:
            raise ValueError("strategy must be one of: none, same, tailored")
        return v


class CredentialRequest(BaseModel):
    # Used to create an encrypted per-site credential (consent-based apply).
    site_domain: str = Field(min_length=3, max_length=253)
    login_email: EmailStr
    # If omitted, the engine generates a unique strong password for this site.
    password: str | None = Field(default=None, max_length=256)

    @field_validator("site_domain")
    @classmethod
    def _normalize_domain(cls, v: str) -> str:
        raw = v.strip().lower()
        # Accept a pasted URL and reduce it to a bare hostname.
        for prefix in ("https://", "http://"):
            if raw.startswith(prefix):
                raw = raw[len(prefix) :]
        raw = raw.split("/")[0].split("?")[0].split("#")[0]
        if raw.startswith("www."):
            raw = raw[4:]
        if "@" in raw or " " in raw or "." not in raw:
            raise ValueError("site_domain must be a bare hostname, e.g. boards.greenhouse.io")
        return raw


class CredentialRead(BaseModel):
    id: uuid.UUID
    site_domain: str
    login_email: str
    # The stored secret is never returned — only whether one exists.
    has_password: bool = True

    model_config = {"from_attributes": True}
