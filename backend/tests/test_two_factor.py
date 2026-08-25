"""Two-factor auth: enrolment, the login challenge, and backup codes.

Security-critical, so each gate is pinned: no tokens are issued on a 2FA account
until the second factor is verified, and backup codes are single-use.
"""

from __future__ import annotations

import pyotp

from app.models.user import User
from app.services import twofa
from tests.conftest import requires_mongo
from tests.test_security import _auth, _login, _register

pytestmark = [requires_mongo]


def test_totp_and_backup_code_primitives():
    secret = twofa.new_secret()
    assert twofa.code_valid(secret, pyotp.TOTP(secret).now()) is True
    assert twofa.code_valid(secret, "000000") is False
    plain, hashes = twofa.generate_backup_codes()
    assert len(plain) == len(hashes) == 8
    assert all(p.isdigit() for p in plain)


async def test_full_2fa_enrolment_and_login_challenge(client):
    email = await _register(client)
    tokens = await _login(client, email)

    # 1. setup returns a secret + otpauth URI, but 2FA is not on yet.
    setup = await client.post("/api/v1/auth/2fa/setup", headers=_auth(tokens))
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://")

    me = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert me.json()["two_factor_enabled"] is False

    # 2. a wrong code cannot enable it.
    bad = await client.post(
        "/api/v1/auth/2fa/enable", json={"code": "000000"}, headers=_auth(tokens)
    )
    assert bad.status_code == 400

    # 3. the right code enables it and returns backup codes.
    good = await client.post(
        "/api/v1/auth/2fa/enable",
        json={"code": pyotp.TOTP(secret).now()},
        headers=_auth(tokens),
    )
    assert good.status_code == 200
    backup = good.json()["backup_codes"]
    assert len(backup) == 8

    me2 = await client.get("/api/v1/auth/me", headers=_auth(tokens))
    assert me2.json()["two_factor_enabled"] is True

    # 4. login now withholds tokens and returns a challenge.
    from tests.test_security import PASSWORD

    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    body = login.json()
    assert body.get("two_factor_required") is True
    assert "access_token" not in body
    challenge = body["challenge"]

    # 5. verify with a TOTP code -> real tokens.
    ver = await client.post(
        "/api/v1/auth/2fa/verify",
        json={"challenge": challenge, "code": pyotp.TOTP(secret).now()},
    )
    assert ver.status_code == 200
    assert "access_token" in ver.json()


async def test_backup_code_is_single_use(client):
    email = await _register(client)
    tokens = await _login(client, email)
    setup = await client.post("/api/v1/auth/2fa/setup", headers=_auth(tokens))
    secret = setup.json()["secret"]
    enable = await client.post(
        "/api/v1/auth/2fa/enable",
        json={"code": pyotp.TOTP(secret).now()},
        headers=_auth(tokens),
    )
    backup = enable.json()["backup_codes"]
    user = await User.find_one(User.email == email)

    # First use of a backup code works and consumes it.
    assert await twofa.verify_login(user, backup[0]) is True
    fresh = await User.find_one(User.email == email)
    assert await twofa.verify_login(fresh, backup[0]) is False  # already used
