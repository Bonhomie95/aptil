"""Ashby ATS adapter.

Fills the standard Ashby application form (name, email, phone, résumé upload)
and submits. Ashby renders a React form with ``_fieldEntry`` name attributes and
aria-labelled inputs, so selectors are matched flexibly. Never solves CAPTCHAs —
see base module.
"""

from __future__ import annotations

from typing import Any

from app.services.ats.base import AtsAdapter


class AshbyAdapter(AtsAdapter):
    ats_type = "ashby"

    apply_hosts = ("ashbyhq.com",)

    name_selectors = [
        'input[name="_systemfield_name"]',
        'input[aria-label="Name"]',
        'input[id*="name"]',
    ]
    email_selectors = [
        'input[name="_systemfield_email"]',
        'input[type="email"]',
        'input[aria-label="Email"]',
    ]
    phone_selectors = [
        'input[name="_systemfield_phone"]',
        'input[type="tel"]',
        'input[aria-label="Phone"]',
    ]
    resume_selectors = [
        'input[name="_systemfield_resume"]',
        'input[type="file"][name*="resume"]',
        'input[type="file"][accept*="pdf"]',
        'form:has(input[type="email"]) input[type="file"]',
    ]
    submit_selectors = [
        'button:has-text("Submit Application")',
        'form:has(input[type="email"]) button[type="submit"]',
        'button[type="submit"]:has-text("Submit")',
    ]

    async def apply(
        self, application: Any, job: Any, profile: Any, credential: Any
    ) -> dict[str, str]:
        return await self.run_standard_flow(application, job, profile, credential)
