"""Administrator user-management and audit-event schemas (Part 4, Stage 5).

Schemas only: no API route is involved. Records and events used for response
tests come from temporary databases; passwords are generated at runtime.
"""

from __future__ import annotations

import inspect
import json
import secrets
import typing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.audit.repository import ACTIONS, ACTOR_TYPES, OUTCOMES, TARGET_TYPES, append_audit_event, init_audit_tables
from backend.app.auth.admin_repository import MAX_OFFSET, MAX_PAGE_SIZE, list_users
from backend.app.auth.repository import create_user, init_auth_tables, update_user
from backend.app.core.config import Settings
from backend.app.core.security import create_access_token, hash_password
from backend.app.schemas.admin import (
    AUDIT_DETAIL_RESPONSE_KEYS,
    AUDIT_DETAIL_WITHHELD_KEYS,
    AdminUserListResponse,
    AdminUserResponse,
    AuditEventListQuery,
    AuditEventListResponse,
    AuditEventResponse,
    PasswordResetRequest,
    RoleChangeRequest,
    StudentCreateRequest,
    UserListQuery,
    UserProfileUpdateRequest,
    public_audit_details,
)

INTERNAL_FIELDS = ("password_hash", "token_version", "failed_login_count", "locked_until")
FORBIDDEN_REQUEST_FIELDS = (*INTERNAL_FIELDS, "id", "role", "is_active", "last_login_at", "created_at", "password")


def strong_password() -> str:
    return "Kp4#" + secrets.token_urlsafe(18)


def _credential_values() -> list[str]:
    settings = Settings(app_env="test", jwt_secret_key=secrets.token_urlsafe(48))
    return [hash_password(strong_password())[:90], create_access_token(1, 0, settings=settings)[:90]]


def _student(**overrides: Any) -> dict[str, Any]:
    body = {
        "email": "New.Student@Uni.EDU",
        "password": strong_password(),
        "admission_batch": "2024",
        "programme": "BSc CS",
    }
    body.update(overrides)
    return body


def _error_text(excinfo: pytest.ExceptionInfo[ValidationError]) -> str:
    return str(excinfo.value) + json.dumps(excinfo.value.errors(include_input=False), default=str)


# --------------------------------------------------------------------------- #
# StudentCreateRequest
# --------------------------------------------------------------------------- #


def test_student_create_request_normalizes_input() -> None:
    request = StudentCreateRequest(**_student(admission_batch=" 2024 ", programme=" BSc CS ", full_name="  Ada  "))

    assert request.email == "new.student@uni.edu"
    assert (request.admission_batch, request.programme, request.full_name) == ("2024", "BSc CS", "Ada")
    assert StudentCreateRequest(**_student(full_name="   ")).full_name is None


def test_student_create_request_has_no_role_field() -> None:
    assert "role" not in StudentCreateRequest.model_fields
    assert set(StudentCreateRequest.model_fields) == {"email", "password", "admission_batch", "programme", "full_name"}


@pytest.mark.parametrize("field", FORBIDDEN_REQUEST_FIELDS[:-1])  # "password" is a real field here
def test_student_create_request_rejects_internal_and_role_fields(field: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        StudentCreateRequest(**_student(**{field: "administrator" if field == "role" else 1}))

    assert excinfo.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("missing", ["admission_batch", "programme", "email", "password"])
def test_student_create_request_requires_cohort_and_credentials(missing: str) -> None:
    body = _student()
    del body[missing]

    with pytest.raises(ValidationError):
        StudentCreateRequest(**body)


@pytest.mark.parametrize(
    "overrides",
    [
        {"admission_batch": ""},
        {"admission_batch": "   "},
        {"programme": None},
        {"admission_batch": 2024},  # strict: no number coercion
        {"programme": ["BSc CS"]},
        {"admission_batch": "x" * 101},
        {"email": "not-an-email"},
        {"email": "a" * 250 + "@u.edu"},
        {"full_name": "n" * 201},
        {"password": ""},
        {"password": "x" * 1025},
    ],
)
def test_student_create_request_rejects_invalid_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StudentCreateRequest(**_student(**overrides))


@pytest.mark.parametrize("value", _credential_values(), ids=["argon2-hash", "jwt"])
def test_student_create_request_rejects_credential_shaped_cohorts(value: str) -> None:
    for field in ("admission_batch", "programme"):
        with pytest.raises(ValidationError) as excinfo:
            StudentCreateRequest(**_student(**{field: value}))
        assert value not in _error_text(excinfo)


@pytest.mark.parametrize("password", ["password1234567", "Short1!", "aaaaaaaaaaaaaaaaaaaa", "New.Student#24"])
def test_student_create_request_applies_the_password_policy(password: str) -> None:
    """The last case contains the email name (new.student), which the policy refuses."""
    with pytest.raises(ValidationError) as excinfo:
        StudentCreateRequest(**_student(password=password))

    assert "password policy" in str(excinfo.value).lower()
    assert password not in _error_text(excinfo)


def test_passwords_are_hidden_from_repr_and_errors() -> None:
    password = strong_password()
    request = StudentCreateRequest(**_student(password=password))
    reset = PasswordResetRequest(new_password=password)

    for model in (request, reset):
        assert password not in repr(model) and password not in str(model)
    with pytest.raises(ValidationError) as excinfo:
        StudentCreateRequest(**_student(password=password, admission_batch=""))
    assert password not in _error_text(excinfo)


# --------------------------------------------------------------------------- #
# UserProfileUpdateRequest, RoleChangeRequest, PasswordResetRequest
# --------------------------------------------------------------------------- #


def test_profile_update_returns_only_supplied_fields() -> None:
    assert UserProfileUpdateRequest(programme=" BSc DS ").changes() == {"programme": "BSc DS"}
    assert UserProfileUpdateRequest(full_name=None).changes() == {"full_name": None}
    assert UserProfileUpdateRequest(admission_batch="   ").changes() == {"admission_batch": None}
    assert UserProfileUpdateRequest(full_name="A", admission_batch="2025", programme="X").changes() == {
        "admission_batch": "2025",
        "full_name": "A",
        "programme": "X",
    }


def test_profile_update_changes_match_the_repository_operation() -> None:
    from backend.app.auth.admin_repository import update_profile

    assert set(UserProfileUpdateRequest.model_fields) <= set(inspect.signature(update_profile).parameters)


def test_profile_update_requires_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdateRequest()


@pytest.mark.parametrize("field", ("email", *FORBIDDEN_REQUEST_FIELDS))
def test_profile_update_rejects_other_fields(field: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        UserProfileUpdateRequest(**{field: "x"})

    assert excinfo.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    "body",
    [{"programme": 5}, {"admission_batch": "x" * 101}, {"full_name": "n" * 201}, *[{"programme": v} for v in _credential_values()]],
)
def test_profile_update_rejects_invalid_values(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        UserProfileUpdateRequest(**body)


@pytest.mark.parametrize("role", ["student", "administrator"])
def test_role_change_accepts_known_roles(role: str) -> None:
    assert RoleChangeRequest(role=role).role == role


@pytest.mark.parametrize("body", [{}, {"role": "superuser"}, {"role": "Administrator"}, {"role": 1},
                                  {"role": "student", "user_id": 3}, {"role": "student", "is_active": False}])
def test_role_change_rejects_invalid_bodies(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RoleChangeRequest(**body)


def test_password_reset_request() -> None:
    password = strong_password()

    assert PasswordResetRequest(new_password=password).new_password == password
    for body in ({}, {"new_password": "password1234567"}, {"new_password": password, "user_id": 2},
                 {"password": password}, {"new_password": 123456789012345}):
        with pytest.raises(ValidationError) as excinfo:
            PasswordResetRequest(**body)
        assert password not in _error_text(excinfo)


# --------------------------------------------------------------------------- #
# UserListQuery
# --------------------------------------------------------------------------- #


def test_user_list_query_defaults_and_repository_arguments() -> None:
    query = UserListQuery()

    assert query.filters() == {"role": None, "is_active": None, "admission_batch": None, "programme": None,
                               "limit": 50, "offset": 0}
    parameters = set(inspect.signature(list_users).parameters) - {"db_path"}
    assert set(query.filters()) == parameters


def test_user_list_query_parses_query_string_values() -> None:
    query = UserListQuery.model_validate(
        {"role": "student", "is_active": "false", "limit": "100", "offset": "1000000", "programme": " BSc CS "}
    )

    assert (query.role, query.is_active, query.limit, query.offset, query.programme) == (
        "student", False, MAX_PAGE_SIZE, MAX_OFFSET, "BSc CS")


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": MAX_PAGE_SIZE + 1},
        {"limit": "abc"},
        {"offset": -1},
        {"offset": MAX_OFFSET + 1},
        {"role": "superuser"},
        {"is_active": "maybe"},
        {"admission_batch": "  "},
        {"programme": "x" * 101},
        {"email": "a@uni.edu"},
        {"password_hash": "x"},
        {"sort": "email"},
    ],
)
def test_user_list_query_rejects_invalid_parameters(params: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        UserListQuery.model_validate(params)


# --------------------------------------------------------------------------- #
# User responses
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "schemas.db"
    init_auth_tables(path)
    init_audit_tables(path)
    return path


def test_admin_user_response_never_exposes_internal_fields(db_path: Path) -> None:
    record = create_user("view@uni.edu", strong_password(), "student", admission_batch="2024", programme="BSc CS",
                         full_name="Viewed", db_path=db_path)
    record = update_user(record.id, failed_login_count=3, last_login_at=datetime.now(timezone.utc), db_path=db_path)

    response = AdminUserResponse.from_record(record)
    payload = response.model_dump_json()

    assert set(AdminUserResponse.model_fields) == {
        "id", "email", "role", "full_name", "admission_batch", "programme", "is_active", "is_locked",
        "last_login_at", "created_at", "updated_at",
    }
    for field in INTERNAL_FIELDS:
        assert field not in json.loads(payload)
    assert record.password_hash not in payload and "$argon2" not in payload
    assert (response.id, response.role, response.is_locked) == (record.id, "student", False)
    assert response.last_login_at is not None and response.last_login_at.tzinfo is not None


def test_admin_user_response_derives_lock_state(db_path: Path) -> None:
    record = create_user("locked@uni.edu", strong_password(), "student", admission_batch="2024", programme="BSc CS",
                         db_path=db_path)
    until = datetime.now(timezone.utc) + timedelta(minutes=10)
    record = update_user(record.id, failed_login_count=5, locked_until=until, db_path=db_path)

    assert AdminUserResponse.from_record(record).is_locked is True
    assert AdminUserResponse.from_record(record, now=until + timedelta(seconds=1)).is_locked is False
    assert until.isoformat()[:16] not in AdminUserResponse.from_record(record).model_dump_json()


def test_admin_user_list_response_from_repository_page(db_path: Path) -> None:
    for index in range(3):
        create_user(f"s{index}@uni.edu", strong_password(), "student", admission_batch="2024", programme="BSc CS",
                    db_path=db_path)

    response = AdminUserListResponse.from_page(list_users(limit=2, offset=1, db_path=db_path))

    assert (response.total, response.limit, response.offset, len(response.users)) == (3, 2, 1, 2)
    assert "password_hash" not in response.model_dump_json()


def test_user_responses_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AdminUserListResponse(users=[], total=0, limit=10, offset=0, password_hash="x")


# --------------------------------------------------------------------------- #
# Audit events
# --------------------------------------------------------------------------- #


def test_audit_query_defaults_and_valid_filters() -> None:
    query = AuditEventListQuery.model_validate(
        {
            "action": "user.deactivated",
            "outcome": "denied",
            "actor_user_id": "3",
            "target_type": "user",
            "target_id": "9",
            "occurred_after": "2026-01-01T00:00:00+00:00",
            "occurred_before": "2026-02-01T00:00:00Z",
            "limit": "100",
        }
    )

    assert (query.action, query.actor_user_id, query.target_id, query.limit, query.offset) == (
        "user.deactivated", 3, 9, 100, 0)
    assert AuditEventListQuery().limit == 50


@pytest.mark.parametrize(
    "params",
    [
        {"action": "user.deleted"},
        {"action": "x" * 65},
        {"outcome": "maybe"},
        {"actor_user_id": 0},
        {"actor_user_id": 2**63},
        {"target_id": 4},  # without target_type
        {"target_type": "document", "target_id": 1},
        {"occurred_after": "2026-01-01T00:00:00"},  # naive
        {"occurred_after": "2026-02-01T00:00:00+00:00", "occurred_before": "2026-01-01T00:00:00+00:00"},
        {"limit": 0},
        {"limit": MAX_PAGE_SIZE + 1},
        {"offset": MAX_OFFSET + 1},
        {"details": "x"},
        {"email": "a@uni.edu"},
    ],
)
def test_audit_query_rejects_invalid_parameters(params: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AuditEventListQuery.model_validate(params)


def test_audit_detail_keys_are_all_classified() -> None:
    recorded = {key for spec in ACTIONS.values() for key in spec.detail_keys}

    assert recorded == AUDIT_DETAIL_RESPONSE_KEYS | AUDIT_DETAIL_WITHHELD_KEYS
    assert not AUDIT_DETAIL_RESPONSE_KEYS & AUDIT_DETAIL_WITHHELD_KEYS


def test_audit_response_vocabulary_matches_the_repository() -> None:
    hints = typing.get_type_hints(AuditEventResponse)

    def literal_values(annotation: Any) -> set[str]:
        args = typing.get_args(annotation)
        values: set[str] = set()
        for arg in args:
            values |= set(typing.get_args(arg)) if typing.get_args(arg) else ({arg} if isinstance(arg, str) else set())
        return values

    assert literal_values(hints["outcome"]) == set(OUTCOMES)
    assert literal_values(hints["actor_type"]) == set(ACTOR_TYPES)
    assert literal_values(hints["target_type"]) == set(TARGET_TYPES)


def test_audit_response_withholds_lockout_details(db_path: Path) -> None:
    common = {"actor_type": "anonymous", "target_type": "user", "target_id": 4, "db_path": db_path}
    failed = append_audit_event("auth.login_failed", outcome="failure",
                                details={"reason": "invalid_password", "failed_login_count": 4}, **common)
    locked = append_audit_event("auth.account_locked", outcome="success", actor_type="system", target_type="user",
                                target_id=4, details={"failed_login_count": 5,
                                                      "locked_until": datetime.now(timezone.utc)}, db_path=db_path)
    changed = append_audit_event("user.updated", outcome="success", actor_type="user", actor_user_id=1,
                                 actor_role="administrator", target_type="user", target_id=4,
                                 details={"changed_fields": ["programme"], "old_programme": "A", "new_programme": "B"},
                                 db_path=db_path)

    responses = [AuditEventResponse.from_event(event) for event in (failed, locked, changed)]

    assert responses[0].details == {"reason": "invalid_password"}
    assert responses[1].details == {}
    assert responses[2].details == {"changed_fields": ["programme"], "old_programme": "A", "new_programme": "B"}
    assert responses[2].occurred_at.tzinfo is not None
    payload = AuditEventListResponse(events=responses, total=3, limit=50, offset=0).model_dump_json()
    assert "failed_login_count" not in payload and "locked_until" not in payload


def test_unknown_detail_keys_are_dropped_not_passed_through() -> None:
    assert public_audit_details({"reason": "self_change", "password": "x", "token": "y"}) == {"reason": "self_change"}


def test_audit_responses_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AuditEventListResponse(events=[], total=0, limit=10, offset=0, internal="x")
