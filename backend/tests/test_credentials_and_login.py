"""Envelope encryption, key rotation, and the sign-in-never-sign-up rule.

These cover the two things that have no other coverage: the credential
at-rest format (which has to stay readable across a key rotation), and the ATS
login hook (which handles a user's real password and must never guess twice).
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core import security as sec
from app.core.config import settings
from app.services.ats import get_ats_adapter, supported_ats_types
from app.services.ats.base import AtsAdapter
from app.services.ats.workday import WorkdayAdapter


@pytest.fixture
def keys(monkeypatch):
    """Two independent KEKs, applied to settings for the duration of a test."""
    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", k1)
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEYS_OLD", "")
    return k1, k2


# --------------------------------------------------------------------------
# Envelope encryption
# --------------------------------------------------------------------------
def test_secret_round_trips_and_is_not_stored_in_the_clear(keys):
    token = sec.encrypt_secret("per-site-password")
    assert token.startswith("v2.")
    assert "per-site-password" not in token
    assert sec.decrypt_secret(token) == "per-site-password"


def test_each_secret_gets_its_own_data_key(keys):
    """Identical plaintexts must not produce identical ciphertexts.

    Beyond the usual argument, it means compromising one data key exposes
    exactly one credential rather than every credential encrypted with it.
    """
    a, b = sec.encrypt_secret("same"), sec.encrypt_secret("same")
    assert a != b
    assert a.split(".")[2] != b.split(".")[2]  # different wrapped DEKs


def test_pre_envelope_ciphertext_still_decrypts(keys):
    """Rows written before envelope encryption existed must keep working."""
    k1, _ = keys
    legacy = Fernet(k1.encode()).encrypt(b"legacy").decode()
    assert sec.decrypt_secret(legacy) == "legacy"
    assert sec.needs_rewrap(legacy) is True


def test_rotation_rewraps_the_data_key_without_touching_the_payload(keys, monkeypatch):
    k1, k2 = keys
    token = sec.encrypt_secret("secret")

    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", k2)
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEYS_OLD", k1)

    assert sec.needs_rewrap(token) is True
    assert sec.decrypt_secret(token) == "secret", "old-key rows must still open"

    rotated = sec.rewrap_secret(token)
    assert sec.needs_rewrap(rotated) is False
    assert sec.decrypt_secret(rotated) == "secret"
    # The encrypted password itself is copied, so rotation never materialises
    # a plaintext and never rewrites the bulk of the record.
    assert rotated.split(".")[3] == token.split(".")[3]


def test_retiring_a_key_actually_retires_it(keys, monkeypatch):
    """Once the old key is dropped, anything still on it is unreadable."""
    k1, k2 = keys
    stale = sec.encrypt_secret("secret")
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", k2)
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEYS_OLD", k1)
    rotated = sec.rewrap_secret(stale)

    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEYS_OLD", "")
    assert sec.decrypt_secret(rotated) == "secret"
    with pytest.raises(InvalidToken):
        sec.decrypt_secret(stale)


def test_legacy_row_upgrades_to_an_envelope(keys):
    k1, _ = keys
    legacy = Fernet(k1.encode()).encrypt(b"legacy").decode()
    upgraded = sec.rewrap_secret(legacy)
    assert upgraded.startswith("v2.")
    assert sec.decrypt_secret(upgraded) == "legacy"
    assert sec.needs_rewrap(upgraded) is False


# --------------------------------------------------------------------------
# The sign-in hook
# --------------------------------------------------------------------------
class _Element:
    def __init__(self, visible=True, enabled=True):
        self._visible, self._enabled = visible, enabled
        self.filled = None
        self.clicked = False

    async def is_visible(self):
        return self._visible

    async def is_enabled(self):
        return self._enabled

    async def fill(self, value):
        self.filled = value

    async def click(self):
        self.clicked = True


class _Page:
    """Just enough Playwright Page to drive perform_login."""

    def __init__(self, elements: dict, text: str = "", url: str = "https://x/job/1"):
        self.elements = elements
        self.text = text
        self.url = url
        self.visited: list[str] = []

    async def query_selector(self, selector):
        return self.elements.get(selector)

    async def inner_text(self, _selector):
        return self.text

    async def goto(self, url, **_kwargs):
        self.visited.append(url)
        self.url = url

    async def wait_for_load_state(self, *_a, **_k):
        return None


class _Adapter(AtsAdapter):
    ats_type = "test"
    login_email_selectors = ["#user"]
    login_password_selectors = ["#pass"]
    login_submit_selectors = ["#go"]
    signed_in_selectors = ["#signout"]

    async def apply(self, application, job, profile, credential):  # pragma: no cover
        raise NotImplementedError


class _Credential:
    def __init__(self, token):
        self.login_email = "user@example.com"
        self.encrypted_password = token


@pytest.fixture
def adapter():
    return _Adapter()


async def test_login_fills_and_confirms_with_a_signed_in_marker(keys, adapter):
    cred = _Credential(sec.encrypt_secret("s3cret"))
    user, pw, go = _Element(), _Element(), _Element()
    page = _Page({"#user": user, "#pass": pw, "#go": go, "#signout": _Element()})

    assert await adapter.perform_login(page, cred, "https://x/job/1") is None
    assert user.filled == "user@example.com"
    assert pw.filled == "s3cret"
    assert go.clicked is True


async def test_login_without_proof_parks_instead_of_assuming_success(keys, adapter):
    """A clicked button is not evidence — same rule as submission."""
    cred = _Credential(sec.encrypt_secret("s3cret"))
    page = _Page({"#user": _Element(), "#pass": _Element(), "#go": _Element()})
    result = await adapter.perform_login(page, cred, "https://x/job/1")
    assert result == {"status": "needs_info", "detail": "login_failed"}


async def test_login_stops_at_a_captcha(keys, adapter):
    cred = _Credential(sec.encrypt_secret("s3cret"))
    page = _Page(
        {"#user": _Element(), "#pass": _Element(), "#go": _Element()},
        text="please verify you are human",
    )
    result = await adapter.perform_login(page, cred, "https://x/job/1")
    assert result == {"status": "needs_info", "detail": "captcha_or_botcheck"}


async def test_unrecognised_login_form_parks_without_clicking_anything(keys, adapter):
    cred = _Credential(sec.encrypt_secret("s3cret"))
    go = _Element()
    page = _Page({"#user": _Element(), "#go": go})  # no password field
    result = await adapter.perform_login(page, cred, "https://x/job/1")
    assert result == {"status": "needs_info", "detail": "login_form_not_recognised"}
    assert go.clicked is False


async def test_undecryptable_credential_parks_rather_than_erroring(adapter, monkeypatch):
    monkeypatch.setattr(
        settings, "CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEYS_OLD", "")
    # Encrypted under a key that is no longer configured.
    other = Fernet(Fernet.generate_key()).encrypt(b"x").decode()
    page = _Page({"#user": _Element(), "#pass": _Element(), "#go": _Element()})
    result = await adapter.perform_login(page, _Credential(other), "https://x/job/1")
    assert result == {"status": "needs_info", "detail": "credential_unreadable"}


async def test_an_adapter_with_no_login_selectors_cannot_log_in(keys):
    class _NoLogin(AtsAdapter):
        ats_type = "nologin"

        async def apply(self, *_a):  # pragma: no cover
            raise NotImplementedError

    cred = _Credential(sec.encrypt_secret("s3cret"))
    result = await _NoLogin().perform_login(_Page({}), cred, "https://x/job/1")
    assert result == {"status": "needs_info", "detail": "login_not_supported"}


async def test_login_wall_is_detected_from_page_text(adapter):
    assert await adapter.needs_login(_Page({}, text="you must be signed in")) is True
    assert await adapter.needs_login(_Page({}, text="apply for this role")) is False


# --------------------------------------------------------------------------
# Never register
# --------------------------------------------------------------------------
def test_no_adapter_exposes_a_registration_path():
    """The guardrail is structural: there is nothing to call.

    If someone adds a `register`/`signup` method to an adapter, this fails and
    they have to justify it against docs/compliance.md section 1a.
    """
    banned = ("register", "signup", "sign_up", "create_account")
    for name in supported_ats_types():
        adapter = get_ats_adapter(name)
        for attr in banned:
            assert not hasattr(adapter, attr), f"{name} exposes {attr}()"


async def test_workday_parks_without_a_credential_and_never_launches_a_browser():
    result = await WorkdayAdapter().apply(None, None, None, None)
    assert result == {"status": "needs_info", "detail": "credential_required"}


async def test_workday_is_honest_about_the_multi_step_form():
    result = await WorkdayAdapter().apply(None, None, None, _Credential("x"))
    assert result == {"status": "needs_info", "detail": "multi_step_application"}


def test_workday_login_url_is_derived_from_the_posting_url():
    url = WorkdayAdapter().login_url(
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US/Eng_1"
    )
    assert url == (
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/login"
    )


def test_every_park_reason_maps_to_a_user_action():
    """A reason with no mapping shows the user a generic "needs attention"."""
    from app.workers.tasks.apply import _ACTION_FOR

    for detail in (
        "credential_required",
        "credential_unreadable",
        "login_failed",
        "login_form_not_recognised",
        "login_page_unreachable",
        "login_not_supported",
        "multi_step_application",
    ):
        assert detail in _ACTION_FOR, f"{detail} has no user-facing action"
