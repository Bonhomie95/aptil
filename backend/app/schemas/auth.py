"""Auth request/response schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    # Compliance §5: an explicit, recorded consent at signup.
    accepted_terms: bool = Field(
        default=False, description="User accepted the Terms and Privacy Policy"
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    expires_in: int = 0


class RefreshRequest(BaseModel):
    refresh_token: str = Field(max_length=4096)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=4096)
    # Revoke every session for the account, not just this device.
    all_devices: bool = False


class VerifyEmailRequest(BaseModel):
    token: str = Field(max_length=512)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ResendVerificationResponse(BaseModel):
    sent: bool
    next_cooldown_seconds: int


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(max_length=512)
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    # Optional: an account created through Google has no password to confirm.
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    is_email_verified: bool
    onboarding_step: str
    onboarding_completed: bool
    # Google-only accounts have none. Settings needs this to ask for a NEW
    # password instead of a current one it will never be given, and account
    # deletion already branches the same way.
    has_password: bool = True

    model_config = {"from_attributes": True}
