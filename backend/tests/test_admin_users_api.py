"""Administrator user-management API (Part 4, Stage 5).

Requests use real accounts in a temporary database signed in through the login
service; nothing overrides ``get_current_user``. The anonymous/student/admin
matrix for every route is also enforced by ``test_route_permissions.py``; this
module covers behaviour, refusals, audit records and transactions.
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app.config import Settings as StorageSettings
from backend.app.api.deps import FORBIDDEN_DETAIL, NOT_AUTHENTICATED_DETAIL
from backend.app.api.v1 import admin_users as admin_routes
from backend.app.audit.repository import AuditEventError, init_audit_tables
from backend.app.auth import admin_repository
from backend.app.auth.admin_repository import AdminActionRefusedError, ConcurrentModificationError
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT
from backend.app.auth.repository import get_user_by_id, init_auth_tables, to_authenticated_user, update_user
from backend.app.core.security import verify_password
from backend.app.main import app, initialize_storage
from backend.tests.auth_support import SignedInAccount, create_signed_in_account, make_auth_settings, use_auth_database

USERS = "/api/v1/admin/users"
LOGIN = "/api/v1/auth/login"
INTERNAL = ("password_hash", "token_version", "failed_login_count", "locked_until", "$argon2")
RESPONSE_FIELDS = {
    "id", "email", "role", "full_name", "admission_batch", "programme", "is_active", "is_locked",
    "last_login_at", "created_at", "updated_at",
}


def strong_password() -> str:
    return "Kp4#" + secrets.token_urlsafe(18)


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    yield
    after = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    assert after == before, "The real project database was modified."


class Env:
    def __init__(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.db_path = db_path
        init_auth_tables(db_path)
        init_audit_tables(db_path)
        self.settings = make_auth_settings()
        use_auth_database(app, monkeypatch, db_path, self.settings)
        self.client = TestClient(app)
        self.admin = self.account(ROLE_ADMINISTRATOR)

    def account(self, role: str = ROLE_STUDENT, **options: Any) -> SignedInAccount:
        if role == ROLE_STUDENT:
            options.setdefault("admission_batch", "2024")
            options.setdefault("programme", "BSc CS")
        return create_signed_in_account(self.db_path, self.settings, role, **options)

    def request(self, method: str, path: str, who: Optional[SignedInAccount] = None, **kwargs: Any) -> Any:
        actor = self.admin if who is None else who
        return self.client.request(method, f"{USERS}{path}", headers=actor.headers, **kwargs)

    def login(self, email: str, password: str) -> Any:
        return self.client.post(LOGIN, json={"email": email, "password": password})

    def events(self, action: Optional[str] = None) -> list[dict[str, Any]]:
        """Audit events, excluding sign-in events (auth.*) unless an action is named."""
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM audit_events ORDER BY id;").fetchall()
        events = [{**dict(row), "details": json.loads(row["details"])} for row in rows]
        if action is not None:
            return [event for event in events if event["action"] == action]
        return [event for event in events if not event["action"].startswith("auth.")]

    def user(self, user_id: int) -> Any:
        return get_user_by_id(user_id, db_path=self.db_path)

    def me(self, account: SignedInAccount) -> int:
        return self.client.get("/api/v1/auth/me", headers=account.headers).status_code


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path / "admin-api.db", monkeypatch)


def _assert_safe(response: Any, *secrets_: str) -> None:
    for marker in (*INTERNAL, *secrets_):
        assert marker not in response.text, marker


def _assert_no_secret_values(response: Any, *values: str) -> None:
    """For error responses: no hash and no submitted secret, though field names may appear in ``loc``."""
    assert "$argon2" not in response.text
    for value in values:
        assert value not in response.text


def _assert_user_body(response: Any, status_code: int = 200) -> dict[str, Any]:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == RESPONSE_FIELDS
    assert response.headers["cache-control"] == "no-store"
    _assert_safe(response)
    return body


def _new_student(**overrides: Any) -> dict[str, Any]:
    body = {"email": f"new-{secrets.token_hex(4)}@uni.edu", "password": strong_password(),
            "admission_batch": "2024", "programme": "BSc CS"}
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- #
# Listing and reading
# --------------------------------------------------------------------------- #


def test_list_users_with_filters_and_pagination(env: Env) -> None:
    students = [env.account(admission_batch="2025" if i % 2 else "2024").user.id for i in range(5)]

    everyone = env.request("GET", "")
    filtered = env.request("GET", "", params={"role": "student", "admission_batch": "2025"})
    page = env.request("GET", "", params={"limit": 2, "offset": 1, "role": "student"})

    assert everyone.status_code == 200 and everyone.headers["cache-control"] == "no-store"
    assert everyone.json()["total"] == 6
    assert [u["id"] for u in filtered.json()["users"]] == [students[1], students[3]]
    assert page.json() | {"users": None} == {"users": None, "total": 5, "limit": 2, "offset": 1}
    assert [u["id"] for u in page.json()["users"]] == students[1:3]
    for user in everyone.json()["users"]:
        assert set(user) == RESPONSE_FIELDS
    _assert_safe(everyone)


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 1_000_001}, {"role": "superuser"},
     {"is_active": "maybe"}, {"admission_batch": " "}, {"sort": "email"}, {"password_hash": "x"}],
)
def test_list_users_rejects_invalid_parameters(env: Env, params: dict[str, Any]) -> None:
    assert env.request("GET", "", params=params).status_code == 422


def test_get_user(env: Env) -> None:
    student = env.account(full_name="Ada Student")

    body = _assert_user_body(env.request("GET", f"/{student.user.id}"))

    assert (body["id"], body["role"], body["full_name"], body["is_locked"]) == (student.user.id, "student", "Ada Student", False)
    assert env.request("GET", "/999999").json() == {"detail": "User not found."}
    for bad in ("0", "abc", str(2**63)):
        assert env.request("GET", f"/{bad}").status_code == 422


# --------------------------------------------------------------------------- #
# Creating students
# --------------------------------------------------------------------------- #


def test_create_student_and_sign_in(env: Env) -> None:
    body = _new_student(email="Fresh.Student@Uni.EDU", full_name="Fresh Student")

    response = env.request("POST", "", json=body)

    created = _assert_user_body(response, 201)
    assert (created["email"], created["role"], created["admission_batch"]) == ("fresh.student@uni.edu", "student", "2024")
    _assert_safe(response, body["password"])
    assert env.login("fresh.student@uni.edu", body["password"]).status_code == 200
    [event] = env.events()
    assert (event["action"], event["outcome"], event["actor_user_id"], event["target_id"]) == (
        "user.created", "success", env.admin.user.id, created["id"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"role": "administrator"},
        {"role": "student"},
        {"is_active": False},
        {"password_hash": "$argon2id$v=19$x"},
        {"admission_batch": None},
        {"programme": "  "},
        {"email": "not-an-email"},
        {"password": "password1234567"},
    ],
)
def test_create_rejects_invalid_or_privileged_requests(env: Env, overrides: dict[str, Any]) -> None:
    body = _new_student(**overrides)

    response = env.request("POST", "", json=body)

    assert response.status_code == 422
    _assert_no_secret_values(response, body["password"], "$argon2id$v=19$x")
    assert env.request("GET", "").json()["total"] == 1  # only the acting administrator
    assert env.events() == []


def test_create_refuses_a_password_containing_the_email_name(env: Env) -> None:
    body = _new_student(email="jordan.smith@uni.edu", password="Jordan.Smith#2024")

    response = env.request("POST", "", json=body)

    assert response.status_code == 422
    assert "password policy" in response.text.lower()
    _assert_safe(response, body["password"])


def test_create_rejects_duplicate_email(env: Env) -> None:
    existing = env.account()

    response = env.request("POST", "", json=_new_student(email=existing.user.email.upper()))

    assert response.status_code == 409
    assert response.json() == {"detail": "An account with this email already exists."}
    assert env.events() == []


# --------------------------------------------------------------------------- #
# Profile and role
# --------------------------------------------------------------------------- #


def test_update_profile(env: Env) -> None:
    student = env.account()

    body = _assert_user_body(env.request("PATCH", f"/{student.user.id}", json={"programme": "BSc DS", "full_name": "New"}))

    assert (body["programme"], body["full_name"]) == ("BSc DS", "New")
    assert env.me(student) == 200  # profile changes do not revoke tokens
    [event] = env.events()
    assert event["details"]["changed_fields"] == ["full_name", "programme"]
    assert "New" not in json.dumps(event["details"])


@pytest.mark.parametrize(
    "payload, status_code",
    [({}, 422), ({"role": "administrator"}, 422), ({"is_active": False}, 422), ({"email": "x@uni.edu"}, 422),
     ({"admission_batch": None}, 422), ({"programme": ""}, 422)],
)
def test_update_profile_rejections(env: Env, payload: dict[str, Any], status_code: int) -> None:
    student = env.account()
    before = env.user(student.user.id)

    response = env.request("PATCH", f"/{student.user.id}", json=payload)

    assert response.status_code == status_code
    assert env.user(student.user.id) == before
    assert env.events() == []


def test_demotion_revokes_the_demoted_administrators_tokens(env: Env) -> None:
    other = env.account(ROLE_ADMINISTRATOR)

    body = _assert_user_body(env.request("PATCH", f"/{other.user.id}/role", json={"role": "student"}))

    assert body["role"] == "student"
    assert env.me(other) == 401
    assert env.events("user.role_changed")[0]["outcome"] == "success"


def test_promotion_is_refused_and_audited(env: Env) -> None:
    student = env.account()
    before = env.user(student.user.id)

    response = env.request("PATCH", f"/{student.user.id}/role", json={"role": "administrator"})

    assert response.status_code == 403
    assert response.json() == {"detail": "The administrator role cannot be granted through user management."}
    assert env.user(student.user.id) == before
    [event] = env.events()
    assert (event["action"], event["outcome"], event["details"]["reason"]) == ("user.role_changed", "denied", "role_not_assignable")


def test_administrator_cannot_change_own_role_or_status(env: Env) -> None:
    env.account(ROLE_ADMINISTRATOR)
    own = env.admin.user.id

    role = env.request("PATCH", f"/{own}/role", json={"role": "student"})
    status_change = env.request("POST", f"/{own}/deactivate")

    for response in (role, status_change):
        assert response.status_code == 403
    assert env.user(own).role == "administrator" and env.user(own).is_active
    assert [(e["outcome"], e["details"]["reason"]) for e in env.events()] == [("denied", "self_change")] * 2


@pytest.mark.parametrize("payload", [{}, {"role": "superuser"}, {"role": 1}, {"role": "student", "user_id": 1}])
def test_role_change_rejects_invalid_bodies(env: Env, payload: dict[str, Any]) -> None:
    assert env.request("PATCH", f"/{env.account().user.id}/role", json=payload).status_code == 422


# --------------------------------------------------------------------------- #
# Password reset
# --------------------------------------------------------------------------- #


def test_reset_student_password(env: Env) -> None:
    student = env.account()
    new_password = strong_password()

    response = env.request("POST", f"/{student.user.id}/password", json={"new_password": new_password})

    _assert_user_body(response)
    _assert_safe(response, new_password)
    assert env.me(student) == 401  # existing tokens revoked
    assert env.login(student.user.email, student.password).status_code == 401
    assert env.login(student.user.email, new_password).status_code == 200
    [event] = env.events()
    assert (event["action"], event["outcome"], event["details"]) == ("user.password_reset", "success", {})


@pytest.mark.parametrize("target", ["self", "other_administrator"])
def test_administrator_passwords_cannot_be_reset(env: Env, target: str) -> None:
    other = env.account(ROLE_ADMINISTRATOR)
    account = env.admin if target == "self" else other
    new_password = strong_password()

    response = env.request("POST", f"/{account.user.id}/password", json={"new_password": new_password})

    assert response.status_code == 403
    _assert_safe(response, new_password)
    assert verify_password(account.password, env.user(account.user.id).password_hash)
    assert env.login(account.user.email, account.password).status_code == 200
    [event] = env.events("user.password_reset")
    assert event["outcome"] == "denied"
    assert event["details"]["reason"] == ("self_change" if target == "self" else "administrator_account")


def test_reset_rejects_weak_passwords_without_echoing_them(env: Env) -> None:
    student = env.account(email="casey.lee@uni.edu")
    before = env.user(student.user.id)

    for password in ("password1234567", "Casey.Lee#2024!"):  # second fails only the email-name rule
        response = env.request("POST", f"/{student.user.id}/password", json={"new_password": password})
        assert response.status_code == 422
        _assert_no_secret_values(response, password)
    assert env.user(student.user.id) == before
    assert env.events() == []


# --------------------------------------------------------------------------- #
# Bodyless actions
# --------------------------------------------------------------------------- #


def test_deactivate_and_reactivate(env: Env) -> None:
    student = env.account()

    deactivated = _assert_user_body(env.request("POST", f"/{student.user.id}/deactivate"))
    assert deactivated["is_active"] is False and env.me(student) == 401
    assert env.login(student.user.email, student.password).status_code == 401

    reactivated = _assert_user_body(env.request("POST", f"/{student.user.id}/reactivate"))
    assert reactivated["is_active"] is True
    assert env.me(student) == 401  # tokens revoked at deactivation stay revoked
    assert env.login(student.user.email, student.password).status_code == 200
    assert [e["action"] for e in env.events()] == ["user.deactivated", "user.reactivated"]


def test_administrator_can_deactivate_another_administrator(env: Env) -> None:
    other = env.account(ROLE_ADMINISTRATOR)

    assert _assert_user_body(env.request("POST", f"/{other.user.id}/deactivate"))["is_active"] is False
    assert env.me(other) == 401


def test_unlock(env: Env) -> None:
    student = env.account()
    update_user(student.user.id, failed_login_count=5, locked_until=datetime.now(timezone.utc) + timedelta(minutes=15),
                db_path=env.db_path)
    assert env.request("GET", f"/{student.user.id}").json()["is_locked"] is True
    assert env.login(student.user.email, student.password).status_code == 401

    body = _assert_user_body(env.request("POST", f"/{student.user.id}/unlock"))

    assert body["is_locked"] is False
    assert env.login(student.user.email, student.password).status_code == 200
    assert env.events("user.unlocked")[0]["details"] == {"failed_login_count": 5}


def test_revoke_sessions(env: Env) -> None:
    student = env.account()

    _assert_user_body(env.request("POST", f"/{student.user.id}/revoke-sessions"))

    assert env.me(student) == 401
    assert env.login(student.user.email, student.password).status_code == 200


def test_administrator_may_revoke_own_sessions(env: Env) -> None:
    _assert_user_body(env.request("POST", f"/{env.admin.user.id}/revoke-sessions"))

    assert env.me(env.admin) == 401


def test_bodyless_actions_ignore_any_body(env: Env) -> None:
    student = env.account()

    response = env.request("POST", f"/{student.user.id}/unlock", json={"role": "administrator", "is_active": False})

    assert response.status_code == 200
    assert env.user(student.user.id).role == "student" and env.user(student.user.id).is_active


@pytest.mark.parametrize("path", ["deactivate", "reactivate", "unlock", "revoke-sessions"])
def test_bodyless_actions_on_unknown_users(env: Env, path: str) -> None:
    response = env.request("POST", f"/999999/{path}")

    assert response.status_code == 404 and response.json() == {"detail": "User not found."}
    assert env.events() == []


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #


def test_students_cannot_manage_users_and_nothing_changes(env: Env) -> None:
    student = env.account()
    other = env.account()
    before = (env.user(student.user.id), env.user(other.user.id))

    responses = [
        env.request("GET", "", who=student),
        env.request("POST", "", who=student, json=_new_student()),
        env.request("PATCH", f"/{student.user.id}/role", who=student, json={"role": "administrator"}),
        env.request("POST", f"/{other.user.id}/password", who=student, json={"new_password": strong_password()}),
        env.request("POST", f"/{other.user.id}/deactivate", who=student),
    ]

    for response in responses:
        assert response.status_code == 403 and response.json() == {"detail": FORBIDDEN_DETAIL}
    assert (env.user(student.user.id), env.user(other.user.id)) == before
    # Only the refusals are recorded; no user-management event exists.
    events = env.events()
    assert [e["action"] for e in events] == ["authorization.denied"] * len(responses)
    assert {(e["actor_user_id"], e["actor_role"], e["details"]["reason"]) for e in events} == {
        (student.user.id, "student", "insufficient_role")
    }


@pytest.mark.parametrize("state", ["inactive", "revoked", "demoted"])
def test_administrator_tokens_stop_working_when_the_account_changes(env: Env, state: str) -> None:
    other = env.account(ROLE_ADMINISTRATOR)
    actor = to_authenticated_user(env.user(env.admin.user.id))
    if state == "inactive":
        admin_repository.deactivate_account(actor, other.user.id, db_path=env.db_path)
    elif state == "revoked":
        admin_repository.revoke_sessions(actor, other.user.id, db_path=env.db_path)
    else:
        admin_repository.change_role(actor, other.user.id, "student", db_path=env.db_path)

    response = env.request("GET", "", who=other)

    assert response.status_code == 401 and response.json() == {"detail": NOT_AUTHENTICATED_DETAIL}


# --------------------------------------------------------------------------- #
# Error translation, audit and transactions
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "error, status_code, detail",
    [
        (AdminActionRefusedError("actor_not_authorized"), 403, FORBIDDEN_DETAIL),
        (AdminActionRefusedError("last_administrator"), 409, "The last active administrator cannot be deactivated or demoted."),
        (ConcurrentModificationError(), 409, "The account changed during the operation; please retry."),
        (AuditEventError("Detail 'x' is not approved."), 500, admin_routes.USER_MANAGEMENT_ERROR_DETAIL),
        (sqlite3.OperationalError("disk I/O error at C:/internal/path.db"), 500, admin_routes.USER_MANAGEMENT_ERROR_DETAIL),
        (RuntimeError("secret internal detail"), 500, admin_routes.USER_MANAGEMENT_ERROR_DETAIL),
    ],
)
def test_repository_outcomes_are_translated_without_leaking(env: Env, monkeypatch: pytest.MonkeyPatch, error: Exception,
                                                            status_code: int, detail: str) -> None:
    def raise_error(*_args: Any, **_kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(admin_repository, "deactivate_account", raise_error)

    response = env.request("POST", f"/{env.account().user.id}/deactivate")

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert "C:/" not in response.text and "secret" not in response.text and "Detail 'x'" not in response.text


@pytest.mark.parametrize(
    "method, path, payload",
    [
        ("POST", "", "create"),
        ("PATCH", "/{id}", {"programme": "BSc DS"}),
        ("POST", "/{id}/password", "password"),
        ("POST", "/{id}/deactivate", None),
        ("POST", "/{id}/revoke-sessions", None),
    ],
)
def test_audit_failure_rolls_back_the_change(env: Env, monkeypatch: pytest.MonkeyPatch, method: str, path: str,
                                             payload: Any) -> None:
    student = env.account()
    before = env.user(student.user.id)
    before_users = env.request("GET", "").json()
    real_append = admin_repository.append_audit_event

    def append_then_fail(*args: Any, **kwargs: Any) -> None:
        real_append(*args, **kwargs)
        raise RuntimeError("simulated failure after the audit write")

    monkeypatch.setattr(admin_repository, "append_audit_event", append_then_fail)
    placeholders = {"create": _new_student(), "password": {"new_password": strong_password()}}
    body = placeholders[payload] if isinstance(payload, str) else payload

    response = env.request(method, path.replace("{id}", str(student.user.id)), json=body)

    assert response.status_code == 500
    assert response.json() == {"detail": admin_routes.USER_MANAGEMENT_ERROR_DETAIL}
    monkeypatch.setattr(admin_repository, "append_audit_event", real_append)
    assert env.request("GET", "").json() == before_users
    assert env.user(student.user.id) == before
    assert env.events() == []


def test_each_successful_change_writes_one_event_by_the_signed_in_administrator(env: Env) -> None:
    student = env.account()
    sid = student.user.id
    update_user(sid, failed_login_count=2, db_path=env.db_path)

    for method, path, body in (
        ("PATCH", f"/{sid}", {"admission_batch": "2025"}),
        ("POST", f"/{sid}/unlock", None),
        ("POST", f"/{sid}/revoke-sessions", None),
        ("POST", f"/{sid}/password", {"new_password": strong_password()}),
        ("POST", f"/{sid}/deactivate", None),
        ("POST", f"/{sid}/reactivate", None),
    ):
        assert env.request(method, path, json=body).status_code == 200, path

    events = env.events()
    assert [e["action"] for e in events] == [
        "user.updated", "user.unlocked", "user.sessions_revoked", "user.password_reset", "user.deactivated",
        "user.reactivated",
    ]
    assert {(e["actor_type"], e["actor_user_id"], e["actor_role"], e["target_id"], e["outcome"]) for e in events} == {
        ("user", env.admin.user.id, "administrator", sid, "success")
    }


def test_no_password_is_logged(env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    student = env.account()
    passwords = [strong_password() for _ in range(3)]

    with caplog.at_level(logging.DEBUG):
        env.request("POST", "", json=_new_student(password=passwords[0]))
        env.request("POST", f"/{student.user.id}/password", json={"new_password": passwords[1]})
        monkeypatch.setattr(admin_repository, "reset_password", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        env.request("POST", f"/{student.user.id}/password", json={"new_password": passwords[2]})

    for password in passwords:
        assert password not in caplog.text
    assert "$argon2" not in caplog.text


# --------------------------------------------------------------------------- #
# Startup and documentation
# --------------------------------------------------------------------------- #


def test_startup_creates_the_audit_table_additively(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolated = StorageSettings(
        gemini_api_key=None,
        database_path=tmp_path / "data" / "cohortiq.db",
        upload_dir=tmp_path / "data" / "uploads",
        extracted_dir=tmp_path / "data" / "extracted",
    )
    monkeypatch.setattr("backend.app.main.get_storage_settings", lambda: isolated)

    db_path = initialize_storage()
    admin_repository.list_users(db_path=db_path)  # users table usable
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "INSERT INTO audit_events (occurred_at, action, outcome, actor_type, details) "
            "VALUES ('x', 'user.updated', 'success', 'system', '{}');"
        )
        connection.commit()
    initialize_storage()  # second start keeps existing events

    with closing(sqlite3.connect(db_path)) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master;")}
        count = connection.execute("SELECT COUNT(*) FROM audit_events;").fetchone()[0]
    assert {"regulations", "document_pages", "users", "audit_events", "audit_events_no_update"} <= names
    assert count == 1


def test_router_itself_requires_an_administrator() -> None:
    """Guards routes added later even if they forget the per-endpoint dependency."""
    from backend.app.api.deps import require_administrator

    assert require_administrator in [dependency.dependency for dependency in admin_routes.router.dependencies]


def test_openapi_documents_admin_routes_safely(env: Env) -> None:
    schema = env.client.get("/openapi.json").json()
    components = schema["components"]["schemas"]

    assert set(components["AdminUserResponse"]["properties"]) == RESPONSE_FIELDS
    assert "role" not in components["StudentCreateRequest"]["properties"]
    for path, operations in schema["paths"].items():
        if path.startswith(USERS):
            for operation in operations.values():
                assert operation["security"] == [{"HTTPBearer": []}]
                assert {"401", "403"} <= set(operation["responses"])
    for name in ("deactivate", "reactivate", "unlock", "revoke-sessions"):
        assert "requestBody" not in schema["paths"][f"{USERS}/{{user_id}}/{name}"]["post"]
