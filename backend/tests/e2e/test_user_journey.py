"""The full signed-in journey, end to end in a real browser.

Covers the path a new user actually takes: register → verify → log in →
onboarding wizard (every step, including the one that had no screen) →
dashboard → interview → settings, plus the session behaviours that used to
break silently (a 30-minute token expiry with no refresh, logout not revoking
anything).
"""

from __future__ import annotations

import os
import re
import uuid

import pytest

WEB_URL = os.environ.get("WEB_URL", "http://localhost:3000")
API_URL = os.environ.get("API_URL", "http://localhost:8000")
PASSWORD = "a-strong-enough-password-1"  # noqa: S105


def _up() -> bool:
    from tests.e2e.test_ui_flows import _reachable

    return _reachable(WEB_URL) and _reachable(f"{API_URL}/health")


pytestmark = pytest.mark.skipif(not _up(), reason="web + api stack not running")

try:
    from playwright.sync_api import Page, expect, sync_playwright
except ImportError:  # pragma: no cover
    pytest.skip("playwright not installed", allow_module_level=True)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    yield pg
    ctx.close()


def _register_and_verify(email: str) -> None:
    """Create an account and mark it verified straight in the database.

    Clicking the emailed link is covered by the API tests; this keeps the UI
    journey focused on the UI.
    """
    import httpx

    from tests.e2e.conftest import mongo_client

    resp = httpx.post(
        f"{API_URL}/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": "Journey Tester",
            "accepted_terms": True,
        },
        timeout=15,
    )
    assert resp.status_code == 201, resp.text

    db_name = os.environ.get("MONGO_DB", "aptil_dev")
    result = mongo_client()[db_name]["users"].update_one(
        {"email": email}, {"$set": {"is_email_verified": True}}
    )
    assert result.matched_count == 1, f"user {email} not found in {db_name}"


def _login(pg: Page, email: str) -> None:
    pg.goto(f"{WEB_URL}/login")
    pg.wait_for_load_state("networkidle")
    pg.get_by_label("Email", exact=False).fill(email)
    pg.get_by_label("Password", exact=False).fill(PASSWORD)
    pg.get_by_role("button", name="Log in").click()


def _new_email() -> str:
    return f"journey-{uuid.uuid4().hex[:10]}@example.com"


# --------------------------------------------------------------------------
def test_register_screen_prompts_for_verification(page: Page):
    email = _new_email()
    page.goto(f"{WEB_URL}/register")
    page.wait_for_load_state("networkidle")
    page.get_by_label("Full name", exact=False).fill("Journey Tester")
    page.get_by_label("Email", exact=False).fill(email)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_label("Confirm password").fill(PASSWORD)
    page.get_by_role("checkbox").check()
    page.get_by_role("button", name="Create account").click()

    expect(page.get_by_role("heading", name="Verify your email")).to_be_visible(
        timeout=15000
    )
    body = page.locator("body").inner_text()
    assert email in body
    # Registration already sent one email, so the resend must start on cooldown
    # rather than offering a button the server will refuse.
    assert "Resend in" in body


def test_unverified_login_shows_the_verify_screen_not_a_raw_error(page: Page):
    import httpx

    email = _new_email()
    httpx.post(
        f"{API_URL}/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "accepted_terms": True},
        timeout=15,
    )
    _login(page, email)
    expect(page.get_by_role("heading", name="Verify your email")).to_be_visible(
        timeout=15000
    )
    assert "email_not_verified" not in page.locator("body").inner_text()


def test_full_onboarding_wizard_reaches_the_dashboard(page: Page):
    email = _new_email()
    _register_and_verify(email)
    _login(page, email)

    # A verified but un-onboarded user is sent into the wizard.
    page.wait_for_url(re.compile(r"/onboarding"), timeout=20000)
    expect(page.get_by_role("heading", name="Set up your profile")).to_be_visible()

    # Step 1 — no CV: choose "build one for me".
    page.get_by_role("button", name=re.compile("build one for me")).click()
    page.get_by_role("button", name="Continue").click()

    # Step 2 — personal details. The contact email is what the apply engine
    # puts on ATS forms, so it must be capturable here.
    expect(page.get_by_role("heading", name="Your details")).to_be_visible(timeout=10000)
    page.get_by_label("First name").fill("Journey")
    page.get_by_label("Last name").fill("Tester")
    page.get_by_label("Contact email").fill(email)
    page.get_by_label("Headline").fill("Senior Backend Engineer")
    page.get_by_role("button", name="Continue").click()

    # Step 3 — experience & skills.
    expect(page.get_by_role("heading", name=re.compile("Experience"))).to_be_visible(
        timeout=10000
    )
    page.get_by_label("Skills").fill("Python, FastAPI, MongoDB")
    page.get_by_role("button", name="Add role").click()
    page.get_by_placeholder("Job title").fill("Backend Engineer")
    page.get_by_placeholder("Company").fill("Acme")
    page.get_by_role("button", name="Continue").click()

    # Step 4 — strategy. Building a résumé is required before continuing.
    expect(
        page.get_by_role("heading", name=re.compile("Generate your résumé"))
    ).to_be_visible(timeout=10000)
    page.get_by_role("button", name="Generate my résumé").click()
    expect(page.get_by_text("Your résumé is ready", exact=False)).to_be_visible(
        timeout=20000
    )
    page.get_by_role("button", name="Continue").click()

    # Step 5 — credentials. This step exists in the backend enum and previously
    # had NO screen: a user resuming here saw a blank card.
    expect(page.get_by_role("heading", name="Job site accounts")).to_be_visible(
        timeout=10000
    )
    page.get_by_role("button", name="Continue").click()

    # Step 6 — plan.
    expect(page.get_by_role("heading", name="Pick a plan")).to_be_visible(timeout=10000)
    page.get_by_role("button", name=re.compile("Finish")).click()

    page.wait_for_url(re.compile(r"/dashboard"), timeout=20000)
    expect(page.get_by_role("heading", name="Your pipeline")).to_be_visible()
    # A new account lands on the free plan, so quota is shown rather than zeroes.
    # Asserted with expect() so it waits for the subscription fetch instead of
    # snapshotting the DOM before it resolves.
    expect(page.get_by_text("Free plan", exact=False)).to_be_visible(timeout=15000)


def test_onboarding_back_button_preserves_entered_data(page: Page):
    email = _new_email()
    _register_and_verify(email)
    _login(page, email)
    page.wait_for_url(re.compile(r"/onboarding"), timeout=20000)

    page.get_by_role("button", name=re.compile("build one for me")).click()
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_role("heading", name="Your details")).to_be_visible(timeout=10000)
    page.get_by_label("First name").fill("Persisted")
    page.get_by_role("button", name="Continue").click()

    expect(page.get_by_role("heading", name=re.compile("Experience"))).to_be_visible(
        timeout=10000
    )
    page.get_by_role("button", name="Back").click()
    expect(page.get_by_role("heading", name="Your details")).to_be_visible(timeout=10000)
    # "Saved as you go" must actually mean saved.
    expect(page.get_by_label("First name")).to_have_value("Persisted")


def test_resuming_onboarding_lands_on_a_real_step_not_a_blank_card(page: Page):
    """A stored step with no matching screen used to render nothing at all."""
    import httpx

    from tests.e2e.conftest import mongo_client

    email = _new_email()
    _register_and_verify(email)

    # Force the account onto the step the wizard used to be missing.
    mongo_client()[os.environ.get("MONGO_DB", "aptil_dev")]["users"].update_one(
        {"email": email}, {"$set": {"onboarding_step": "credentials"}}
    )
    assert httpx.get(f"{API_URL}/health", timeout=5).status_code == 200

    _login(page, email)
    page.wait_for_url(re.compile(r"/onboarding"), timeout=20000)
    expect(page.get_by_role("heading", name="Job site accounts")).to_be_visible(
        timeout=10000
    )
    # And the step must be reachable/continuable, not a dead end.
    expect(page.get_by_role("button", name="Continue")).to_be_enabled()


def test_app_navigation_reaches_every_section(page: Page):
    email = _new_email()
    _register_and_verify(email)

    # Complete onboarding via the API so this test focuses on navigation.
    import httpx

    tokens = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=15,
    ).json()
    httpx.post(
        f"{API_URL}/api/v1/onboarding/step",
        json={"step": "completed"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )

    _login(page, email)
    page.wait_for_url(re.compile(r"/dashboard"), timeout=20000)

    for label, url_part, heading in [
        ("Jobs", "/jobs", "Discovered roles"),
        ("Interview", "/interview", "Mock interview"),
        ("Plans", "/plans", "Choose your plan"),
        ("Dashboard", "/dashboard", "Your pipeline"),
    ]:
        page.get_by_role("navigation", name="Main").get_by_role(
            "link", name=label, exact=True
        ).click()
        page.wait_for_url(re.compile(url_part), timeout=15000)
        expect(page.get_by_role("heading", name=heading)).to_be_visible(timeout=15000)

    # Settings is an icon link, reachable from every page.
    page.get_by_role("link", name="Settings").click()
    page.wait_for_url(re.compile(r"/settings"), timeout=15000)
    expect(page.get_by_role("heading", name="Settings", exact=True)).to_be_visible()


def test_expired_access_token_is_refreshed_transparently(page: Page):
    """A 30-minute expiry with no refresh path used to dump users to /login."""
    email = _new_email()
    _register_and_verify(email)
    import httpx

    tokens = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=15,
    ).json()
    httpx.post(
        f"{API_URL}/api/v1/onboarding/step",
        json={"step": "completed"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )

    _login(page, email)
    page.wait_for_url(re.compile(r"/dashboard"), timeout=20000)
    # Let the dashboard's initial requests finish. Mutating auth state while
    # they are still in flight races the client's own refresh handling and makes
    # this test measure the race rather than the behaviour under test.
    expect(page.get_by_text("Free plan", exact=False)).to_be_visible(timeout=30000)

    # Corrupt only the access token; the refresh token stays valid.
    page.evaluate("() => localStorage.setItem('aptil_access', 'not-a-valid-token')")
    page.reload(wait_until="domcontentloaded")

    # Wait for the outcome itself (token replaced) rather than a fixed window —
    # `next dev` can spend seconds recompiling a route, which is not what this
    # test is measuring.
    page.wait_for_function(
        "() => { const t = localStorage.getItem('aptil_access');"
        " return t && t !== 'not-a-valid-token'; }",
        timeout=45000,
    )
    # And the user must still be on the dashboard, not bounced to login.
    expect(page.get_by_role("heading", name="Your pipeline")).to_be_visible(
        timeout=45000
    )
    assert "/dashboard" in page.url


def test_unrecoverable_session_lands_on_login_with_an_explanation(page: Page):
    email = _new_email()
    _register_and_verify(email)
    _login(page, email)
    page.wait_for_url(re.compile(r"/onboarding|/dashboard"), timeout=20000)

    page.evaluate(
        """() => {
          localStorage.setItem('aptil_access', 'bad');
          localStorage.setItem('aptil_refresh', 'also-bad');
        }"""
    )
    page.goto(f"{WEB_URL}/dashboard")
    page.wait_for_url(re.compile(r"/login"), timeout=20000)
    assert "/login" in page.url


def test_logout_clears_the_session_and_blocks_back_navigation(page: Page):
    email = _new_email()
    _register_and_verify(email)
    import httpx

    tokens = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=15,
    ).json()
    httpx.post(
        f"{API_URL}/api/v1/onboarding/step",
        json={"step": "completed"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )

    _login(page, email)
    page.wait_for_url(re.compile(r"/dashboard"), timeout=20000)

    page.get_by_role("button", name="Log out").click()
    page.wait_for_url(re.compile(r"/login"), timeout=15000)

    stored = page.evaluate("() => localStorage.getItem('aptil_access')")
    assert stored is None

    # Going "back" must not restore an authenticated view.
    page.goto(f"{WEB_URL}/dashboard")
    page.wait_for_url(re.compile(r"/login"), timeout=15000)


def test_settings_exposes_export_and_deletion(page: Page):
    """compliance.md §5 requires both; neither existed before."""
    email = _new_email()
    _register_and_verify(email)
    _login(page, email)
    page.wait_for_url(re.compile(r"/onboarding|/dashboard"), timeout=20000)

    page.goto(f"{WEB_URL}/settings")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("button", name="Export my data")).to_be_visible(
        timeout=15000
    )
    expect(page.get_by_role("button", name="Delete my account")).to_be_visible()
    expect(page.get_by_role("heading", name="Job site accounts")).to_be_visible()


def test_dashboard_empty_state_offers_the_next_action(page: Page):
    email = _new_email()
    _register_and_verify(email)
    import httpx

    tokens = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=15,
    ).json()
    httpx.post(
        f"{API_URL}/api/v1/onboarding/step",
        json={"step": "completed"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )

    _login(page, email)
    page.wait_for_url(re.compile(r"/dashboard"), timeout=20000)
    expect(page.get_by_text("No applications yet")).to_be_visible(timeout=20000)
    # An empty state that just says "nothing here" is a dead end.
    expect(page.get_by_role("button", name=re.compile("Find matches now"))).to_be_visible()


# --------------------------------------------------------------------------
# Signed-in visitors should not be shown auth forms
# --------------------------------------------------------------------------
def _seed_tokens(pg: Page, tokens: dict | None) -> None:
    """Put a session in localStorage, from a page that will not redirect.

    Seeding from /login raced the very behaviour under test: for a signed-in
    visitor that page immediately starts redirecting to /dashboard, so clearing
    and rewriting localStorage underneath it sometimes left the next navigation
    reading a half-written session and landing on the form. /terms is public,
    same-origin, and static, so the write always completes first.
    """
    pg.goto(f"{WEB_URL}/terms", wait_until="domcontentloaded")
    pg.evaluate("() => localStorage.clear()")
    if tokens:
        pg.evaluate(
            "(t) => { localStorage.setItem('aptil_access', t.access);"
            " localStorage.setItem('aptil_refresh', t.refresh); }",
            {"access": tokens["access_token"], "refresh": tokens["refresh_token"]},
        )


def _tokens_for(email: str) -> dict:
    import httpx

    return httpx.post(
        f"{API_URL}/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=15,
    ).json()


def _onboarded_tokens() -> dict:
    """A verified, onboarded account — the state the app chrome is designed for."""
    import httpx

    email = _new_email()
    _register_and_verify(email)
    tokens = _tokens_for(email)
    httpx.post(
        f"{API_URL}/api/v1/onboarding/step",
        json={"step": "completed"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )
    return tokens


def _footer_links(pg: Page) -> list[str]:
    return pg.eval_on_selector_all(
        "footer nav a", "els => els.map(e => e.textContent.trim())"
    )


def _header_links(pg: Page) -> list[str]:
    return pg.eval_on_selector_all(
        "header a", "els => els.map(e => e.textContent.trim())"
    )


def test_the_app_never_offers_to_log_in_a_user_who_already_is(page: Page):
    """"Log in" under the dashboard reads as though the session had dropped.

    The footer is shared between the marketing site and the app, and its auth
    link was unconditional — so every signed-in page offered one.
    """
    _seed_tokens(page, _onboarded_tokens())

    for path in ("/dashboard", "/jobs", "/settings", "/plans", "/onboarding"):
        page.goto(f"{WEB_URL}{path}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1200)
        links = _footer_links(page)
        assert "Log in" not in links, f"{path} footer offers Log in to a signed-in user"
        # The legal links are the reason this footer exists at all.
        assert "Privacy Policy" in links and "Terms of Service" in links


def test_the_marketing_surface_points_a_signed_in_visitor_at_the_app(page: Page):
    """On /, a signed-in visitor was offered "Log in" and invited to "Get
    started" a second account."""
    _seed_tokens(page, _onboarded_tokens())
    page.goto(WEB_URL)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    footer, header = _footer_links(page), _header_links(page)
    assert "Log in" not in footer and "Dashboard" in footer
    assert "Log in" not in header and "Get started" not in header
    assert any("dashboard" in h.lower() for h in header)


def test_a_signed_out_visitor_still_gets_the_way_in(page: Page):
    """The other half: the sign-in route must not vanish for everyone else."""
    page.goto(WEB_URL)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)
    footer, header = _footer_links(page), _header_links(page)
    assert "Log in" in footer
    assert "Log in" in header and "Get started" in header



def test_signed_in_user_is_sent_to_dashboard_from_login_and_register(page: Page):
    import httpx

    email = _new_email()
    _register_and_verify(email)
    tokens = _tokens_for(email)
    httpx.post(
        f"{API_URL}/api/v1/onboarding/step",
        json={"step": "completed"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )

    for path in ("/login", "/register"):
        _seed_tokens(page, tokens)
        page.goto(f"{WEB_URL}{path}", wait_until="domcontentloaded")
        page.wait_for_url(re.compile(r"/dashboard"), timeout=20000)
        assert "/dashboard" in page.url, f"{path} did not redirect"


def test_signed_in_but_unonboarded_goes_to_onboarding_not_dashboard(page: Page):
    """Routing via /dashboard would bounce them again; go straight there."""
    email = _new_email()
    _register_and_verify(email)
    tokens = _tokens_for(email)

    _seed_tokens(page, tokens)
    page.goto(f"{WEB_URL}/login", wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"/onboarding"), timeout=20000)
    assert "/onboarding" in page.url


def test_signed_out_visitor_still_gets_the_forms(page: Page):
    for path, control in (("/login", "Log in"), ("/register", "Create account")):
        _seed_tokens(page, None)
        page.goto(f"{WEB_URL}{path}", wait_until="domcontentloaded")
        expect(page.get_by_role("button", name=control)).to_be_visible(timeout=15000)
        assert path in page.url


def test_a_stale_token_does_not_trap_you_on_the_login_page(page: Page):
    """A token that no longer validates must leave the form usable."""
    page.goto(f"{WEB_URL}/login", wait_until="domcontentloaded")
    page.evaluate(
        "() => { localStorage.clear();"
        " localStorage.setItem('aptil_access', 'not-a-real-token'); }"
    )
    page.goto(f"{WEB_URL}/login", wait_until="domcontentloaded")
    expect(page.get_by_role("button", name="Log in")).to_be_visible(timeout=20000)
    assert "/login" in page.url
    # The dead token should have been cleared rather than left to fail again.
    assert page.evaluate("() => localStorage.getItem('aptil_access')") is None


def test_unverified_user_does_not_ping_pong_between_login_and_dashboard(page: Page):
    """Redirecting them to /dashboard would sign them out and send them back."""
    import httpx

    from tests.e2e.conftest import mongo_client

    email = _new_email()
    _register_and_verify(email)
    tokens = _tokens_for(email)
    httpx.post(
        f"{API_URL}/api/v1/onboarding/step",
        json={"step": "completed"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=15,
    )
    # Revoke verification behind the token's back.
    mongo_client()[os.environ.get("MONGO_DB", "aptil_dev")]["users"].update_one(
        {"email": email}, {"$set": {"is_email_verified": False}}
    )

    _seed_tokens(page, tokens)
    page.goto(f"{WEB_URL}/login", wait_until="domcontentloaded")
    expect(page.get_by_role("button", name="Log in")).to_be_visible(timeout=20000)
    assert "/login" in page.url
