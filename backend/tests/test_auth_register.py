"""Student self-registration (POST /api/v1/auth/register).

Uses a temporary database; an autouse guard verifies the real project database
is never modified.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from backend.app.api.deps import get_auth_settings
from backend.app.api.v1 import auth as auth_routes
from backend.app.audit import repository as audit_repository
from backend.app.audit.repository import init_audit_tables
from backend.app.auth.models import ROLE_STUDENT
from backend.app.auth.repository import get_user_by_email, init_auth_tables
from backend.app.core.config import Settings
from backend.app.main import app
from backend.tests.auth_support import make_auth_settings, use_auth_database

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
PASSWORD = "Campus-Rules-2024!"
PROFILE_FIELDS = {"id", "email", "role", "full_name", "admission_batch", "programme", "is_active", "created_at"}


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    yield
    after = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    assert after == before, "The real project database was modified."


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    db_path = tmp_path / "register.db"
    init_auth_tables(db_path)
    init_audit_tables(db_path)
    monkeypatch.delenv("STUDENT_EMAIL_DOMAIN", raising=False)
    monkeypatch.delenv("REGISTRATION_EMAIL_DOMAIN", raising=False)
    use_auth_database(app, monkeypatch, db_path, make_auth_settings())
    return TestClient(app), db_path


def body(**overrides: Any) -> dict[str, Any]:
    data = {
        "email": "asha.k@student.smvec.ac.in",
        "password": PASSWORD,
        "admission_batch": "2024",
        "programme": "B-tech - CSE",
        "full_name": "Asha K",
    }
    data.update(overrides)
    return {key: value for key, value in data.items() if value is not None}


def events(db_path: Path) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM audit_events ORDER BY id;").fetchall()
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


def test_registers_a_student_and_can_sign_in(env: tuple[TestClient, Path]) -> None:
    client, db_path = env

    response = client.post(REGISTER, json=body(email="  Asha.K@Student.SMVEC.ac.in "))

    assert response.status_code == 201, response.text
    profile = response.json()
    assert set(profile) == PROFILE_FIELDS
    assert (profile["email"], profile["role"], profile["admission_batch"], profile["programme"]) == (
        "asha.k@student.smvec.ac.in", ROLE_STUDENT, "2024", "B-tech - CSE")
    assert response.headers["cache-control"] == "no-store"
    assert "access_token" not in response.text and "$argon2" not in response.text

    login = client.post(LOGIN, json={"email": "asha.k@student.smvec.ac.in", "password": PASSWORD})
    assert login.status_code == 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.json()["role"] == ROLE_STUDENT


def test_registration_is_audited_without_personal_data(env: tuple[TestClient, Path]) -> None:
    client, db_path = env

    user_id = client.post(REGISTER, json=body()).json()["id"]

    [created] = [event for event in events(db_path) if event["action"] == "user.created"]
    assert (created["outcome"], created["actor_type"], created["actor_user_id"]) == ("success", "anonymous", None)
    assert (created["target_type"], created["target_id"]) == ("user", user_id)
    assert created["details"] == {"role": "student", "admission_batch": "2024", "programme": "B-tech - CSE"}
    raw = json.dumps(events(db_path))
    for secret in ("asha.k@student.smvec.ac.in", PASSWORD, "Asha K", "$argon2"):
        assert secret not in raw


@pytest.mark.parametrize(
    "email",
    [
        "asha@gmail.com",
        "asha@student.smvec.ac.in.evil.com",
        "asha@evil.student.smvec.ac.in",
        "asha@student.smvec.ac",
        "asha@student.smvecac.in",
        "smvec.ac.in",
        "asha@@student.smvec.ac.in",
        "asha@smvec.ac.in",
    ],
)
def test_only_the_college_domain_is_accepted(env: tuple[TestClient, Path], email: str) -> None:
    client, db_path = env

    response = client.post(REGISTER, json=body(email=email))

    assert response.status_code == 422
    assert get_user_by_email("asha@student.smvec.ac.in", db_path=db_path) is None
    assert PASSWORD not in response.text


def test_domain_message_is_clear(env: tuple[TestClient, Path]) -> None:
    client, _ = env
    response = client.post(REGISTER, json=body(email="asha@gmail.com"))
    assert "ending in @student.smvec.ac.in" in response.text


def test_domain_is_configurable(env: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = env
    settings = Settings(
        app_env="test",
        jwt_secret_key="a-secure-test-key-with-many-characters",
        student_email_domain="example.edu",
    )
    app.dependency_overrides[get_auth_settings] = lambda: settings

    assert client.post(REGISTER, json=body(email="asha@example.edu")).status_code == 201
    assert client.post(REGISTER, json=body(email="ravi@student.smvec.ac.in")).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"role": "administrator"},
        {"role": "staff"},
        {"role": "student"},
        {"is_active": False},
        {"password_hash": "$argon2id$x"},
    ],
)
def test_unknown_fields_such_as_role_are_rejected(env: tuple[TestClient, Path], overrides: dict[str, Any]) -> None:
    client, db_path = env

    response = client.post(REGISTER, json={**body(), **overrides})

    assert response.status_code == 422
    assert get_user_by_email("asha.k@student.smvec.ac.in", db_path=db_path) is None


@pytest.mark.parametrize("password", ["short1!A", "alllowercaseletters", "asha.k-smvec-2024!", "password1234!A"])
def test_password_policy_applies(env: tuple[TestClient, Path], password: str) -> None:
    client, db_path = env

    response = client.post(REGISTER, json=body(password=password))

    assert response.status_code == 422
    assert password not in response.text
    assert get_user_by_email("asha.k@student.smvec.ac.in", db_path=db_path) is None


@pytest.mark.parametrize(
    "overrides",
    [{"admission_batch": None}, {"programme": None}, {"admission_batch": "   "}, {"programme": ""}],
)
def test_cohort_is_required(env: tuple[TestClient, Path], overrides: dict[str, Any]) -> None:
    client, _ = env
    assert client.post(REGISTER, json=body(**overrides)).status_code == 422


def test_duplicate_email_is_refused_in_any_letter_case(env: tuple[TestClient, Path]) -> None:
    client, db_path = env
    assert client.post(REGISTER, json=body()).status_code == 201

    response = client.post(REGISTER, json=body(email="ASHA.K@student.smvec.ac.in", password="Another-Pass-99!"))

    assert response.status_code == 409
    assert response.json() == {"detail": auth_routes.DUPLICATE_ACCOUNT_DETAIL}
    assert len([e for e in events(db_path) if e["action"] == "user.created"]) == 1


def test_audit_failure_creates_no_account(env: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    client, db_path = env

    def broken(*_: Any, **__: Any) -> Any:
        raise audit_repository.AuditEventError("rejected")

    monkeypatch.setattr("backend.app.auth.repository.append_audit_event", broken)

    response = client.post(REGISTER, json=body())

    assert response.status_code == 503
    assert response.json() == {"detail": auth_routes.REGISTRATION_ERROR_DETAIL}
    assert get_user_by_email("asha.k@student.smvec.ac.in", db_path=db_path) is None


def test_registration_does_not_need_a_signing_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Accounts can be created even before JWT_SECRET_KEY is set; sign-in then reports 503."""
    db_path = tmp_path / "nosecret.db"
    init_auth_tables(db_path)
    init_audit_tables(db_path)
    from backend.app.core.config import Settings

    use_auth_database(app, monkeypatch, db_path, Settings(app_env="test", jwt_secret_key=None))
    client = TestClient(app)

    assert client.post(REGISTER, json=body()).status_code == 201
    assert client.post(LOGIN, json={"email": "asha.k@student.smvec.ac.in", "password": PASSWORD}).status_code == 503
