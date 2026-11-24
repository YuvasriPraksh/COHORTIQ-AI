"""Schemas for sign-in and the authenticated user's profile.

Only the fields declared here are accepted or returned. In particular the
profile never contains the password hash, token version, failed-login count,
lock state or any other internal security field, and the sign-in request has
no ``role`` field (unknown fields are rejected): roles are always read from the
users table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.auth.repository import MAX_EMAIL_LENGTH, normalize_email
from backend.app.core.security import MAX_PASSWORD_LENGTH


class LoginRequest(BaseModel):
    """Email and password sign-in request."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH, strict=True)
    # Excluded from repr so a logged model can never reveal the password.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH, strict=True, repr=False)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        """Trim and lower-case the email; reject values that are not an address."""
        try:
            return normalize_email(value)
        except ValueError:
            raise ValueError("Email address is not valid.") from None


class TokenResponse(BaseModel):
    """A bearer access token and its lifetime in seconds."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires.")


class UserProfileResponse(BaseModel):
    """Public profile of the authenticated account."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: Literal["student", "administrator"]
    full_name: Optional[str] = None
    admission_batch: Optional[str] = None
    programme: Optional[str] = None
    is_active: bool
    created_at: datetime
