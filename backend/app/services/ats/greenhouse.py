"""Greenhouse ATS adapter.

Fills the standard Greenhouse "job_application" form (first/last name, email,
phone, résumé upload) and submits. Never solves CAPTCHAs — see base module.
"""

from __future__ import annotations

from typing import Any

from app.services.ats.base import AtsAdapter


class GreenhouseAdapter(AtsAdapter):
    ats_type = "greenhouse"
    auto_submits = True

    # Employers may point their Greenhouse board at their own careers site
    # (Stripe's redirects to stripe.com, which has no form on the page). Landing
    # anywhere else is reported as `employer_hosts_own_form`, not as a parse
    # failure.
    apply_hosts = ("greenhouse.io",)

    # NOTE on selector order: modern Greenhouse renders every field with an `id`
    # and an EMPTY `name` attribute, so the `input[name=...]` forms below match
    # nothing on current boards and are kept only for older embedded boards.

    first_name_selectors = [
        "#first_name",
        'input[name="first_name"]',
        'input[aria-label="First Name" i]',
        'input[autocomplete="given-name"]',
    ]
    last_name_selectors = [
        "#last_name",
        'input[name="last_name"]',
        'input[aria-label="Last Name" i]',
        'input[autocomplete="family-name"]',
    ]
    email_selectors = [
        "#email",
        'input[name="email"]',
        'input[type="email"]',
        'input[aria-label="Email" i]',
        'input[autocomplete="email"]',
    ]
    phone_selectors = [
        "#phone",
        'input[name="phone"]',
        'input[type="tel"]',
        'input[aria-label="Phone" i]',
        'input[autocomplete="tel"]',
    ]
    # Generic fallbacks are scoped to the application form so we cannot attach
    # the CV to an unrelated file input (e.g. a cover-letter or portfolio field).
    # The file input IS #resume — it is not a wrapper containing one, which is
    # why '#resume input[type=file]' matched nothing on any current board.
    resume_selectors = [
        'input[type="file"]#resume',
        'input[type="file"][id*="resume" i]',
        'input[type="file"][name*="resume" i]',
        '#application_form input[type="file"]',
        'form#application-form input[type="file"]',
    ]
    # #submit_app is gone from current Greenhouse; a plain submit button is what
    # actually renders. Kept first for older embedded boards that still have it.
    submit_selectors = [
        "#submit_app",
        'button:has-text("Submit Application")',
        '#application_form button[type="submit"]',
        'form#application-form button[type="submit"]',
        'form:has(input[name="email"]) button[type="submit"]',
        'form:has(input[name="email"]) input[type="submit"]',
    ]

    # aria-label is the only reliable handle for these: Greenhouse gives custom
    # questions opaque ids like "question_8581812008" that differ per posting.
    linkedin_selectors = [
        'input[aria-label*="LinkedIn" i]',
        'input[id*="linkedin" i]',
    ]
    website_selectors = [
        'input[aria-label*="Website" i]',
        'input[aria-label*="Portfolio" i]',
    ]

    # Field ids confirmed against a live job-boards.greenhouse.io form.
    demographic_selectors = {
        "gender": ["#gender", 'select[id*="gender" i]'],
        "hispanic_or_latino": ["#hispanic_ethnicity", 'select[id*="hispanic" i]'],
        "race": ["#race", 'select[id*="race" i]'],
        "veteran_status": ["#veteran_status", 'select[id*="veteran" i]'],
        "disability_status": ["#disability_status", 'select[id*="disability" i]'],
    }

    cover_letter_selectors = [
        'textarea#cover_letter_text',
        'textarea[name="cover_letter"]',
        'textarea[aria-label*="cover letter" i]',
        'textarea[id*="cover" i]',
    ]

    async def apply(
        self, application: Any, job: Any, profile: Any, credential: Any
    ) -> dict[str, str]:
        return await self.run_standard_flow(application, job, profile, credential)
