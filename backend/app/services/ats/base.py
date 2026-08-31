"""ATS adapter base class and shared Playwright helpers.

Compliance guardrails (docs/compliance.md, sections 1 & 2) are enforced here:

- We apply through the company's own ATS application form. We do NOT pilot a
  user's logged-in LinkedIn/Indeed session.
- Where an ATS puts the application form behind a sign-in, we sign in with a
  credential the user stored for that exact site (``SiteCredential``) — or,
  when the user has opted in (``User.auto_create_accounts``) and the deployment
  has a managed mail domain, we create the account FOR them using their managed
  alias (``u-…@APPLY_EMAIL_DOMAIN``) and a generated password stored encrypted.
  The user's own email password is never involved. Accounts start
  ``pending_verification`` until the site's confirmation mail arrives on the
  alias and is followed. See docs/compliance.md section 1a.
- We NEVER bypass CAPTCHAs or bot-detection. ``detect_captcha`` runs before any
  form submission; if a challenge is present the adapter returns ``needs_info``
  with detail ``captcha_or_botcheck`` and the application is parked for the user
  to finish manually. There is deliberately no CAPTCHA-solving code path.

Correctness guardrails:

- Required fields are checked BEFORE submitting. An application with no email
  address is worthless to the employer, so we park instead of sending it.
- ``submitted`` is only reported after the page actually confirms it. A click on
  a button is not evidence of submission — client-side validation can reject the
  form and leave the user with a dashboard full of applications that were never
  really sent.

Playwright is an OPTIONAL dependency (``project.optional-dependencies.automation``).
It is imported lazily inside functions so importing this module never fails when
Playwright is not installed; adapters degrade to ``needs_info`` /
``automation_unavailable`` in that case.
"""

from __future__ import annotations

import os
import re
import tempfile
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from playwright.async_api import Page

log = get_logger(__name__)

# --- Result contract ------------------------------------------------------
STATUS_SUBMITTED = "submitted"
STATUS_NEEDS_INFO = "needs_info"
STATUS_FAILED = "failed"

# Identify honestly (compliance §6). We do not spoof a consumer browser UA.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 AptilApplyBot/1.0 (+https://aptil.ai/bot)"
)

NAV_TIMEOUT_MS = 45_000
CONFIRM_TIMEOUT_MS = 20_000


def _result(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}


def _file_exists(path: str) -> bool:
    """Sync filesystem check (kept out of async fns to satisfy ASYNC240)."""
    return os.path.exists(path)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:  # pragma: no cover
        pass


# --- CAPTCHA / bot-detection markers (HARD product rule: never solve/evade) ---
CAPTCHA_IFRAME_MARKERS = (
    "recaptcha",
    "hcaptcha",
    "turnstile",  # Cloudflare Turnstile
    "arkoselabs",  # FunCaptcha
    "funcaptcha",
)
# Visible-text markers. Matched against rendered text only — matching raw HTML
# meant a script tag mentioning "recaptcha" parked a perfectly fine application.
CAPTCHA_TEXT_MARKERS = (
    "verify you are human",
    "i'm not a robot",
    "i am not a robot",
    "confirm you are not a robot",
    "please complete the security check",
    "checking if the site connection is secure",
)

# Signals that the page is asking us to sign in before it will show the form.
LOGIN_WALL_TEXT_MARKERS = (
    "sign in to apply",
    "sign in to continue",
    "please sign in",
    "log in to apply",
    "you must be signed in",
    "create an account to apply",
)

# Phrases that indicate the ATS accepted the application.
CONFIRMATION_MARKERS = (
    "application submitted",
    "thank you for applying",
    "thanks for applying",
    "your application has been submitted",
    "application received",
    "we have received your application",
    "thank you for your interest",
    "successfully applied",
    "application complete",
)

# Phrases that indicate the form bounced us back.
VALIDATION_MARKERS = (
    "this field is required",
    "is required",
    "please fill",
    "please complete",
    "invalid email",
    "please correct",
)


async def _visible_text(page: Page) -> str:
    """Rendered text of the page, lower-cased. Empty string on teardown."""
    try:
        text = await page.inner_text("body")
    except Exception as exc:  # pragma: no cover - page may be navigating
        log.debug("visible_text_failed", error=str(exc)[:200])
        return ""
    return (text or "").lower()


async def detect_captcha(page: Page) -> bool:
    """Return True if the page shows a VISIBLE CAPTCHA or bot-detection
    challenge — not just markup that mentions one.

    Many ATS forms (Greenhouse in particular) embed an invisible reCAPTCHA
    scaffold on every application for silent background spam-scoring: a
    zero-height, empty div present on the page whether or not anything is
    actually being challenged. A bare selector match flagged that div as a
    challenge and parked EVERY Greenhouse application unconditionally, even
    though a real visitor never sees anything there — this app's own
    detector was too broad, not the site actually blocking it. Only a match
    that is genuinely rendered (something a real visitor would actually see)
    counts as a challenge now.

    This is intentionally conservative about what DOES count: any visible
    match means we STOP and hand control back to the user. We do not attempt
    to solve or evade it.
    """
    selector = ", ".join(
        [
            *[f'iframe[src*="{m}"]' for m in CAPTCHA_IFRAME_MARKERS],
            *[f'div[class*="{m}"]' for m in CAPTCHA_IFRAME_MARKERS],
            *[f'div[id*="{m}"]' for m in CAPTCHA_IFRAME_MARKERS],
            "[data-sitekey]",
        ]
    )
    try:
        for el in await page.query_selector_all(selector):
            if await el.is_visible():
                return True
    except Exception as exc:  # pragma: no cover - defensive against page teardown
        log.debug("captcha_probe_failed", error=str(exc)[:200])

    text = await _visible_text(page)
    return any(marker in text for marker in CAPTCHA_TEXT_MARKERS)


@asynccontextmanager
async def launch_context(**context_kwargs: Any):
    """Async context manager yielding a headless Chromium ``BrowserContext``.

    Lazily imports Playwright so this module imports cleanly without the
    optional ``automation`` extra. Raises ``ImportError`` if Playwright is not
    installed (callers catch this and return ``automation_unavailable``).

    This launches a *clean* browser context. We do NOT load a user's existing
    logged-in session or cookies (compliance section 1).
    """
    from playwright.async_api import async_playwright  # lazy, optional dep

    context_kwargs.setdefault("user_agent", USER_AGENT)
    context_kwargs.setdefault("viewport", {"width": 1280, "height": 900})
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(**context_kwargs)
        context.set_default_timeout(20_000)
        try:
            yield context
        finally:
            await context.close()
            await browser.close()


# --- Field-filling helpers ------------------------------------------------
async def fill_first(page: Page, selectors: list[str], value: str | None) -> bool:
    """Fill the first matching, visible selector with ``value``. Best-effort."""
    if not value:
        return False
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el is not None and await el.is_visible() and await el.is_enabled():
                await el.fill(value)
                return True
        except Exception as exc:  # pragma: no cover - move on to the next selector
            log.debug("fill_selector_failed", selector=selector, error=str(exc)[:200])
            continue
    return False


# --- Voluntary self-identification ------------------------------------------
#
# Employers render these as native <select> on some boards and as a
# React combobox (a text input backed by a listbox) on current Greenhouse.
# `.fill()` works on neither, so both shapes are handled explicitly.
#
# Values are the Profile enums; the tuples are substrings to look for in the
# option labels the ATS actually renders, most specific first. Matching on
# substrings rather than exact text is deliberate — every board words these
# slightly differently ("Decline To Self Identify" vs "I don't wish to answer").
# Every wording of "no answer" seen in the wild. Shared so a new phrasing is
# added once rather than per field. NOT used for disability_status: CC-305 makes
# "I do not want to answer" a substantive option of its own.
_DECLINE = (
    "decline",
    "prefer not",
    "do not wish to answer",
    "don't wish to answer",
    "do not want to answer",
    "don't want to answer",
    "wish not to answer",
    "not to answer",
)

CHOICE_LABELS: dict[str, dict[str, tuple[str, ...]]] = {
    "gender": {
        "male": ("male",),
        "female": ("female",),
        "non_binary": ("non-binary", "nonbinary", "non binary"),
        "decline_to_self_identify": _DECLINE,
    },
    "hispanic_or_latino": {
        "yes": ("yes",),
        "no": ("no",),
        "decline_to_self_identify": _DECLINE,
    },
    # EEO-1 labels carry a "(Not Hispanic or Latino)" qualifier on every race
    # category, so match on the distinctive part only — "white" matches both
    # "White" and "White (Not Hispanic or Latino)".
    "race": {
        "hispanic_or_latino": ("hispanic or latino", "hispanic/latino", "hispanic"),
        "white": ("white",),
        "black_or_african_american": ("black or african american", "black"),
        "native_hawaiian_or_pacific_islander": (
            "native hawaiian or other pacific islander",
            "native hawaiian", "pacific islander",
        ),
        "asian": ("asian",),
        "american_indian_or_alaska_native": (
            "american indian or alaska native", "american indian", "alaska native",
        ),
        "two_or_more_races": ("two or more races", "two or more"),
        "decline_to_self_identify": _DECLINE,
    },
    "veteran_status": {
        # Greenhouse words this "I identify as one or more of the classifications
        # of a protected veteran"; others just say "Protected veteran".
        "protected_veteran": (
            "identify as one or more", "one or more of the classifications",
            "i am a protected veteran", "protected veteran",
        ),
        # Ordered so this cannot be swallowed by the "protected veteran"
        # substring above — fill_choice takes the first label that matches.
        "not_a_veteran": (
            "i am not a protected veteran", "not a protected veteran",
            "am not a veteran", "not a veteran",
        ),
        "decline_to_self_identify": _DECLINE,
    },
    # OFCCP Form CC-305 wording, verbatim. Longest-first so "no, i do not have a
    # disability" cannot be matched by the bare "no" fallback.
    "disability_status": {
        "yes": (
            "yes, i have a disability, or have had one in the past",
            "yes, i have a disability", "have had one in the past", "yes, i have",
        ),
        "no": (
            "no, i do not have a disability and have not had one in the past",
            "no, i do not have a disability", "no, i don't have a disability",
            "do not have a disability",
        ),
        "do_not_want_to_answer": (
            "i do not want to answer", "i don't wish to answer",
            "do not want to answer", "do not wish to answer", "decline",
        ),
    },
}


def _best_value_for(field: str, label: str) -> str | None:
    """Which answer does this option label represent?

    Scored by the LONGEST matching label rather than the first, because the
    labels overlap by design: "protected veteran" is a substring of "I am not a
    protected veteran". First-match would have ticked "not a veteran" for a user
    who told us they ARE one — reporting the opposite of the truth to an
    employer, silently.
    """
    # "(Not Hispanic or Latino)" qualifies an EEO-1 race category; it is not
    # part of the category name. Left in, it is a LONGER match than the category
    # itself, so "White (Not Hispanic or Latino)" scored as hispanic_or_latino —
    # i.e. reported the wrong race to the employer. Qualifiers go first.
    low = re.sub(r"\([^)]*\)", " ", (label or "")).strip().lower()
    low = re.sub(r"\s+", " ", low)
    if not low:
        return None
    best_value, best_len = None, 0
    for value, wanted in CHOICE_LABELS.get(field, {}).items():
        for want in wanted:
            if want in low and len(want) > best_len:
                best_value, best_len = value, len(want)
    return best_value


async def fill_choice(
    page: Page, selectors: list[str], field: str, value: str | None
) -> bool:
    """Answer a single-choice question, native <select> or React combobox.

    Returns True only when the option matching ``value`` was actually chosen. A
    silent miss leaves the user's stated answer off a form they believe we
    filled; a wrong hit is worse, so an option is only accepted when ``value``
    is its BEST match, not merely a match.
    """
    if not value or not CHOICE_LABELS.get(field, {}).get(value):
        return False

    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el is None or not await el.is_visible():
                continue

            tag = (await el.evaluate("e => e.tagName")).lower()
            if tag == "select":
                labels = await el.eval_on_selector_all(
                    "option", "os => os.map(o => o.textContent || '')"
                )
                for idx, label in enumerate(labels):
                    if _best_value_for(field, label) == value:
                        await el.select_option(index=idx)
                        return True
                continue

            # React combobox: open it and read the rendered options, so the same
            # best-match rule applies rather than clicking the first near-hit.
            await el.click()
            try:
                options = page.get_by_role("option")
                count = await options.count()
                for i in range(min(count, 30)):
                    option = options.nth(i)
                    label = await option.inner_text(timeout=1_000)
                    if _best_value_for(field, label) == value:
                        await option.click(timeout=2_000)
                        return True
            finally:
                # Leave no listbox open — it would swallow the submit click.
                await page.keyboard.press("Escape")
        except Exception as exc:
            log.debug("choice_failed", selector=selector, field=field,
                      error=str(exc)[:200])
            continue
    return False


async def upload_first(page: Page, selectors: list[str], path: str | None) -> bool:
    """Set the resume file on the first matching file input. Best-effort."""
    if not path or not _file_exists(path):
        return False
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el is not None:
                await el.set_input_files(path)
                return True
        except Exception as exc:  # pragma: no cover
            log.debug("upload_selector_failed", selector=selector, error=str(exc)[:200])
            continue
    return False


async def resolve_resume_path(application: Any) -> str | None:
    """Download the application's résumé from object storage to a temp file.

    Falls back to the user's most recent uploaded résumé when the application
    has no tailored document linked, so a missing tailoring run does not mean
    applying with no CV at all. Callers must delete the returned file.
    """
    from app.models.profile import ResumeDocument
    from app.services.storage import download_bytes

    doc = None
    doc_id = getattr(application, "resume_document_id", None)
    try:
        if doc_id:
            doc = await ResumeDocument.get(doc_id)
        if doc is None:
            user_id = getattr(application, "user_id", None)
            if user_id is not None:
                doc = await ResumeDocument.find(
                    ResumeDocument.user_id == user_id,
                    ResumeDocument.kind == "uploaded",
                ).sort(-ResumeDocument.created_at).first_or_none()
        if doc is None:
            return None
        data = download_bytes(doc.storage_key)
        suffix = os.path.splitext(doc.filename)[1] or ".pdf"
    except Exception:  # pragma: no cover - storage/DB best-effort
        log.warning("resume_fetch_failed", application_id=str(getattr(application, "id", "")))
        return None

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="aptil_resume_")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


def full_name(profile: Any) -> str:
    parts = [getattr(profile, "first_name", None), getattr(profile, "last_name", None)]
    return " ".join(p for p in parts if p).strip()


def contact_email(profile: Any) -> str | None:
    """The email to put on an application form."""
    return (getattr(profile, "email", None) or "").strip() or None


# How long to wait for a JS-rendered application form to appear. Greenhouse,
# Ashby and most company-hosted boards mount their form with React AFTER
# `domcontentloaded` fires, and `query_selector` does NOT auto-wait the way
# Playwright locators do — so the original code inspected an empty DOM and
# reported every one of them as "form not recognised".
FORM_READY_TIMEOUT_MS = 20_000


async def wait_for_form(
    page: Page, selectors: list[str], timeout_ms: int
) -> bool:
    """Wait until any of ``selectors`` is attached to the DOM.

    Returns True as soon as one appears, False if none do within ``timeout_ms``.
    Named ``timeout_ms`` rather than ``timeout``: this is passed straight to
    Playwright's own wait, it does not bound an asyncio await.
    Uses a single combined CSS selector so the wait is one race rather than a
    serial per-selector timeout (which would take len(selectors) x timeout in
    the failure case).
    """
    usable = [s for s in selectors if s and "," not in s]
    if not usable:
        return False
    try:
        await page.wait_for_selector(
            ", ".join(usable), state="attached", timeout=timeout_ms
        )
        return True
    except Exception as exc:
        log.debug("form_never_appeared", error=str(exc)[:200])
        return False


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    """True if ``host`` is one of ``domains`` or a subdomain of one.

    Deliberately not ``str.endswith``: "notgreenhouse.io" ends with
    "greenhouse.io" and would have been accepted as the real thing.
    """
    return any(host == d or host.endswith("." + d) for d in domains)


class AtsAdapter(ABC):
    """Base class for a single ATS's application flow.

    Concrete adapters declare selector maps and reuse :meth:`run_standard_flow`.
    The public contract is :meth:`apply`, returning
    ``{"status": submitted|needs_info|failed, "detail": str}``.
    """

    #: ``ats_type`` this adapter handles (matches ``Job.ats_type``).
    ats_type: str = ""

    #: True only for adapters that actually submit an application end to end
    #: (Greenhouse/Lever/Ashby). Workday parks (multi-step wizard) and company
    #: pages have no adapter — those are NOT auto-appliable, so we never turn
    #: them into dashboard applications the user would just have to finish.
    auto_submits: bool = False

    #: CSS selectors tried in order for each standard field.
    name_selectors: list[str] = []
    first_name_selectors: list[str] = []
    last_name_selectors: list[str] = []
    email_selectors: list[str] = []
    phone_selectors: list[str] = []
    resume_selectors: list[str] = []
    submit_selectors: list[str] = []

    #: Extra fields employers ask for on nearly every application. Filling them
    #: is the difference between "we prepared this for you" and "we typed your
    #: name in and gave up".
    linkedin_selectors: list[str] = []
    website_selectors: list[str] = []

    #: Voluntary self-identification, keyed by Profile.demographics field name.
    demographic_selectors: dict[str, list[str]] = {}

    #: Cover-letter textarea, filled from JobApplication.cover_letter when set.
    cover_letter_selectors: list[str] = []

    #: Hostname suffixes this adapter's selectors are written for. Many
    #: employers configure their ATS to redirect to their own careers site
    #: (Stripe's Greenhouse board lands on stripe.com, which has no form on the
    #: page at all). Landing off-ATS is a different outcome from "the form was
    #: unreadable", and the user deserves to be told which.
    apply_hosts: tuple[str, ...] = ()

    @abstractmethod
    async def apply(
        self, application: Any, job: Any, profile: Any, credential: Any
    ) -> dict[str, str]:
        """Attempt the application. Must never raise; return a result dict."""
        raise NotImplementedError

    def missing_requirements(self, profile: Any) -> list[str]:
        """Fields the ATS will reject the form without."""
        missing: list[str] = []
        if not contact_email(profile):
            missing.append("email address")
        if not full_name(profile):
            missing.append("full name")
        return missing

    # --- Sign-in / sign-up ------------------------------------------------
    #
    # Some ATSes (Workday, iCIMS, Taleo) will not show an application form to an
    # anonymous visitor. Preference order when we hit that wall:
    #   1. a credential the user stored themselves;
    #   2. if the user opted in, an account WE create with their managed alias
    #      (adapter must declare signup selectors);
    #   3. park for the user to handle.
    # CAPTCHA/bot-check handling is unchanged: a challenge anywhere in either
    # flow parks the application. We never solve or evade one.

    #: True when this ATS always gates the form behind a sign-in.
    requires_login: bool = False

    #: Selectors for the sign-in form. An adapter without these cannot log in.
    login_email_selectors: list[str] = []
    login_password_selectors: list[str] = []
    login_submit_selectors: list[str] = []
    #: Presence of any of these means "you must sign in first".
    login_wall_selectors: list[str] = []
    #: Presence of any of these is proof the sign-in worked.
    signed_in_selectors: list[str] = []

    #: Selectors for the account-creation form. Empty = this ATS has no
    #: signup flow we can drive; registration is skipped and we park.
    signup_email_selectors: list[str] = []
    signup_password_selectors: list[str] = []
    signup_confirm_password_selectors: list[str] = []
    signup_submit_selectors: list[str] = []
    #: Link/button that switches the login page to the signup form.
    signup_link_selectors: list[str] = []

    def supports_signup(self) -> bool:
        return bool(self.signup_email_selectors and self.signup_password_selectors)

    def login_url(self, apply_url: str) -> str | None:
        """Where to sign in, derived from the posting URL.

        ``None`` means "sign in on the page we are already on".
        """
        return None

    async def needs_login(self, page: Page) -> bool:
        """Whether this page is refusing to show the form until we sign in."""
        if self.login_wall_selectors:
            try:
                for selector in self.login_wall_selectors:
                    el = await page.query_selector(selector)
                    if el is not None and await el.is_visible():
                        return True
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("login_wall_probe_failed", error=str(exc)[:200])
        text = await _visible_text(page)
        return any(marker in text for marker in LOGIN_WALL_TEXT_MARKERS)

    async def signed_in(self, page: Page) -> bool:
        """Whether the sign-in actually took.

        Same principle as :meth:`confirm`: a clicked button proves nothing. If an
        adapter declares no proof selector we cannot claim success, so we don't.
        """
        if not self.signed_in_selectors:
            return False
        for selector in self.signed_in_selectors:
            try:
                el = await page.query_selector(selector)
                if el is not None:
                    return True
            except Exception as exc:  # pragma: no cover
                log.debug("signed_in_probe_failed", error=str(exc)[:200])
        return False

    async def perform_login(
        self, page: Page, credential: Any, apply_url: str
    ) -> dict[str, str] | None:
        """Sign in with a stored credential. Returns ``None`` on success.

        On failure returns the result dict the caller should hand back — always
        a park, never a retry loop, because repeatedly guessing a password is
        how an account gets locked.
        """
        if not (self.login_password_selectors and self.login_email_selectors):
            return _result(STATUS_NEEDS_INFO, "login_not_supported")

        from app.core.security import decrypt_secret

        try:
            password = decrypt_secret(credential.encrypted_password)
        except Exception:  # noqa: BLE001 - wrong key / corrupt ciphertext
            log.warning("credential_decrypt_failed_in_apply")
            return _result(STATUS_NEEDS_INFO, "credential_unreadable")

        target = self.login_url(apply_url)
        if target and target != page.url:
            try:
                await page.goto(
                    target, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS
                )
            except Exception:
                return _result(STATUS_NEEDS_INFO, "login_page_unreachable")

        if await detect_captcha(page):
            return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")

        got_email = await fill_first(
            page, self.login_email_selectors, credential.login_email
        )
        got_password = await fill_first(page, self.login_password_selectors, password)
        # Drop the plaintext as soon as it is on the page.
        del password
        if not (got_email and got_password):
            return _result(STATUS_NEEDS_INFO, "login_form_not_recognised")

        clicked = False
        for selector in self.login_submit_selectors:
            try:
                el = await page.query_selector(selector)
                if el is not None and await el.is_visible() and await el.is_enabled():
                    await el.click()
                    clicked = True
                    break
            except Exception as exc:  # pragma: no cover
                log.debug("login_submit_failed", selector=selector, error=str(exc)[:200])
        if not clicked:
            return _result(STATUS_NEEDS_INFO, "login_form_not_recognised")

        try:
            await page.wait_for_load_state("networkidle", timeout=CONFIRM_TIMEOUT_MS)
        except Exception as exc:  # pragma: no cover
            log.debug("login_wait_timeout", error=str(exc)[:200])

        if await detect_captcha(page):
            return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")
        if not await self.signed_in(page):
            # Could be a wrong password, an MFA prompt, or a changed layout. All
            # three are the user's to resolve, and none is worth a second try.
            log.info("ats_login_unconfirmed", ats_type=self.ats_type)
            return _result(STATUS_NEEDS_INFO, "login_failed")

        # Back to the posting, now as a signed-in visitor.
        if page.url != apply_url:
            try:
                await page.goto(
                    apply_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS
                )
            except Exception:
                return _result(STATUS_FAILED, "navigation_failed")
        return None

    async def perform_registration(
        self, page: Page, email: str, password: str
    ) -> dict[str, str] | None:
        """Create an account with the managed alias. ``None`` on success.

        Success here means "the form was submitted without a challenge", not
        "the account works" — that is only proven when the verification mail
        arrives and a later sign-in succeeds. One attempt, no retries: retrying
        a signup is how duplicate-account lockouts happen.
        """
        if not self.supports_signup():
            return _result(STATUS_NEEDS_INFO, "credential_required")

        # Some sites land on the login form with a "create account" toggle.
        for selector in self.signup_link_selectors:
            try:
                el = await page.query_selector(selector)
                if el is not None and await el.is_visible():
                    await el.click()
                    break
            except Exception as exc:  # pragma: no cover
                log.debug("signup_link_failed", selector=selector, error=str(exc)[:200])

        if await detect_captcha(page):
            return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")

        filled_email = await fill_first(page, self.signup_email_selectors, email)
        filled_pw = await fill_first(page, self.signup_password_selectors, password)
        await fill_first(page, self.signup_confirm_password_selectors, password)
        if not (filled_email and filled_pw):
            return _result(STATUS_NEEDS_INFO, "signup_form_not_recognised")

        if await detect_captcha(page):
            return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")

        submitted = False
        for selector in self.signup_submit_selectors:
            try:
                el = await page.query_selector(selector)
                if el is not None and await el.is_visible() and await el.is_enabled():
                    await el.click()
                    submitted = True
                    break
            except Exception as exc:  # pragma: no cover
                log.debug("signup_submit_failed", selector=selector, error=str(exc)[:200])
        if not submitted:
            return _result(STATUS_NEEDS_INFO, "signup_form_not_recognised")

        try:
            await page.wait_for_load_state("networkidle", timeout=CONFIRM_TIMEOUT_MS)
        except Exception as exc:  # pragma: no cover - some sites never go idle
            log.debug("signup_idle_wait_timeout", error=str(exc)[:120])
        if await detect_captcha(page):
            return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")
        return None

    async def run_standard_flow(
        self, application: Any, job: Any, profile: Any, credential: Any
    ) -> dict[str, str]:
        """Shared navigate -> fill -> (captcha check) -> submit -> CONFIRM flow."""
        apply_url = getattr(job, "apply_url", None)
        if not apply_url:
            return _result(STATUS_FAILED, "missing_apply_url")

        # Refuse to send an application the employer cannot act on. Previously
        # the email selector read a field the Profile model never had, so every
        # submission went out with no contact address.
        missing = self.missing_requirements(profile)
        if missing:
            return _result(
                STATUS_NEEDS_INFO,
                f"Add your {' and '.join(missing)} to your profile before applying.",
            )

        resume_path = await resolve_resume_path(application)
        try:
            async with launch_context() as context:
                page = await context.new_page()
                try:
                    await page.goto(
                        apply_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS
                    )
                except Exception:
                    return _result(STATUS_FAILED, "navigation_failed")

                # Guardrail: bail out the moment a challenge is present.
                if await detect_captcha(page):
                    return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")

                # Did we actually land on the ATS? Employers can point their
                # board at their own careers site, which has entirely different
                # markup (or no form at all). That is not a parsing failure and
                # must not be reported as one.
                if self.apply_hosts:
                    landed = _host_of(page.url)
                    if landed and not _host_matches(landed, self.apply_hosts):
                        log.info(
                            "apply_redirected_off_ats",
                            ats_type=self.ats_type,
                            expected=self.apply_hosts,
                            landed=landed,
                        )
                        return _result(STATUS_NEEDS_INFO, "employer_hosts_own_form")

                # Some ATSes hide the form behind a sign-in. Use the credential
                # the user stored for THIS site, or park — we never register.
                if self.requires_login or await self.needs_login(page):
                    if credential is None:
                        # Opted-in users get an account created for them with
                        # their managed alias — no user password involved.
                        outcome = await self._register_managed_account(
                            page, profile, apply_url
                        )
                        return outcome
                    failure = await self.perform_login(page, credential, apply_url)
                    if failure is not None:
                        return failure

                # The form is mounted by JS on every ATS we support, so wait for
                # it before reading the DOM. Without this every React-rendered
                # form looked unrecognisable.
                ready = await wait_for_form(
                    page,
                    [*self.email_selectors, *self.name_selectors,
                     *self.first_name_selectors],
                    FORM_READY_TIMEOUT_MS,
                )
                if not ready:
                    return _result(STATUS_NEEDS_INFO, "application_form_not_recognised")

                filled = await self.fill_form(page, profile, resume_path)
                # Cover letter: fill the textarea if the form has one and we
                # generated a letter for this application.
                letter = getattr(application, "cover_letter", None)
                if letter and self.cover_letter_selectors:
                    filled["cover_letter"] = await fill_first(
                        page, self.cover_letter_selectors, letter
                    )
                if not filled.get("email"):
                    # The form has no field we recognise — submitting blind would
                    # produce an incomplete application.
                    return _result(STATUS_NEEDS_INFO, "application_form_not_recognised")

                # Re-check right before the irreversible submit click.
                if await detect_captcha(page):
                    return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")

                submitted = await self.submit(page)
                if not submitted:
                    result = _result(STATUS_NEEDS_INFO, "submit_control_not_found")
                    result["filled"] = filled  # type: ignore[assignment]
                    return result

                result = await self.confirm(page)
                # Hand back what was filled so the application row can show the
                # user that the automation did its part.
                result["filled"] = filled  # type: ignore[assignment]
                return result
        except ImportError:
            # Optional automation extra is not installed in this environment.
            return _result(STATUS_NEEDS_INFO, "automation_unavailable")
        except Exception as exc:  # pragma: no cover - never crash the worker
            log.warning("ats_apply_error", ats_type=self.ats_type, error=str(exc))
            return _result(STATUS_FAILED, "adapter_error")
        finally:
            if resume_path and _file_exists(resume_path):
                _safe_remove(resume_path)

    async def _register_managed_account(
        self, page: Page, profile: Any, apply_url: str
    ) -> dict[str, str]:
        """Try to create an account for an opted-in user; always returns a park.

        Even on success the application cannot proceed this run — the site will
        not accept a sign-in until its verification mail (delivered to the
        managed alias) is followed. The inbound-email pipeline flips the
        credential to active and re-queues the application.
        """
        from app.models.user import User
        from app.services.apply_email import aliases_enabled, create_managed_credential

        user = await User.get(getattr(profile, "user_id", None))
        if (
            user is None
            or not user.auto_create_accounts
            or not aliases_enabled()
            or not self.supports_signup()
        ):
            return _result(STATUS_NEEDS_INFO, "credential_required")

        site_domain = _host_of(apply_url)
        created = await create_managed_credential(user, site_domain)
        if created is None:
            # A credential already exists for this site (possibly still pending
            # verification) — nothing further to create.
            return _result(STATUS_NEEDS_INFO, "verification_pending")
        credential_row, password = created

        failure = await self.perform_registration(page, credential_row.login_email, password)
        if failure is not None:
            # The signup never went through, so the stored credential describes
            # an account that does not exist. Remove it or the next run would
            # "sign in" with it and park on login_failed instead of retrying.
            await credential_row.delete()
            return failure

        log.info(
            "managed_account_registered",
            ats_type=self.ats_type,
            site=credential_row.site_domain,
        )
        return _result(STATUS_NEEDS_INFO, "verification_pending")

    async def confirm(self, page: Page) -> dict[str, str]:
        """Decide the outcome from what the page actually shows after submit.

        Reporting ``submitted`` on the strength of a click alone produced false
        successes whenever the form bounced on validation.
        """
        try:
            await page.wait_for_load_state("networkidle", timeout=CONFIRM_TIMEOUT_MS)
        except Exception as exc:  # pragma: no cover - some ATSes never go idle
            log.debug("confirm_wait_timeout", error=str(exc)[:200])

        # A challenge can appear only on the confirmation attempt.
        if await detect_captcha(page):
            return _result(STATUS_NEEDS_INFO, "captcha_or_botcheck")

        text = await _visible_text(page)
        if any(marker in text for marker in CONFIRMATION_MARKERS):
            return _result(STATUS_SUBMITTED, f"submitted_via_{self.ats_type}")

        if any(marker in text for marker in VALIDATION_MARKERS):
            return _result(
                STATUS_NEEDS_INFO,
                "The form needs details we don't have — please finish it yourself.",
            )

        # No positive confirmation: park it rather than claim a success we
        # cannot evidence. The user can complete it from the apply URL.
        log.info("ats_no_confirmation", ats_type=self.ats_type)
        return _result(STATUS_NEEDS_INFO, "submission_not_confirmed")

    async def fill_form(
        self, page: Page, profile: Any, resume_path: str | None
    ) -> dict[str, bool]:
        """Fill the standard fields. Returns which ones actually took a value."""
        name = full_name(profile)
        first = getattr(profile, "first_name", None)
        last = getattr(profile, "last_name", None)

        prefs = getattr(profile, "preferences", None) or {}

        filled = {
            "name": await fill_first(page, self.name_selectors, name),
            "first_name": await fill_first(page, self.first_name_selectors, first),
            "last_name": await fill_first(page, self.last_name_selectors, last),
            # Profile.email is the application contact address.
            "email": await fill_first(
                page, self.email_selectors, contact_email(profile)
            ),
            "phone": await fill_first(
                page, self.phone_selectors, getattr(profile, "phone", None)
            ),
            "resume": await upload_first(page, self.resume_selectors, resume_path),
            "linkedin": await fill_first(
                page, self.linkedin_selectors, prefs.get("linkedin_url")
            ),
            "website": await fill_first(
                page, self.website_selectors, prefs.get("website_url")
            ),
        }

        # Voluntary EEO answers. Only ever replayed onto a form the user chose to
        # submit, and only for questions they actually answered — an unanswered
        # field is left for the employer's own default, never guessed.
        demographics = getattr(profile, "demographics", None)
        if demographics is not None:
            for field, selectors in self.demographic_selectors.items():
                answer = getattr(demographics, field, None)
                if not answer:
                    continue
                filled[f"eeo_{field}"] = await fill_choice(
                    page, selectors, field, answer
                )
        return filled

    async def submit(self, page: Page) -> bool:
        """Click the first matching submit control. Best-effort.

        Selector lists are ordered most-specific first, and generic fallbacks are
        scoped to the form so we cannot click an unrelated control (a newsletter
        signup, a search button) on the same page.
        """
        for selector in self.submit_selectors:
            try:
                el = await page.query_selector(selector)
                if el is not None and await el.is_visible() and await el.is_enabled():
                    await el.click()
                    return True
            except Exception as exc:  # pragma: no cover
                log.debug("submit_selector_failed", selector=selector, error=str(exc)[:200])
                continue
        return False
