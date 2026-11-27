"""Schemas for administrator user management and audit-event listing (Part 4, Stage 5).

Requests
    Unknown fields (and unknown query parameters) are rejected. There is no
    request field for a password hash, token version, lockout state or any
    other internal authentication field, and the student-creation request has
    no ``role`` field: the API can only create students, and a cohort is
    required. Each request maps to exactly one repository operation in
    :mod:`backend.app.auth.admin_repository`, so every change stays atomic.

Responses
    Only the fields declared here are returned. User responses never include
    the password hash, token version, failed sign-in counter or lock expiry;
    administrators see only a derived ``is_locked`` flag. Audit responses
    return only detail keys from an explicit allowlist, which withholds the
    lockout counter and lock expiry recorded for sign-in events.

Bounds come from the repositories (page sizes, offsets, text lengths, the
audit vocabulary) and are not redefined here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.audit.repository import ACTIONS, AuditEvent, _looks_secret
from backend.app.auth.admin_repository import DEFAULT_PAGE_SIZE, MAX_OFFSET, MAX_PAGE_SIZE, UserPage
from backend.app.auth.password_policy import validate_password_strength
from backend.app.auth.repository import (
    MAX_COHORT_VALUE_LENGTH,
    MAX_EMAIL_LENGTH,
    MAX_FULL_NAME_LENGTH,
    UserRecord,
    is_locked,
    normalize_email,
)
from backend.app.core.security import MAX_PASSWORD_LENGTH

MAX_ID = 2**63 - 1
"""Largest SQLite integer; larger ids are rejected instead of overflowing."""

Role = Literal["student", "administrator"]


# --------------------------------------------------------------------------- #
# Shared field validation
# --------------------------------------------------------------------------- #


def _clean_cohort(value: Optional[str], *, required: bool) -> Optional[str]:
    """Trim a cohort value; refuse blank (when required) and credential-shaped values.

    Cohort values are written to the audit log, which refuses credential-shaped
    strings; rejecting them here returns 422 instead of failing the change.
    """
    if value is None:
        if required:
            raise ValueError("A value is required.")
        return None
    cleaned = value.strip()
    if not cleaned:
        if required:
            raise ValueError("A value is required.")
        return None
    if _looks_secret(cleaned):
        raise ValueError("The value looks like a credential and was refused.")
    return cleaned


def _clean_full_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _check_password(password: str, email: Optional[str] = None) -> str:
    problems = validate_password_strength(password, email=email)
    if problems:
        # Policy messages describe the rule, never the password.
        raise ValueError("Password does not meet the password policy: " + " ".join(problems))
    return password


def _aware(value: Optional[datetime], name: str) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} must include a timezone offset.")
    return value


# --------------------------------------------------------------------------- #
# User management requests
# --------------------------------------------------------------------------- #


class StudentCreateRequest(BaseModel):
    """Create a student account. There is deliberately no role field."""

    # hide_input_in_errors: a logged ValidationError must never contain the password.
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH, strict=True)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH, strict=True, repr=False)
    admission_batch: str = Field(min_length=1, max_length=MAX_COHORT_VALUE_LENGTH, strict=True)
    programme: str = Field(min_length=1, max_length=MAX_COHORT_VALUE_LENGTH, strict=True)
    full_name: Optional[str] = Field(default=None, max_length=MAX_FULL_NAME_LENGTH, strict=True)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        try:
            return normalize_email(value)
        except ValueError:
            raise ValueError("Email address is not valid.") from None

    @field_validator("admission_batch", "programme")
    @classmethod
    def _require_cohort(cls, value: str) -> str:
        return _clean_cohort(value, required=True)  # type: ignore[return-value]

    @field_validator("full_name")
    @classmethod
    def _trim_full_name(cls, value: Optional[str]) -> Optional[str]:
        return _clean_full_name(value)

    @model_validator(mode="after")
    def _password_policy(self) -> "StudentCreateRequest":
        _check_password(self.password, self.email)
        return self


class UserProfileUpdateRequest(BaseModel):
    """Change an account's full name and/or cohort. Omitted fields are unchanged.

    ``null`` clears a value; the repository still requires students to keep a
    cohort. At least one field must be supplied.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(default=None, max_length=MAX_FULL_NAME_LENGTH, strict=True)
    admission_batch: Optional[str] = Field(default=None, max_length=MAX_COHORT_VALUE_LENGTH, strict=True)
    programme: Optional[str] = Field(default=None, max_length=MAX_COHORT_VALUE_LENGTH, strict=True)

    @field_validator("admission_batch", "programme")
    @classmethod
    def _clean_cohort_value(cls, value: Optional[str]) -> Optional[str]:
        return _clean_cohort(value, required=False)

    @field_validator("full_name")
    @classmethod
    def _trim_full_name(cls, value: Optional[str]) -> Optional[str]:
        return _clean_full_name(value)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "UserProfileUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one of full_name, admission_batch or programme.")
        return self

    def changes(self) -> dict[str, Optional[str]]:
        """Only the supplied fields, as keyword arguments for ``update_profile``."""
        return {name: getattr(self, name) for name in sorted(self.model_fields_set)}


class RoleChangeRequest(BaseModel):
    """Change an account's role.

    ``administrator`` is accepted here so that a promotion attempt reaches the
    repository, which refuses it and records the refusal in the audit log. The
    API can never grant the administrator role.
    """

    model_config = ConfigDict(extra="forbid")

    role: Role  # a Literal accepts only these exact strings


class PasswordResetRequest(BaseModel):
    """Set a student's new password.

    The policy is checked here as far as possible without the account's email;
    the repository checks it again with the email when the password is set.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH, strict=True, repr=False)

    @field_validator("new_password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return _check_password(value)


class UserListQuery(BaseModel):
    """Query parameters for listing users. Unknown parameters are rejected."""

    model_config = ConfigDict(extra="forbid")

    role: Optional[Role] = None
    is_active: Optional[bool] = None
    admission_batch: Optional[str] = Field(default=None, max_length=MAX_COHORT_VALUE_LENGTH)
    programme: Optional[str] = Field(default=None, max_length=MAX_COHORT_VALUE_LENGTH)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET)

    @field_validator("admission_batch", "programme")
    @classmethod
    def _non_blank_filter(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Filter must not be blank.")
        return value.strip() if value is not None else None

    def filters(self) -> dict[str, Any]:
        """Keyword arguments for ``list_users``."""
        return self.model_dump()


# --------------------------------------------------------------------------- #
# User management responses
# --------------------------------------------------------------------------- #


class AdminUserResponse(BaseModel):
    """An account as shown to administrators. No internal authentication fields."""

    model_config = ConfigDict(extra="forbid")

    id: int
    email: str
    role: Role
    full_name: Optional[str] = None
    admission_batch: Optional[str] = None
    programme: Optional[str] = None
    is_active: bool
    is_locked: bool = Field(description="True while a temporary sign-in lock is in force.")
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: UserRecord, *, now: Optional[datetime] = None) -> "AdminUserResponse":
        return cls(
            id=record.id,
            email=record.email,
            role=record.role,
            full_name=record.full_name,
            admission_batch=record.admission_batch,
            programme=record.programme,
            is_active=record.is_active,
            is_locked=is_locked(record, now),
            last_login_at=record.last_login_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class AdminUserListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: list[AdminUserResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(ge=0, le=MAX_OFFSET)

    @classmethod
    def from_page(cls, page: UserPage, *, now: Optional[datetime] = None) -> "AdminUserListResponse":
        return cls(
            users=[AdminUserResponse.from_record(user, now=now) for user in page.users],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


# --------------------------------------------------------------------------- #
# Audit events
# --------------------------------------------------------------------------- #

AUDIT_DETAIL_RESPONSE_KEYS = frozenset(
    {
        "changed_fields",
        "role",
        "old_role",
        "new_role",
        "admission_batch",
        "programme",
        "old_admission_batch",
        "new_admission_batch",
        "old_programme",
        "new_programme",
        "old_is_active",
        "new_is_active",
        "old_status",
        "new_status",
        "reason",
        "method",
        "path",
    }
)
"""Audit detail keys returned by the API."""

AUDIT_DETAIL_WITHHELD_KEYS = frozenset({"failed_login_count", "locked_until"})
"""Recorded audit detail keys never returned by the API (lockout internals)."""


class AuditEventListQuery(BaseModel):
    """Query parameters for listing audit events. Unknown parameters are rejected."""

    model_config = ConfigDict(extra="forbid")

    action: Optional[str] = Field(default=None, max_length=64)
    outcome: Optional[Literal["success", "failure", "denied"]] = None
    actor_user_id: Optional[int] = Field(default=None, ge=1, le=MAX_ID)
    target_type: Optional[Literal["user", "regulation"]] = None
    target_id: Optional[int] = Field(default=None, ge=1, le=MAX_ID)
    occurred_after: Optional[datetime] = None
    occurred_before: Optional[datetime] = None
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET)

    @field_validator("action")
    @classmethod
    def _known_action(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ACTIONS:
            raise ValueError("Unknown audit action.")
        return value

    @field_validator("occurred_after", "occurred_before")
    @classmethod
    def _timezone_aware(cls, value: Optional[datetime], info: Any) -> Optional[datetime]:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def _consistent(self) -> "AuditEventListQuery":
        if self.target_id is not None and self.target_type is None:
            raise ValueError("target_id requires target_type.")
        if self.occurred_after and self.occurred_before and self.occurred_after > self.occurred_before:
            raise ValueError("occurred_after must not be later than occurred_before.")
        return self


class AuditEventResponse(BaseModel):
    """One audit event as shown to administrators."""

    model_config = ConfigDict(extra="forbid")

    id: int
    occurred_at: datetime
    action: str
    outcome: Literal["success", "failure", "denied"]
    actor_type: Literal["user", "anonymous", "cli", "system"]
    actor_user_id: Optional[int] = None
    actor_role: Optional[Role] = None
    target_type: Optional[Literal["user", "regulation"]] = None
    target_id: Optional[int] = None
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Approved, non-sensitive details only: " + ", ".join(sorted(AUDIT_DETAIL_RESPONSE_KEYS)) + ".",
    )

    @classmethod
    def from_event(cls, event: AuditEvent) -> "AuditEventResponse":
        return cls(
            id=event.id,
            occurred_at=event.occurred_at,
            action=event.action,
            outcome=event.outcome,
            actor_type=event.actor_type,
            actor_user_id=event.actor_user_id,
            actor_role=event.actor_role,
            target_type=event.target_type,
            target_id=event.target_id,
            details=public_audit_details(event.details),
        )


class AuditEventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[AuditEventResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(ge=0, le=MAX_OFFSET)


def public_audit_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only allowlisted detail keys (unknown keys are dropped, never passed through)."""
    return {key: value for key, value in details.items() if key in AUDIT_DETAIL_RESPONSE_KEYS}
