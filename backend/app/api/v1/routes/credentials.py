"""Reveal a stored site credential, behind a re-authentication step.

Aptil generates a unique strong password per job site and stores it encrypted.
The user never chose those passwords, so they must be able to read them back —
otherwise they cannot log into the ATS account we created on their behalf.

Handing them out is still a sensitive operation, so it is gated:
  * the account password must be re-entered on every reveal (a stolen access
    token alone is not enough);
  * OAuth-only accounts, which have no password to re-enter, cannot reveal at
    all — they set a password first;
  * reveals are rate limited per user and written to the audit log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.core.ratelimit import RateLimiter
from app.core.security import decrypt_secret, verify_password
from app.models.profile import SiteCredential
from app.models.user import User

router = APIRouter()
log = get_logger(__name__)


class RevealRequest(BaseModel):
    # Re-authentication: possession of a valid session is not sufficient to
    # read a stored secret back out.
    password: str = Field(min_length=1, max_length=128)


class RevealedCredential(BaseModel):
    id: uuid.UUID
    site_domain: str
    login_email: str
    password: str
    revealed_at: datetime


@router.post(
    "/{credential_id}/reveal",
    response_model=RevealedCredential,
    dependencies=[Depends(RateLimiter(times=10, seconds=3600, scope="user"))],
)
async def reveal_credential(
    credential_id: uuid.UUID,
    payload: RevealRequest,
    user: User = Depends(get_current_user),
):
    """Return the plaintext password for one stored site credential."""
    if not user.hashed_password:
        # Nothing to re-authenticate against.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Set an account password first — we re-check it before showing "
                "a stored site password."
            ),
        )
    if not verify_password(payload.password, user.hashed_password):
        log.warning("credential_reveal_bad_password", user_id=str(user.id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Password is incorrect"
        )

    cred = await SiteCredential.find_one(
        SiteCredential.id == credential_id,
        SiteCredential.user_id == user.id,
        SiteCredential.tenant_id == user.tenant_id,
    )
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")

    try:
        plaintext = decrypt_secret(cred.encrypted_password)
    except Exception as exc:  # noqa: BLE001 - wrong key / corrupt ciphertext
        log.error("credential_decrypt_failed", credential_id=str(cred.id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "This credential could not be decrypted. It may have been saved "
                "under a different CREDENTIAL_ENCRYPTION_KEY."
            ),
        ) from exc

    # Audit trail: reads of a secret are worth recording even though the reader
    # is its owner.
    log.info(
        "credential_revealed",
        user_id=str(user.id),
        credential_id=str(cred.id),
        site_domain=cred.site_domain,
    )
    return RevealedCredential(
        id=cred.id,
        site_domain=cred.site_domain,
        login_email=cred.login_email,
        password=plaintext,
        revealed_at=datetime.now(UTC),
    )
