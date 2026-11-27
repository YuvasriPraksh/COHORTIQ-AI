"""Sign-in, account lockout and user profile (Part 4, Stage 3).

Every test uses a temporary SQLite database injected through
``get_auth_db_path`` and a per-test signing secret injected through
``get_auth_settings``. Passwords are generated at runtime. An autouse guard
verifies that the real project database is never modified.
"""

from __future__ import annotations

import dataclasses
import logging
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import config as app_config
from app.database import init_database
from backend.app.api.deps import (
    AUTH_UNAVAILABLE_DETAIL,
    NOT_AUTHENTICATED_DETAIL,
    AuthenticatedUser,
    get_auth_db_path,
    get_auth_settings,
    require_role,
)
from backend.app.api.v1 import auth as auth_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.api.v1.auth import LOGIN_FAILED_DETAIL
from backend.app.audit.repository import init_audit_tables
from backend.app.auth.repository import (
    UserRecord,
    apply_login_attempt,
    create_user,
    deactivate_user,
    get_user_by_id,
    increment_token_version,
    init_auth_tables,
    is_locked,
    update_user,
)
from backend.app.core.config import Settings
from backend.app.core.security import JWT_ALGORITHM, create_access_token, decode_access_token
from backend.app.main import app as main_app
from backend.app.schemas.auth import LoginRequest, UserProfileResponse
from backend.app.services import auth_service

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
PROFILE_FIELDS = {"id", "email", "role", "full_name", "admission_batch", "programme", "is_active", "created_at"}
INTERNAL_FIELDS = ("password_hash", "token_version", "failed_login_count", "locked_until", "last_login_at", "updated_at")


def strong_password() -> str:
    return "Kp4#" + secrets.token_urlsafe(18)


def make_settings(**overrides: Any) -> Settings:
    return Settings(app_env="test", jwt_secret_key=secrets.token_urlsafe(48), **overrides)


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    yield
    after = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    assert after == before, "The real project database was modified."


class Env:
    def __init__(self, db_path: Path, settings: Settings) -> None:
        self.db_path = db_path
        self.settings = settings
        self.client = TestClient(main_app)
        self.passwords: dict[str, str] = {}

    def add_user(self, email: str, role: str = "student", **kwargs: Any) -> UserRecord:
        password = strong_password()
        record = create_user(email, password, role, db_path=self.db_path, **kwargs)
        self.passwords[record.email] = password
        return record

    def login(self, email: str, password: Optional[str] = None):
        secret = password if password is not None else self.passwords[email.strip().lower()]
        return self.client.post(LOGIN_URL, json={"email": email, "password": secret})

    def me(self, token: Optional[str] = None, scheme: str = "Bearer"):
        headers = {"Authorization": f"{scheme} {token}"} if token is not None else {}
        return self.client.get(ME_URL, headers=headers)

    def user(self, user_id: int) -> UserRecord:
        record = get_user_by_id(user_id, db_path=self.db_path)
        assert record is not None
        return record

    def token(self, email: str) -> str:
        response = self.login(email)
        assert response.status_code == 200, response.text
        return response.json()["access_token"]


def _install(db_path: Path, settings: Settings) -> Env:
    main_app.dependency_overrides[get_auth_db_path] = lambda: str(db_path)
    main_app.dependency_overrides[get_auth_settings] = lambda: settings
    return Env(db_path, settings)


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    db_path = tmp_path / "auth.db"
    init_database(db_path)
    init_auth_tables(db_path)
    init_audit_tables(db_path)
    try:
        yield _install(db_path, make_settings())
    finally:
        main_app.dependency_overrides.pop(get_auth_db_path, None)
        main_app.dependency_overrides.pop(get_auth_settings, None)


def _assert_login_refused(response: Any) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": LOGIN_FAILED_DETAIL}
    assert response.headers.get("www-authenticate") == "Bearer"
    assert "access_token" not in response.text


def _assert_unauthenticated(response: Any) -> None:
    assert response.status_code == 401
    assert response.json() == {"detail": NOT_AUTHENTICATED_DETAIL}
    assert response.headers.get("www-authenticate") == "Bearer"


def _set_columns(db_path: Path, user_id: int, **values: Any) -> None:
    """Write raw column values, bypassing repository validation (test setup only)."""
    assignments = ", ".join(f"{column} = ?" for column in values)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(f"UPDATE users SET {assignments} WHERE id = ?;", (*values.values(), user_id))
        connection.commit()


def _parse(timestamp: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(timestamp) if timestamp else None


# --------------------------------------------------------------------------- #
# Successful sign-in
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["administrator", "student"])
def test_successful_login_returns_bearer_token(env: Env, role: str) -> None:
    user = env.add_user(f"{role}@uni.edu", role)

    response = env.login(user.email)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == env.settings.access_token_expire_minutes * 60
    assert response.headers["cache-control"] == "no-store"
    payload = decode_access_token(body["access_token"], settings=env.settings)
    assert payload.subject == str(user.id)
    assert payload.token_version == user.token_version
    lifetime = payload.expires_at - payload.issued_at
    assert lifetime == timedelta(minutes=env.settings.access_token_expire_minutes)


def test_token_is_hs256_and_carries_no_role(env: Env) -> None:
    user = env.add_user("claims@uni.edu", "administrator")

    token = env.token(user.email)

    assert jwt.get_unverified_header(token)["alg"] == JWT_ALGORITHM == "HS256"
    claims = jwt.decode(token, options={"verify_signature": False})
    assert "role" not in claims
    assert set(claims) == {"sub", "iat", "nbf", "exp", "iss", "aud", "jti", "ver"}


def test_email_is_matched_case_insensitively_and_trimmed(env: Env) -> None:
    user = env.add_user("Mixed.Case@Uni.EDU")
    password = env.passwords[user.email]

    for variant in ("mixed.case@uni.edu", "MIXED.CASE@UNI.EDU", "  Mixed.Case@uni.Edu  "):
        response = env.login(variant, password)
        assert response.status_code == 200, variant
        assert decode_access_token(response.json()["access_token"], settings=env.settings).subject == str(user.id)


def test_successful_login_records_last_login_and_keeps_tokens_valid(env: Env) -> None:
    user = env.add_user("last@uni.edu")
    assert user.last_login_at is None
    first = env.token(user.email)

    before = datetime.now(timezone.utc)
    second = env.token(user.email)

    record = env.user(user.id)
    assert record.last_login_at is not None and _parse(record.last_login_at) >= before - timedelta(seconds=1)
    assert record.token_version == user.token_version  # signing in revokes nothing
    assert env.me(first).status_code == 200 and env.me(second).status_code == 200


def test_token_authenticates_through_get_current_user_with_database_role(env: Env) -> None:
    student = env.add_user("rbac-student@uni.edu", "student")
    admin = env.add_user("rbac-admin@uni.edu", "administrator")
    probe = FastAPI()

    @probe.get("/admin-only")
    def admin_only(user: AuthenticatedUser = Depends(require_role("administrator"))) -> dict[str, Any]:
        return {"id": user.id, "role": user.role}

    probe.dependency_overrides[get_auth_db_path] = lambda: str(env.db_path)
    probe.dependency_overrides[get_auth_settings] = lambda: env.settings
    client = TestClient(probe)

    admin_response = client.get("/admin-only", headers={"Authorization": f"Bearer {env.token(admin.email)}"})
    student_response = client.get("/admin-only", headers={"Authorization": f"Bearer {env.token(student.email)}"})

    assert admin_response.status_code == 200
    assert admin_response.json() == {"id": str(admin.id), "role": "administrator"}
    assert student_response.status_code == 403


# --------------------------------------------------------------------------- #
# Refused sign-in
# --------------------------------------------------------------------------- #


def test_wrong_password_is_refused(env: Env) -> None:
    user = env.add_user("wrong@uni.edu")

    _assert_login_refused(env.login(user.email, strong_password()))


def test_unknown_email_is_refused_after_a_dummy_password_check(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = auth_service.perform_dummy_password_check
    monkeypatch.setattr(auth_service, "perform_dummy_password_check", lambda value: calls.append("dummy") or original(value))

    _assert_login_refused(env.login("nobody@uni.edu", strong_password()))

    assert calls == ["dummy"]


def test_every_path_performs_exactly_one_password_verification(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    active = env.add_user("timing-active@uni.edu")
    inactive = env.add_user("timing-inactive@uni.edu", is_active=False)
    locked = env.add_user("timing-locked@uni.edu")
    update_user(locked.id, locked_until=datetime.now(timezone.utc) + timedelta(minutes=5), db_path=env.db_path)
    verifications: list[str] = []
    real_verify = auth_service.verify_password
    real_dummy = auth_service.perform_dummy_password_check
    monkeypatch.setattr(auth_service, "verify_password", lambda *a: verifications.append("real") or real_verify(*a))
    monkeypatch.setattr(auth_service, "perform_dummy_password_check", lambda v: verifications.append("dummy") or real_dummy(v))

    for email, password in (
        ("timing-unknown@uni.edu", strong_password()),
        (active.email, strong_password()),
        (inactive.email, env.passwords[inactive.email]),
        (locked.email, env.passwords[locked.email]),
        (active.email, env.passwords[active.email]),
    ):
        verifications.clear()
        env.login(email, password)
        assert len(verifications) == 1, email


def test_inactive_account_cannot_log_in(env: Env) -> None:
    user = env.add_user("inactive@uni.edu", is_active=False)

    _assert_login_refused(env.login(user.email))

    assert env.user(user.id).last_login_at is None


def test_deactivated_account_cannot_log_in(env: Env) -> None:
    user = env.add_user("deactivated@uni.edu")
    assert env.login(user.email).status_code == 200

    deactivate_user(user.id, db_path=env.db_path)

    _assert_login_refused(env.login(user.email))


def test_refusals_are_identical_for_every_reason(env: Env) -> None:
    wrong = env.add_user("same-wrong@uni.edu")
    inactive = env.add_user("same-inactive@uni.edu", is_active=False)
    locked = env.add_user("same-locked@uni.edu")
    update_user(locked.id, locked_until=datetime.now(timezone.utc) + timedelta(minutes=10), db_path=env.db_path)

    responses = [
        env.login("same-unknown@uni.edu", strong_password()),
        env.login(wrong.email, strong_password()),
        env.login(inactive.email),  # correct password
        env.login(locked.email),  # correct password
    ]

    def fingerprint(response: Any) -> tuple:
        return (
            response.status_code,
            response.content,
            response.headers.get("www-authenticate"),
            response.headers.get("content-type"),
            response.headers.get("content-length"),
            response.headers.get("cache-control"),
        )

    assert len({fingerprint(response) for response in responses}) == 1
    _assert_login_refused(responses[0])
    for word in ("lock", "inactive", "exist", "attempt", "minute", "disabled"):
        assert word not in responses[0].text.lower()


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "student@uni.edu"},
        {"password": "Kp4#secret-value-x"},
        {"email": None, "password": "Kp4#secret-value-x"},
        {"email": "student@uni.edu", "password": None},
        {"email": "", "password": "Kp4#secret-value-x"},
        {"email": "student@uni.edu", "password": ""},
        {"email": 12345, "password": "Kp4#secret-value-x"},
        {"email": "student@uni.edu", "password": 123456789012},
        {"email": ["student@uni.edu"], "password": "Kp4#secret-value-x"},
        {"email": "student@uni.edu", "password": {"value": "x"}},
        {"email": "not-an-email", "password": "Kp4#secret-value-x"},
        {"email": "two@@uni.edu", "password": "Kp4#secret-value-x"},
        {"email": "a" * 250 + "@u.edu", "password": "Kp4#secret-value-x"},
        {"email": "student@uni.edu", "password": "x" * 1025},
        {"email": "student@uni.edu", "password": "Kp4#secret-value-x", "role": "administrator"},
    ],
)
def test_malformed_login_input_is_rejected_with_422(env: Env, body: dict[str, Any]) -> None:
    env.add_user("student@uni.edu")

    response = env.client.post(LOGIN_URL, json=body)

    assert response.status_code == 422
    assert "access_token" not in response.text
    assert "Kp4#secret-value-x" not in response.text  # input is never echoed


@pytest.mark.parametrize("content", [b"", b"not json", b"[]", b'"text"', b"{\"email\": "])
def test_non_object_body_is_rejected(env: Env, content: bytes) -> None:
    response = env.client.post(LOGIN_URL, content=content, headers={"Content-Type": "application/json"})

    assert response.status_code == 422


def test_oversized_login_body_is_rejected_by_size_limit(env: Env) -> None:
    response = env.client.post(LOGIN_URL, json={"email": "big@uni.edu", "password": "x" * (env.settings.max_json_body_bytes + 1)})

    assert response.status_code == 413


def test_maximum_length_password_is_processed(env: Env) -> None:
    user = env.add_user("long@uni.edu")

    _assert_login_refused(env.login(user.email, "Aa1!" * 256))  # exactly 1024 characters


def test_login_request_repr_hides_the_password() -> None:
    password = strong_password()
    request = LoginRequest(email="Repr@Uni.edu", password=password)

    assert request.email == "repr@uni.edu"
    assert password not in repr(request) and password not in str(request)


# --------------------------------------------------------------------------- #
# Account lockout
# --------------------------------------------------------------------------- #


def test_failed_attempts_increment_the_counter(env: Env) -> None:
    user = env.add_user("count@uni.edu")

    for expected in (1, 2, 3):
        _assert_login_refused(env.login(user.email, strong_password()))
        record = env.user(user.id)
        assert record.failed_login_count == expected
        assert record.locked_until is None


def test_unknown_email_failures_change_no_account(env: Env) -> None:
    user = env.add_user("bystander@uni.edu")

    for _ in range(3):
        env.login("BYSTANDER@uni.edu.au", strong_password())

    assert env.user(user.id) == user


def test_account_locks_after_configured_number_of_failures(env: Env) -> None:
    user = env.add_user("lockme@uni.edu")
    threshold = env.settings.login_max_failed_attempts
    assert threshold == 5 and env.settings.login_lockout_minutes == 15

    for _ in range(threshold - 1):
        env.login(user.email, strong_password())
    assert not is_locked(env.user(user.id))

    started = datetime.now(timezone.utc)
    _assert_login_refused(env.login(user.email, strong_password()))

    record = env.user(user.id)
    assert record.failed_login_count == threshold
    assert is_locked(record)
    locked_until = _parse(record.locked_until)
    expected = started + timedelta(minutes=15)
    assert expected - timedelta(seconds=5) <= locked_until <= expected + timedelta(seconds=5)


def test_locked_account_cannot_log_in_even_with_correct_password(env: Env) -> None:
    user = env.add_user("locked@uni.edu")
    for _ in range(env.settings.login_max_failed_attempts):
        env.login(user.email, strong_password())
    locked = env.user(user.id)
    assert is_locked(locked)

    _assert_login_refused(env.login(user.email))
    _assert_login_refused(env.login(user.email, strong_password()))

    after = env.user(user.id)
    assert after.locked_until == locked.locked_until, "attempts during a lock must not extend it"
    assert after.failed_login_count == locked.failed_login_count
    assert after.last_login_at is None


def test_expired_lock_permits_login_again(env: Env) -> None:
    user = env.add_user("expired@uni.edu")
    update_user(
        user.id,
        failed_login_count=5,
        locked_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        db_path=env.db_path,
    )

    response = env.login(user.email)

    assert response.status_code == 200
    record = env.user(user.id)
    assert (record.failed_login_count, record.locked_until) == (0, None)


def test_failure_after_an_expired_lock_starts_a_new_window(env: Env) -> None:
    user = env.add_user("window@uni.edu")
    update_user(
        user.id,
        failed_login_count=5,
        locked_until=datetime.now(timezone.utc) - timedelta(minutes=1),
        db_path=env.db_path,
    )

    _assert_login_refused(env.login(user.email, strong_password()))

    record = env.user(user.id)
    assert record.failed_login_count == 1
    assert record.locked_until is None
    assert env.login(user.email).status_code == 200


def test_lock_expires_at_the_configured_time(env: Env) -> None:
    user = env.add_user("clock@uni.edu")
    password = env.passwords[user.email]
    start = datetime.now(timezone.utc)
    for offset in range(5):
        with pytest.raises(auth_service.LoginFailedError):
            auth_service.login(user.email, strong_password(), settings=env.settings, db_path=env.db_path, now=start + timedelta(seconds=offset))

    with pytest.raises(auth_service.LoginFailedError):
        auth_service.login(user.email, password, settings=env.settings, db_path=env.db_path, now=start + timedelta(minutes=14))

    issued = auth_service.login(user.email, password, settings=env.settings, db_path=env.db_path, now=start + timedelta(minutes=15, seconds=5))
    assert issued.access_token


def test_successful_login_resets_the_failure_counter(env: Env) -> None:
    user = env.add_user("reset@uni.edu")
    for _ in range(4):
        env.login(user.email, strong_password())
    assert env.user(user.id).failed_login_count == 4

    assert env.login(user.email).status_code == 200

    record = env.user(user.id)
    assert (record.failed_login_count, record.locked_until) == (0, None)
    # Counting starts from zero again: four more failures do not lock.
    for _ in range(4):
        env.login(user.email, strong_password())
    assert not is_locked(env.user(user.id))


def test_lockout_threshold_and_duration_are_configurable(tmp_path: Path) -> None:
    db_path = tmp_path / "custom.db"
    init_auth_tables(db_path)
    init_audit_tables(db_path)
    settings = make_settings(login_max_failed_attempts=2, login_lockout_minutes=1)
    password = strong_password()
    user = create_user("custom@uni.edu", password, "student", db_path=db_path)
    start = datetime.now(timezone.utc)

    for _ in range(2):
        with pytest.raises(auth_service.LoginFailedError):
            auth_service.login(user.email, strong_password(), settings=settings, db_path=db_path, now=start)

    record = get_user_by_id(user.id, db_path=db_path)
    assert _parse(record.locked_until) == start + timedelta(minutes=1)
    assert auth_service.login(user.email, password, settings=settings, db_path=db_path, now=start + timedelta(minutes=1, seconds=1))


@pytest.mark.parametrize(
    "variable, value",
    [
        ("LOGIN_MAX_FAILED_ATTEMPTS", "0"),
        ("LOGIN_MAX_FAILED_ATTEMPTS", "101"),
        ("LOGIN_MAX_FAILED_ATTEMPTS", "five"),
        ("LOGIN_LOCKOUT_MINUTES", "0"),
        ("LOGIN_LOCKOUT_MINUTES", "1441"),
        ("LOGIN_LOCKOUT_MINUTES", "-5"),
    ],
)
def test_unsafe_lockout_configuration_is_rejected(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=variable):
        Settings()


def test_lockout_configuration_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGIN_MAX_FAILED_ATTEMPTS", raising=False)
    monkeypatch.delenv("LOGIN_LOCKOUT_MINUTES", raising=False)

    settings = Settings()

    assert (settings.login_max_failed_attempts, settings.login_lockout_minutes) == (5, 15)


def test_unreadable_lock_value_never_locks_permanently(env: Env) -> None:
    user = env.add_user("garbage@uni.edu")
    _set_columns(env.db_path, user.id, locked_until="not-a-timestamp", failed_login_count=5)
    assert not is_locked(env.user(user.id))

    assert env.login(user.email).status_code == 200
    assert env.user(user.id).locked_until is None


# --------------------------------------------------------------------------- #
# Concurrency and transactional safety
# --------------------------------------------------------------------------- #


def _run_concurrently(count: int, target: Any) -> list[BaseException]:
    barrier = threading.Barrier(count)
    errors: list[BaseException] = []

    def worker() -> None:
        barrier.wait()
        try:
            target()
        except BaseException as error:  # noqa: BLE001 - collected for assertions
            errors.append(error)

    threads = [threading.Thread(target=worker) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return errors


def test_concurrent_failures_are_all_counted(tmp_path: Path) -> None:
    db_path = tmp_path / "race.db"
    init_auth_tables(db_path)
    init_audit_tables(db_path)
    user = create_user("race@uni.edu", strong_password(), "student", db_path=db_path)

    errors = _run_concurrently(
        20,
        lambda: apply_login_attempt(
            user.id,
            verified_password_hash=user.password_hash,
            password_matches=False,
            max_failed_attempts=100,
            lockout_duration=timedelta(minutes=15),
            db_path=db_path,
        ),
    )

    assert errors == []
    assert get_user_by_id(user.id, db_path=db_path).failed_login_count == 20


def test_concurrent_logins_cannot_bypass_the_lock(env: Env) -> None:
    user = env.add_user("burst@uni.edu")
    threshold = env.settings.login_max_failed_attempts
    outcomes: list[str] = []

    def attempt() -> None:
        try:
            auth_service.login(user.email, strong_password(), settings=env.settings, db_path=env.db_path)
            outcomes.append("issued")
        except auth_service.LoginFailedError:
            outcomes.append("refused")

    errors = _run_concurrently(threshold * 3, attempt)

    assert errors == []
    assert outcomes == ["refused"] * (threshold * 3)
    record = env.user(user.id)
    assert record.failed_login_count == threshold  # attempts after the lock are not counted
    assert is_locked(record)
    _assert_login_refused(env.login(user.email))


def test_password_changed_during_sign_in_is_refused(env: Env) -> None:
    user = env.add_user("changed@uni.edu")
    stale_hash = user.password_hash
    update_user(user.id, password=strong_password(), db_path=env.db_path)

    result = apply_login_attempt(
        user.id,
        verified_password_hash=stale_hash,
        password_matches=True,
        max_failed_attempts=5,
        lockout_duration=timedelta(minutes=15),
        db_path=env.db_path,
    )

    assert result is None
    assert env.user(user.id).last_login_at is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_failed_attempts": 0, "lockout_duration": timedelta(minutes=1)},
        {"max_failed_attempts": True, "lockout_duration": timedelta(minutes=1)},
        {"max_failed_attempts": 5, "lockout_duration": timedelta(0)},
        {"max_failed_attempts": 5, "lockout_duration": 15},
    ],
)
def test_apply_login_attempt_rejects_unsafe_policy(env: Env, kwargs: dict[str, Any]) -> None:
    user = env.add_user("policy@uni.edu")

    with pytest.raises(ValueError):
        apply_login_attempt(user.id, verified_password_hash=user.password_hash, password_matches=False, db_path=env.db_path, **kwargs)

    assert env.user(user.id).failed_login_count == 0


def test_apply_login_attempt_for_missing_account_returns_none(env: Env) -> None:
    for user_id in (999, "abc", None, -1):
        assert (
            apply_login_attempt(
                user_id,
                verified_password_hash="$argon2id$x",
                password_matches=True,
                max_failed_attempts=5,
                lockout_duration=timedelta(minutes=1),
                db_path=env.db_path,
            )
            is None
        )


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #


def test_missing_signing_secret_returns_503_without_touching_accounts(env: Env) -> None:
    user = env.add_user("nosecret@uni.edu")
    main_app.dependency_overrides[get_auth_settings] = lambda: Settings(app_env="test", jwt_secret_key=None)

    for password in (env.passwords[user.email], strong_password()):
        response = env.login(user.email, password)
        assert response.status_code == 503
        assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}

    assert env.user(user.id) == user  # no counter, lock or last-login change


def test_database_failure_returns_generic_503(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error at C:/internal/secret/path.db")

    monkeypatch.setattr(auth_service, "get_user_by_email", broken)

    response = env.login("anyone@uni.edu", strong_password())

    assert response.status_code == 503
    assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}
    assert "internal" not in response.text and "sqlite" not in response.text.lower()


def test_missing_users_table_returns_503(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    init_database(db_path)  # regulations tables only
    _install(db_path, make_settings())
    try:
        response = TestClient(main_app).post(LOGIN_URL, json={"email": "a@uni.edu", "password": strong_password()})
    finally:
        main_app.dependency_overrides.pop(get_auth_db_path, None)
        main_app.dependency_overrides.pop(get_auth_settings, None)

    assert response.status_code == 503
    assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}


def test_passwords_tokens_and_hashes_are_never_logged(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    user = env.add_user("quiet@uni.edu")
    password = env.passwords[user.email]
    wrong = [strong_password() for _ in range(env.settings.login_max_failed_attempts)]

    with caplog.at_level(logging.DEBUG):
        token = env.token(user.email)
        env.me(token)
        for value in wrong:
            env.login(user.email, value)
        env.login("ghost@uni.edu", password)

    assert "temporarily locked" in caplog.text  # the lock itself is logged, by id only
    record = env.user(user.id)
    for secret in (password, token, record.password_hash, user.password_hash, *wrong, env.settings.jwt_secret_key):
        assert secret not in caplog.text
    assert "quiet@uni.edu" not in caplog.text and "ghost@uni.edu" not in caplog.text


# --------------------------------------------------------------------------- #
# GET /auth/me
# --------------------------------------------------------------------------- #


def test_me_returns_the_safe_profile(env: Env) -> None:
    user = env.add_user("profile@uni.edu", "student", full_name="Ada Student", admission_batch="2024", programme="BSc CS")
    token = env.token(user.email)

    response = env.me(token)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == PROFILE_FIELDS
    assert body == {
        "id": user.id,
        "email": "profile@uni.edu",
        "role": "student",
        "full_name": "Ada Student",
        "admission_batch": "2024",
        "programme": "BSc CS",
        "is_active": True,
        "created_at": body["created_at"],
    }
    assert datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")) == datetime.fromisoformat(user.created_at)


def test_me_never_exposes_internal_fields(env: Env) -> None:
    user = env.add_user("internal@uni.edu", "administrator")
    env.login(user.email, strong_password())  # leaves a failed-login count behind
    token = env.token(user.email)
    record = env.user(user.id)

    response = env.me(token)

    for name in INTERNAL_FIELDS:
        assert name not in response.json()
    assert record.password_hash not in response.text and "$argon2" not in response.text
    assert token not in response.text


def test_me_role_comes_from_database_not_from_token_claims(env: Env) -> None:
    student = env.add_user("forged@uni.edu", "student")
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {
            "sub": str(student.id),
            "ver": student.token_version,
            "jti": secrets.token_hex(16),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
            "iss": env.settings.jwt_issuer,
            "aud": env.settings.jwt_audience,
            "role": "administrator",
        },
        env.settings.jwt_secret_key,
        algorithm="HS256",
    )

    response = env.me(forged)

    assert response.status_code == 200
    assert response.json()["role"] == "student"


@pytest.mark.parametrize(
    "token, scheme",
    [(None, "Bearer"), ("", "Bearer"), ("not-a-jwt", "Bearer"), ("abc.def.ghi", "Bearer"), ("x" * 5000, "Bearer")],
)
def test_me_without_valid_token_is_401(env: Env, token: Optional[str], scheme: str) -> None:
    _assert_unauthenticated(env.me(token, scheme))


def test_me_with_wrong_scheme_is_401(env: Env) -> None:
    user = env.add_user("scheme@uni.edu")

    _assert_unauthenticated(env.me(env.token(user.email), scheme="Basic"))


def test_me_with_expired_token_is_401(env: Env) -> None:
    user = env.add_user("expired-token@uni.edu")
    expired = create_access_token(
        user.id,
        user.token_version,
        settings=env.settings,
        expires_delta=timedelta(minutes=5),
        now=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    _assert_unauthenticated(env.me(expired))


def test_me_with_token_signed_by_another_secret_is_401(env: Env) -> None:
    user = env.add_user("other-secret@uni.edu")
    foreign = create_access_token(user.id, user.token_version, settings=make_settings())

    _assert_unauthenticated(env.me(foreign))


@pytest.mark.parametrize(
    "revoke",
    [
        lambda env, user: increment_token_version(user.id, db_path=env.db_path),
        lambda env, user: update_user(user.id, password=strong_password(), db_path=env.db_path),
        lambda env, user: update_user(user.id, role="administrator", db_path=env.db_path),
        lambda env, user: deactivate_user(user.id, db_path=env.db_path),
    ],
    ids=["token-version", "password-change", "role-change", "deactivation"],
)
def test_me_with_revoked_token_is_401(env: Env, revoke: Any) -> None:
    user = env.add_user("revoke@uni.edu")
    token = env.token(user.email)
    assert env.me(token).status_code == 200

    revoke(env, user)

    _assert_unauthenticated(env.me(token))


def test_me_for_inactive_user_token_is_401(env: Env) -> None:
    user = env.add_user("inactive-token@uni.edu")
    token = env.token(user.email)
    _set_columns(env.db_path, user.id, is_active=0)  # without a token-version bump

    _assert_unauthenticated(env.me(token))


def test_me_for_deleted_user_is_401(env: Env) -> None:
    user = env.add_user("deleted@uni.edu")
    token = env.token(user.email)
    with closing(sqlite3.connect(env.db_path)) as connection:
        connection.execute("DELETE FROM users WHERE id = ?;", (user.id,))
        connection.commit()

    _assert_unauthenticated(env.me(token))


@pytest.mark.parametrize(
    "change",
    [{"token_version": 7}, {"is_active": False}],
    ids=["revoked-between-reads", "deactivated-between-reads"],
)
def test_me_rechecks_the_profile_row_it_returns(env: Env, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]) -> None:
    user = env.add_user("between@uni.edu")
    token = env.token(user.email)
    real_lookup = auth_routes.get_user_by_id

    def changed_after_authentication(*args: Any, **kwargs: Any) -> Optional[UserRecord]:
        record = real_lookup(*args, **kwargs)
        return dataclasses.replace(record, **change)

    monkeypatch.setattr(auth_routes, "get_user_by_id", changed_after_authentication)

    _assert_unauthenticated(env.me(token))


def test_me_profile_lookup_failure_is_generic_503(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    user = env.add_user("lookup@uni.edu")
    token = env.token(user.email)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise sqlite3.OperationalError("database is locked: C:/internal/path")

    monkeypatch.setattr(auth_routes, "get_user_by_id", broken)

    response = env.me(token)

    assert response.status_code == 503
    assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}


def test_profile_schema_declares_only_public_fields() -> None:
    assert set(UserProfileResponse.model_fields) == PROFILE_FIELDS
    assert set(LoginRequest.model_fields) == {"email", "password"}


# --------------------------------------------------------------------------- #
# Router registration, OpenAPI and scope
# --------------------------------------------------------------------------- #


def test_openapi_documents_login_and_me() -> None:
    schema = TestClient(main_app).get("/openapi.json").json()
    paths = schema["paths"]

    login = paths[LOGIN_URL]["post"]
    me = paths[ME_URL]["get"]
    assert set(paths[LOGIN_URL]) == {"post"} and set(paths[ME_URL]) == {"get"}
    assert {"200", "401", "422", "503"} <= set(login["responses"])
    assert {"200", "401", "503"} <= set(me["responses"])
    assert "security" not in login
    assert me["security"] == [{"HTTPBearer": []}]
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
        "description": "JWT access token",
    }

    components = schema["components"]["schemas"]
    assert set(components["LoginRequest"]["properties"]) == {"email", "password"}
    assert set(components["TokenResponse"]["properties"]) == {"access_token", "token_type", "expires_in"}
    assert set(components["UserProfileResponse"]["properties"]) == PROFILE_FIELDS
    for name in INTERNAL_FIELDS:
        assert name not in str(components["UserProfileResponse"])


def test_login_token_opens_routes_protected_in_stage_4(env: Env) -> None:
    """Public routes stay public; protected routes need the token issued by /auth/login."""
    init_database(env.db_path)
    student = env.add_user("stage4@uni.edu", "student", admission_batch="2024", programme="BSc")
    main_app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(env.db_path)
    try:
        assert env.client.get("/").status_code == 200
        assert env.client.get("/api/v1/health").status_code == 200
        _assert_unauthenticated(env.client.get("/api/v1/regulations"))
        _assert_unauthenticated(env.client.get("/api/v1/cohorts/2024/BSc/regulations"))

        headers = {"Authorization": f"Bearer {env.token(student.email)}"}
        assert env.client.get("/api/v1/regulations", headers=headers).status_code == 200
        assert env.client.get("/api/v1/cohorts/2024/BSc/regulations", headers=headers).status_code == 200
    finally:
        main_app.dependency_overrides.pop(regulation_routes.get_db_path, None)
