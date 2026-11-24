"""Users database repository (Part 4, Stage 2).

Every test uses a temporary SQLite database; an autouse guard verifies the real
project database file is never modified. Passwords are generated at runtime.
"""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import config as app_config
from app.database import get_document_pages, init_database, insert_regulation_with_pages
from backend.app.api.deps import (
    AUTH_UNAVAILABLE_DETAIL,
    AuthenticatedUser,
    get_auth_db_path,
    get_auth_settings,
    get_current_user,
    require_role,
)
from backend.app.auth import repository
from backend.app.auth.password_policy import validate_password_strength
from backend.app.auth.repository import (
    PUBLIC_USER_FIELDS,
    DuplicateEmailError,
    SQLiteUserStore,
    UserRecord,
    WeakPasswordError,
    create_user,
    deactivate_user,
    get_user_by_email,
    get_user_by_id,
    increment_token_version,
    init_auth_tables,
    serialize_user,
    to_authenticated_user,
    update_user,
)
from backend.app.core.config import Settings
from backend.app.core.security import create_access_token, verify_password

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def strong_password() -> str:
    return "Qz7!" + secrets.token_urlsafe(18)


def _signature(path: Path) -> tuple[int, int] | None:
    return (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = _signature(real_db)
    yield
    assert _signature(real_db) == before, "The real project database was modified."


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "users.db"
    init_database(path)
    init_auth_tables(path)
    return path


def _raw(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with closing(sqlite3.connect(db_path)) as connection:
        rows = connection.execute(sql, params).fetchall()
        connection.commit()
    return rows


def _raw_insert(db_path: Path, **overrides: Any) -> None:
    now = datetime.now(timezone.utc).isoformat()
    values = {
        "email": f"raw-{secrets.token_hex(4)}@example.edu",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2g",
        "role": "student",
        "is_active": 1,
        "token_version": 0,
        "failed_login_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(f"INSERT INTO users ({columns}) VALUES ({placeholders});", tuple(values.values()))
        connection.commit()


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def test_users_table_has_the_expected_columns(db_path: Path) -> None:
    columns = [row[1] for row in _raw(db_path, "PRAGMA table_info(users);")]

    assert columns == [
        "id", "email", "password_hash", "role", "full_name", "admission_batch", "programme",
        "is_active", "token_version", "failed_login_count", "locked_until", "last_login_at",
        "created_at", "updated_at",
    ]


def test_init_auth_tables_is_idempotent_and_keeps_users(db_path: Path) -> None:
    create_user("keep@example.edu", strong_password(), "student", db_path=db_path)

    init_auth_tables(db_path)
    init_auth_tables(db_path)

    assert get_user_by_email("keep@example.edu", db_path=db_path) is not None


def test_existing_regulation_tables_are_unchanged(tmp_path: Path) -> None:
    reference = tmp_path / "reference.db"
    with_users = tmp_path / "with_users.db"
    for path in (reference, with_users):
        init_database(path)
        insert_regulation_with_pages(
            {
                "document_name": "R2024",
                "regulation_version": "1",
                "applicable_batches": ["2024"],
                "applicable_programmes": ["CSE"],
                "upload_date": "2024-07-01",
                "verification_status": "approved",
            },
            [{"page_number": 1, "text": "Attendance is 75 percent.", "status": "success"}],
            db_path=path,
        )
    schema_sql = "SELECT name, sql FROM sqlite_master WHERE name IN ('regulations', 'document_pages') ORDER BY name;"
    before = _raw(with_users, schema_sql)
    rows_before = _raw(with_users, "SELECT * FROM regulations;"), _raw(with_users, "SELECT * FROM document_pages;")

    init_auth_tables(with_users)
    create_user("admin@example.edu", strong_password(), "administrator", db_path=with_users)

    assert _raw(with_users, schema_sql) == before == _raw(reference, schema_sql)
    assert (_raw(with_users, "SELECT * FROM regulations;"), _raw(with_users, "SELECT * FROM document_pages;")) == rows_before
    for table in ("regulations", "document_pages"):
        assert _raw(with_users, f"PRAGMA table_info({table});") == _raw(reference, f"PRAGMA table_info({table});")
    assert get_document_pages(1, db_path=with_users)[0]["extracted_text"] == "Attendance is 75 percent."


def test_streamlit_database_initialization_does_not_create_users_table(tmp_path: Path) -> None:
    path = tmp_path / "streamlit_only.db"
    init_database(path)  # the function the Streamlit app calls

    tables = {row[0] for row in _raw(path, "SELECT name FROM sqlite_master WHERE type = 'table';")}
    assert "users" not in tables
    assert {"regulations", "document_pages"} <= tables


def test_app_package_has_no_users_table_or_auth_imports() -> None:
    for source in (PROJECT_ROOT / "app").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "CREATE TABLE IF NOT EXISTS users" not in text, source
        assert "backend.app.auth" not in text, source


# --------------------------------------------------------------------------- #
# Database-level constraints
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["superuser", "Student", "ADMINISTRATOR", "admin", ""])
def test_database_rejects_invalid_roles(db_path: Path, role: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _raw_insert(db_path, role=role)


@pytest.mark.parametrize(
    "password_hash",
    ["PlainTextPassword123!", "", "$2b$12$abcdefghijklmnopqrstuv", "$argon2i$v=19$m=65536,t=3,p=4$abc$def"],
)
def test_database_rejects_non_argon2id_password_hashes(db_path: Path, password_hash: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _raw_insert(db_path, password_hash=password_hash)


def test_database_email_uniqueness_is_case_insensitive(db_path: Path) -> None:
    _raw_insert(db_path, email="Case@Example.edu")

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _raw_insert(db_path, email="case@EXAMPLE.EDU")


@pytest.mark.parametrize(
    "overrides",
    [{"is_active": 2}, {"token_version": -1}, {"failed_login_count": -1}, {"email": "   "}],
    ids=["is_active", "token_version", "failed_login_count", "blank_email"],
)
def test_database_rejects_invalid_values(db_path: Path, overrides: dict[str, Any]) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _raw_insert(db_path, **overrides)


# --------------------------------------------------------------------------- #
# create_user
# --------------------------------------------------------------------------- #


def test_create_user_stores_only_an_argon2id_hash(db_path: Path) -> None:
    password = strong_password()

    user = create_user("Student.One@Example.EDU ", password, "student", full_name="Student One",
                       admission_batch="2024", programme="BSc CS", db_path=db_path)

    assert user.email == "student.one@example.edu"
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(password, user.password_hash)
    assert (user.role, user.is_active, user.token_version, user.failed_login_count) == ("student", True, 0, 0)
    assert (user.admission_batch, user.programme, user.full_name) == ("2024", "BSc CS", "Student One")
    assert user.created_at == user.updated_at
    stored = _raw(db_path, "SELECT * FROM users;")
    assert password not in repr(stored)
    assert password.encode() not in db_path.read_bytes()


def test_create_user_rejects_duplicate_email_in_any_case(db_path: Path) -> None:
    create_user("dup@example.edu", strong_password(), "student", db_path=db_path)

    for variant in ("dup@example.edu", "DUP@Example.EDU", "  Dup@example.edu  "):
        with pytest.raises(DuplicateEmailError):
            create_user(variant, strong_password(), "administrator", db_path=db_path)
    assert len(_raw(db_path, "SELECT id FROM users;")) == 1


@pytest.mark.parametrize("email", ["", "   ", "no-at-sign", "a@b", "two@@example.edu", "sp ace@example.edu", None, 42, "x" * 250 + "@e.du"])
def test_create_user_rejects_invalid_emails(db_path: Path, email: Any) -> None:
    with pytest.raises(ValueError):
        create_user(email, strong_password(), "student", db_path=db_path)


@pytest.mark.parametrize("role", ["superuser", "Student", "admin", "", None])
def test_create_user_rejects_invalid_roles(db_path: Path, role: Any) -> None:
    with pytest.raises(ValueError):
        create_user("role@example.edu", strong_password(), role, db_path=db_path)


@pytest.mark.parametrize(
    "password",
    ["Short1!", "alllowercaseonly", "Password123!x", "Qwerty!23456", "aaaaaaaaaaaaaaaaaaaaaaaa", "mariagonzalez!X9", "", "   " * 6],
    ids=["short", "one_class", "common_password", "common_qwerty", "repetitive", "contains_email_name", "empty", "blank"],
)
def test_create_user_rejects_weak_passwords_without_echoing_them(db_path: Path, password: str) -> None:
    with pytest.raises(WeakPasswordError) as excinfo:
        create_user("mariagonzalez@example.edu", password, "student", db_path=db_path)

    if password.strip():
        assert password not in str(excinfo.value)
    assert _raw(db_path, "SELECT id FROM users;") == []


def test_passphrase_without_symbols_is_accepted(db_path: Path) -> None:
    passphrase = "correct horse battery staple river"
    assert validate_password_strength(passphrase) == []
    create_user("phrase@example.edu", passphrase, "student", db_path=db_path)


def test_create_user_validates_profile_lengths(db_path: Path) -> None:
    with pytest.raises(ValueError, match="admission_batch"):
        create_user("long@example.edu", strong_password(), "student", admission_batch="x" * 101, db_path=db_path)
    with pytest.raises(ValueError, match="is_active"):
        create_user("flag@example.edu", strong_password(), "student", is_active=1, db_path=db_path)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #


def test_lookups_by_id_and_email(db_path: Path) -> None:
    user = create_user("lookup@example.edu", strong_password(), "administrator", db_path=db_path)

    assert get_user_by_id(user.id, db_path=db_path) == user
    assert get_user_by_id(str(user.id), db_path=db_path) == user
    assert get_user_by_email("LOOKUP@example.edu", db_path=db_path) == user
    assert get_user_by_email("  lookup@EXAMPLE.edu ", db_path=db_path) == user


@pytest.mark.parametrize("user_id", [999, "999", "abc", "", "1.0", "-1", 0, -1, None, True, "١"])
def test_unknown_or_malformed_ids_return_none(db_path: Path, user_id: Any) -> None:
    assert get_user_by_id(user_id, db_path=db_path) is None


@pytest.mark.parametrize("email", ["missing@example.edu", "not-an-email", "", None, 7])
def test_unknown_or_malformed_emails_return_none(db_path: Path, email: Any) -> None:
    assert get_user_by_email(email, db_path=db_path) is None


def test_lookups_use_parameterized_queries(db_path: Path) -> None:
    create_user("safe@example.edu", strong_password(), "student", db_path=db_path)

    assert get_user_by_email("x' OR '1'='1@example.edu", db_path=db_path) is None
    assert get_user_by_id("1 OR 1=1", db_path=db_path) is None
    assert len(_raw(db_path, "SELECT id FROM users;")) == 1


# --------------------------------------------------------------------------- #
# Updates, token versions and deactivation
# --------------------------------------------------------------------------- #


def test_update_profile_fields_without_revoking_tokens(db_path: Path) -> None:
    user = create_user("profile@example.edu", strong_password(), "student", db_path=db_path)

    updated = update_user(user.id, full_name="New Name", admission_batch="2025", programme="BSc IT", db_path=db_path)

    assert (updated.full_name, updated.admission_batch, updated.programme) == ("New Name", "2025", "BSc IT")
    assert updated.token_version == user.token_version
    assert updated.created_at == user.created_at
    assert updated.updated_at > user.updated_at


def test_password_change_rehashes_and_revokes_tokens(db_path: Path) -> None:
    old_password, new_password = strong_password(), strong_password()
    user = create_user("rotate@example.edu", old_password, "student", db_path=db_path)

    updated = update_user(user.id, password=new_password, db_path=db_path)

    assert updated.password_hash != user.password_hash
    assert verify_password(new_password, updated.password_hash)
    assert not verify_password(old_password, updated.password_hash)
    assert updated.token_version == user.token_version + 1


def test_weak_new_password_is_rejected_and_nothing_changes(db_path: Path) -> None:
    user = create_user("weakchange@example.edu", strong_password(), "student", db_path=db_path)

    with pytest.raises(WeakPasswordError):
        update_user(user.id, password="weak", db_path=db_path)

    assert get_user_by_id(user.id, db_path=db_path) == user


def test_role_change_revokes_tokens(db_path: Path) -> None:
    user = create_user("promote@example.edu", strong_password(), "student", db_path=db_path)

    updated = update_user(user.id, role="administrator", db_path=db_path)
    unchanged = update_user(user.id, role="administrator", db_path=db_path)

    assert updated.role == "administrator" and updated.token_version == 1
    assert unchanged.token_version == 1  # same role: no extra revocation


def test_email_change_is_normalized_unique_and_revokes_tokens(db_path: Path) -> None:
    create_user("taken@example.edu", strong_password(), "student", db_path=db_path)
    user = create_user("old@example.edu", strong_password(), "student", db_path=db_path)

    with pytest.raises(DuplicateEmailError):
        update_user(user.id, email="TAKEN@example.edu", db_path=db_path)
    updated = update_user(user.id, email=" New@Example.edu ", db_path=db_path)

    assert updated.email == "new@example.edu"
    assert updated.token_version == 1


def test_update_rejects_invalid_values(db_path: Path) -> None:
    user = create_user("invalid@example.edu", strong_password(), "student", db_path=db_path)

    for kwargs in (
        {"role": "superuser"},
        {"is_active": "yes"},
        {"failed_login_count": -1},
        {"failed_login_count": True},
        {"locked_until": "not a time"},
        {"locked_until": datetime(2030, 1, 1)},
        {"programme": "p" * 101},
    ):
        with pytest.raises(ValueError):
            update_user(user.id, db_path=db_path, **kwargs)
    with pytest.raises(TypeError):
        update_user(user.id, db_path=db_path, password_hash="$argon2id$forged")  # type: ignore[call-arg]
    assert get_user_by_id(user.id, db_path=db_path) == user


def test_update_login_tracking_fields(db_path: Path) -> None:
    user = create_user("tracking@example.edu", strong_password(), "student", db_path=db_path)
    lock = datetime.now(timezone.utc) + timedelta(minutes=15)

    updated = update_user(user.id, failed_login_count=3, locked_until=lock, last_login_at=lock.isoformat(), db_path=db_path)

    assert updated.failed_login_count == 3
    assert datetime.fromisoformat(updated.locked_until) == lock
    assert updated.token_version == 0
    cleared = update_user(user.id, failed_login_count=0, locked_until=None, db_path=db_path)
    assert cleared.failed_login_count == 0 and cleared.locked_until is None


def test_update_unknown_user_returns_none(db_path: Path) -> None:
    assert update_user(999, full_name="Nobody", db_path=db_path) is None


def test_update_with_no_changes_returns_existing(db_path: Path) -> None:
    user = create_user("noop@example.edu", strong_password(), "student", db_path=db_path)
    assert update_user(user.id, db_path=db_path) == user


def test_token_version_can_be_incremented(db_path: Path) -> None:
    user = create_user("version@example.edu", strong_password(), "student", db_path=db_path)

    assert increment_token_version(user.id, db_path=db_path) == 1
    assert increment_token_version(str(user.id), db_path=db_path) == 2
    assert update_user(user.id, increment_token_version=True, db_path=db_path).token_version == 3
    assert increment_token_version(999, db_path=db_path) is None
    assert increment_token_version("abc", db_path=db_path) is None


def test_deactivate_user_disables_and_revokes(db_path: Path) -> None:
    user = create_user("leaver@example.edu", strong_password(), "student", db_path=db_path)

    assert deactivate_user(user.id, db_path=db_path) is True
    deactivated = get_user_by_id(user.id, db_path=db_path)

    assert deactivated.is_active is False
    assert deactivated.token_version == user.token_version + 1
    assert deactivate_user(999, db_path=db_path) is False
    assert deactivate_user("abc", db_path=db_path) is False


# --------------------------------------------------------------------------- #
# Safe serialization
# --------------------------------------------------------------------------- #


def test_serialize_user_never_exposes_secrets(db_path: Path) -> None:
    user = create_user("public@example.edu", strong_password(), "student", db_path=db_path)

    public = serialize_user(user)

    assert set(public) == set(PUBLIC_USER_FIELDS)
    for hidden in ("password_hash", "token_version", "failed_login_count", "locked_until"):
        assert hidden not in public
    assert user.password_hash not in repr(public)
    assert "$argon2" not in str(public)


def test_user_record_repr_hides_the_hash(db_path: Path) -> None:
    user = create_user("repr@example.edu", strong_password(), "student", db_path=db_path)

    assert "password_hash" not in repr(user)
    assert user.password_hash not in repr(user)
    assert user.password_hash not in str(user)


def test_authenticated_user_view_has_no_credentials(db_path: Path) -> None:
    user = create_user("view@example.edu", strong_password(), "student", admission_batch="2024", db_path=db_path)

    view = to_authenticated_user(user)

    assert view == AuthenticatedUser(id=str(user.id), role="student", is_active=True, token_version=0,
                                     email="view@example.edu", admission_batch="2024", programme=None)


# --------------------------------------------------------------------------- #
# get_current_user loads users from the real users table
# --------------------------------------------------------------------------- #


class Api:
    def __init__(self, client: TestClient, settings: Settings, db_path: Path) -> None:
        self.client = client
        self.settings = settings
        self.db_path = db_path

    def token(self, user: UserRecord, version: int | None = None) -> str:
        return create_access_token(user.id, user.token_version if version is None else version, settings=self.settings)

    def get(self, path: str, token: str | None = None):
        return self.client.get(path, headers={"Authorization": f"Bearer {token}"} if token else {})


@pytest.fixture
def api(db_path: Path) -> Api:
    settings = Settings(app_env="test", jwt_secret_key=secrets.token_urlsafe(48))
    app = FastAPI()

    @app.get("/me")
    def me(user: AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        return {"id": user.id, "role": user.role, "email": user.email}

    @app.get("/admin")
    def admin(user: AuthenticatedUser = Depends(require_role("administrator"))) -> dict[str, Any]:
        return {"id": user.id}

    # Only the settings and database path are overridden: the real
    # get_user_store / SQLiteUserStore path is exercised.
    app.dependency_overrides[get_auth_settings] = lambda: settings
    app.dependency_overrides[get_auth_db_path] = lambda: str(db_path)
    return Api(TestClient(app), settings, db_path)


def test_get_current_user_loads_active_user_from_database(api: Api) -> None:
    user = create_user("active@example.edu", strong_password(), "student", db_path=api.db_path)

    response = api.get("/me", api.token(user))

    assert response.status_code == 200
    assert response.json() == {"id": str(user.id), "role": "student", "email": "active@example.edu"}


def test_inactive_user_is_rejected(api: Api) -> None:
    user = create_user("inactive@example.edu", strong_password(), "student", db_path=api.db_path)
    token = api.token(user)
    assert api.get("/me", token).status_code == 200

    deactivate_user(user.id, db_path=api.db_path)

    assert api.get("/me", token).status_code == 401
    # Even a token carrying the new version is refused while the account is inactive.
    assert api.get("/me", api.token(user, version=user.token_version + 1)).status_code == 401


def test_password_change_revokes_existing_tokens(api: Api) -> None:
    user = create_user("revoke@example.edu", strong_password(), "student", db_path=api.db_path)
    old_token = api.token(user)

    updated = update_user(user.id, password=strong_password(), db_path=api.db_path)

    assert api.get("/me", old_token).status_code == 401
    assert api.get("/me", api.token(updated)).status_code == 200


def test_role_is_read_from_database_on_every_request(api: Api) -> None:
    user = create_user("promoted@example.edu", strong_password(), "student", db_path=api.db_path)
    assert api.get("/admin", api.token(user)).status_code == 403

    promoted = update_user(user.id, role="administrator", db_path=api.db_path)

    assert api.get("/admin", api.token(user)).status_code == 401  # pre-promotion token revoked
    assert api.get("/admin", api.token(promoted)).status_code == 200


def test_unknown_user_is_rejected(api: Api) -> None:
    ghost = create_access_token(12345, 0, settings=api.settings)
    assert api.get("/me", ghost).status_code == 401


def test_missing_users_table_fails_closed(api: Api, tmp_path: Path) -> None:
    no_users = tmp_path / "no_users_table.db"
    init_database(no_users)
    api.client.app.dependency_overrides[get_auth_db_path] = lambda: str(no_users)

    response = api.get("/me", create_access_token(1, 0, settings=api.settings))

    assert response.status_code == 503
    assert response.json() == {"detail": AUTH_UNAVAILABLE_DETAIL}
    assert api.get("/me").status_code == 401


def test_sqlite_user_store_maps_records(db_path: Path) -> None:
    user = create_user("store@example.edu", strong_password(), "administrator", db_path=db_path)
    store = SQLiteUserStore(db_path)

    assert store.get_user_by_id(str(user.id)) == to_authenticated_user(user)
    assert store.get_user_by_id("999") is None
    assert store.get_user_by_id("not-a-number") is None


def test_startup_creates_users_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.main import app

    isolated = app_config.Settings(
        gemini_api_key=None,
        database_path=tmp_path / "startup" / "cohortiq.db",
        upload_dir=tmp_path / "startup" / "uploads",
        extracted_dir=tmp_path / "startup" / "extracted",
    )
    monkeypatch.setattr("backend.app.main.get_storage_settings", lambda: isolated)
    monkeypatch.setattr("app.database.get_settings", lambda: isolated)

    with TestClient(app):
        tables = {row[0] for row in _raw(isolated.database_path, "SELECT name FROM sqlite_master WHERE type='table';")}

    assert {"regulations", "document_pages", "users"} <= tables
