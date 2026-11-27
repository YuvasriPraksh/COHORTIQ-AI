"""Schemas for sign-in and the authenticated user's profile.

Only the fields declared here are accepted or returned. In particular the
profile never contains the password hash, token version, failed-login count,
lock state or any other internal security field. The sign-in request may name
the role selected in the UI for a server-side comparison, but cannot set the
account's persisted role.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.auth.repository import MAX_EMAIL_LENGTH, normalize_email
from backend.app.core.security import MAX_PASSWORD_LENGTH
from backend.app.schemas.admin import StudentCreateRequest


class LoginRequest(BaseModel):
    """Email and password sign-in request, with an optional UI role selection."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH, strict=True)
    # Excluded from repr so a logged model can never reveal the password.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH, strict=True, repr=False)
    selected_role: Optional[Literal["student", "staff", "administrator"]] = None

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
    role: Literal["student", "staff", "administrator"]
    full_name: Optional[str] = None
    admission_batch: Optional[str] = None
    programme: Optional[str] = None
    is_active: bool
    created_at: datetime


class RegisterRequest(StudentCreateRequest):
    """Public self-registration: a student account at the configured student domain.

    Inherits every rule of the administrator's student-creation request (email
    normalization, password policy checked against the email, required cohort,
    credential-shaped values refused, unknown fields rejected). There is no
    ``role`` field: registration can only create students. The email must be
    exactly at ``STUDENT_EMAIL_DOMAIN`` (default ``student.smvec.ac.in``); there is
    no email verification, so the domain check does not prove ownership.
    """
