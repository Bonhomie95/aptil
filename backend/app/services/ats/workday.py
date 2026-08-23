"""Workday ATS adapter.

Workday is the reason :meth:`AtsAdapter.perform_login` exists: unlike
Greenhouse, Lever and Ashby, it will not show an application form to an
anonymous visitor. The user creates the account on the tenant's careers site
themselves and stores it on the Job site accounts step — or, for opted-in
users, we create one with their managed alias (base.perform_registration) and
park until the verification mail arrives. See docs/compliance.md §1a.

WHAT THIS ADAPTER DOES NOT DO, AND WHY
--------------------------------------
It does not submit. Workday's application is a five-page wizard (My Information
-> My Experience -> Application Questions -> Voluntary Disclosures -> Review),
and ``run_standard_flow`` is a single-page fill-and-submit. Two things follow:

1. We cannot evidence a submission, and §2a forbids claiming one we cannot
   evidence.
2. Signing in headlessly would not help the user even if we did it. The browser
   context is thrown away when the task ends, so the session never reaches the
   user's own browser — they would sign in again to finish the wizard anyway.

So spending the user's stored credential on a login we cannot capitalise on is
worse than not trying: it risks a lockout on a changed layout or an MFA prompt,
for no gain. This adapter therefore parks immediately, with a precise reason and
without launching a browser at all.

The selector map below is real and kept current so that finishing the wizard is
a matter of writing the page-to-page walk, not rediscovering Workday's DOM.
Completing it needs: the multi-step walk, "Save and Continue" between pages,
Workday's per-tenant custom question pages (which are arbitrary), and a
confirmation check on the final Review page.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.services.ats.base import STATUS_NEEDS_INFO, AtsAdapter


class WorkdayAdapter(AtsAdapter):
    ats_type = "workday"

    apply_hosts = ("myworkdayjobs.com", "workday.com")

    # Workday always gates the form behind a sign-in.
    requires_login = True

    # data-automation-id is Workday's stable hook; class names are generated.
    login_email_selectors = [
        'input[data-automation-id="email"]',
        'input[data-automation-id="userName"]',
    ]
    login_password_selectors = ['input[data-automation-id="password"]']
    login_submit_selectors = [
        'button[data-automation-id="signInSubmitButton"]',
        'div[data-automation-id="click_filter"][role="button"]',
    ]
    # Workday's "Create Account" flow shares the sign-in page. Verify-password
    # field is part of the same form.
    signup_link_selectors = [
        'button[data-automation-id="createAccountLink"]',
        '[data-automation-id="createAccountLink"]',
    ]
    signup_email_selectors = ['input[data-automation-id="email"]']
    signup_password_selectors = ['input[data-automation-id="password"]']
    signup_confirm_password_selectors = [
        'input[data-automation-id="verifyPassword"]',
    ]
    signup_submit_selectors = [
        'button[data-automation-id="createAccountSubmitButton"]',
        'div[data-automation-id="click_filter"][role="button"]',
    ]

    login_wall_selectors = [
        '[data-automation-id="signInLink"]',
        '[data-automation-id="authAccountSignIn"]',
    ]
    signed_in_selectors = [
        '[data-automation-id="utilityButtonSignOut"]',
        '[data-automation-id="signOutLink"]',
    ]

    first_name_selectors = ['input[data-automation-id="legalNameSection_firstName"]']
    last_name_selectors = ['input[data-automation-id="legalNameSection_lastName"]']
    email_selectors = ['input[data-automation-id="email"]']
    phone_selectors = ['input[data-automation-id="phone-number"]']
    resume_selectors = ['input[data-automation-id="file-upload-input-ref"]']
    # "Save and Continue" advances a page; it does not submit an application.
    submit_selectors = ['button[data-automation-id="bottom-navigation-next-button"]']

    def login_url(self, apply_url: str) -> str | None:
        """``https://{tenant}.{dc}.myworkdayjobs.com/en-US/{site}/login``."""
        parts = urlparse(apply_url)
        segments = [s for s in parts.path.split("/") if s]
        # /en-US/{site}/job/... -> keep the locale and site, swap the rest.
        if len(segments) < 2:
            return None
        return f"{parts.scheme}://{parts.netloc}/{segments[0]}/{segments[1]}/login"

    async def apply(
        self, application: Any, job: Any, profile: Any, credential: Any
    ) -> dict[str, str]:
        if credential is None:
            # Distinguish "you have not given us an account" from "we cannot do
            # this" — the first is fixable by the user, the second is not.
            return {"status": STATUS_NEEDS_INFO, "detail": "credential_required"}
        return {"status": STATUS_NEEDS_INFO, "detail": "multi_step_application"}
