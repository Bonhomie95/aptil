"""Lever ATS adapter.

Fills the standard Lever application form (full name, email, phone, résumé
upload) and submits. Never solves CAPTCHAs — see base module.
"""

from __future__ import annotations

from typing import Any

from app.services.ats.base import AtsAdapter


class LeverAdapter(AtsAdapter):
    ats_type = "lever"

    apply_hosts = ("lever.co",)

    # Lever uses a single full-name field by default.
    name_selectors = [
        'input[name="name"]',
        'input[autocomplete="name"]',
        "#name",
    ]
    email_selectors = [
        'input[name="email"]',
        'input[type="email"]',
        "#email",
    ]
    phone_selectors = [
        'input[name="phone"]',
        'input[type="tel"]',
        "#phone",
    ]
    # Scoped fallbacks only — a bare input[type=file] could be any upload on
    # the page, and a bare submit button could be an unrelated form.
    resume_selectors = [
        'input[name="resume"]',
        'input[type="file"][name*="resume"]',
        'form.application-form input[type="file"]',
        'form:has(input[name="email"]) input[type="file"]',
    ]
    submit_selectors = [
        'button:has-text("Submit application")',
        "button.postings-btn[type='submit']",
        'form.application-form button[type="submit"]',
        'form:has(input[name="email"]) button[type="submit"]',
        'form:has(input[name="email"]) input[type="submit"]',
    ]

    async def apply(
        self, application: Any, job: Any, profile: Any, credential: Any
    ) -> dict[str, str]:
        return await self.run_standard_flow(application, job, profile, credential)
