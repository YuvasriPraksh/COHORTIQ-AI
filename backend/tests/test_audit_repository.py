"""Append-only audit event repository (Part 4, Stage 5, Task 1).

Every test uses a temporary SQLite database; an autouse guard verifies the real
project database file is never modified. No API route or existing flow is
involved: this module exercises the repository only.
"""

from __future__ import annotations

import inspect
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from app import config as app_config
from app.database import get_connection, init_database, insert_regulation_with_pages
from backend.app.audit import repository as audit
from backend.app.audit.repository import (
    ACTIONS,
    MAX_DETAILS_BYTES,
    AuditEvent,
    AuditEventError,
    append_audit_event,
    init_audit_tables,
)
from backend.app.auth.repository import create_user, init_auth_tables
from backend.app.core.config import Settings
from backend.app.core.security import create_access_token, hash_password

COLUMNS = {
    "id",
    "occurred_at",
    "action",
    "outcome",
    "actor_type",
    "actor_user_id",
    "actor_role",
    "target_type",
    "target_id",
    "details",
}
INDEXES = {
    "idx_audit_events_occurred_at",
    "idx_audit_events_actor",
    "idx_audit_events_target",
    "idx_audit_events_action",
}
TRIGGERS = {"audit_events_no_update", "audit_events_no_delete", "audit_events_no_replace"}
SENSITIVE_KEY = re.compile(r"pass|hash|token|secret|jwt|email|question|pdf|content|text|ip|address|name", re.I)


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    yield
    after = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    assert after == before, "The real project database was modified."


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "audit.db"
    init_audit_tables(path)
    return path


def _rows(db_path: Path) -> list[tuple]:
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute("SELECT * FROM audit_events ORDER BY id;").fetchall()


def _schema(db_path: Path, kind: str) -> set[str]:
    with closing(sqlite3.connect(db_path)) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = ?;", (kind,))}


def _login_failed(path: Path, **overrides: Any) -> AuditEvent:
    arguments: dict[str, Any] = {
        "outcome": "failure",
        "actor_type": "anonymous",
        "target_type": "user",
        "target_id": 7,
        "details": {"reason": "invalid_password", "failed_login_count": 2},
        "db_path": path,
    }
    arguments.update(overrides)
    return append_audit_event("auth.login_failed", **arguments)


# Minimal valid arguments for every approved action.
VALID_EVENTS: dict[str, dict[str, Any]] = {
    "user.created": {"outcome": "success", "actor_type": "cli", "target_type": "user", "target_id": 1,
                     "details": {"role": "administrator"}},
    "user.updated": {"outcome": "success", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                     "target_type": "user", "target_id": 2,
                     "details": {"changed_fields": ["programme"], "old_programme": "BSc CS", "new_programme": "BSc DS"}},
    "user.role_changed": {"outcome": "denied", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                          "target_type": "user", "target_id": 1, "details": {"old_role": "administrator", "new_role": "student"}},
    "user.deactivated": {"outcome": "success", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                         "target_type": "user", "target_id": 2},
    "user.reactivated": {"outcome": "success", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                         "target_type": "user", "target_id": 2},
    "user.unlocked": {"outcome": "success", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                      "target_type": "user", "target_id": 2, "details": {"failed_login_count": 5}},
    "user.sessions_revoked": {"outcome": "success", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                              "target_type": "user", "target_id": 2},
    "user.password_reset": {"outcome": "success", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                            "target_type": "user", "target_id": 2},
    "auth.login_succeeded": {"outcome": "success", "actor_type": "user", "actor_user_id": 2, "actor_role": "student",
                             "target_type": "user", "target_id": 2},
    "auth.login_failed": {"outcome": "failure", "actor_type": "anonymous", "target_type": "user", "target_id": 2,
                          "details": {"reason": "account_locked"}},
    "auth.account_locked": {"outcome": "success", "actor_type": "system", "target_type": "user", "target_id": 2,
                            "details": {"failed_login_count": 5, "locked_until": "2026-01-01T10:15:00+00:00"}},
    "regulation.ingested": {"outcome": "failure", "actor_type": "user", "actor_user_id": 1, "actor_role": "administrator",
                            "details": {"reason": "invalid_pdf"}},
    "regulation.verification_changed": {"outcome": "success", "actor_type": "user", "actor_user_id": 1,
                                        "actor_role": "administrator", "target_type": "regulation", "target_id": 4,
                                        "details": {"old_status": "pending", "new_status": "approved"}},
    "authorization.denied": {"outcome": "denied", "actor_type": "user", "actor_user_id": 2, "actor_role": "student",
                             "details": {"method": "PATCH", "path": "/api/v1/regulations/{regulation_id}/verification",
                                         "reason": "insufficient_role"}},
}


# --------------------------------------------------------------------------- #
# Table initialization
# --------------------------------------------------------------------------- #


def test_initialization_creates_table_indexes_and_triggers(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events);")}

    assert columns == COLUMNS
    assert INDEXES <= _schema(db_path, "index")
    assert _schema(db_path, "trigger") == TRIGGERS


def test_initialization_creates_no_other_table(tmp_path: Path) -> None:
    path = tmp_path / "only-audit.db"

    init_audit_tables(path)

    assert _schema(path, "table") - {"sqlite_sequence"} == {"audit_events"}


def test_initialization_is_idempotent_and_keeps_events(db_path: Path) -> None:
    first = _login_failed(db_path)

    init_audit_tables(db_path)
    init_audit_tables(db_path)

    assert _schema(db_path, "trigger") == TRIGGERS
    assert [row[0] for row in _rows(db_path)] == [first.id]


def test_initialization_leaves_existing_tables_and_data_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "existing.db"
    init_database(path)
    init_auth_tables(path)
    insert_regulation_with_pages(
        {
            "document_name": "Existing Rules",
            "regulation_version": "v1",
            "effective_date": "2024-01-01",
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc CS"],
            "upload_date": "2024-01-01",
            "total_pages": 1,
            "processing_status": "extracted",
            "verification_status": "approved",
        },
        [{"page_number": 1, "extracted_text": "Existing text", "extraction_status": "success"}],
        db_path=path,
    )
    create_user("existing@uni.edu", "Kp4#" + secrets.token_urlsafe(18), "student", db_path=path)

    def snapshot() -> tuple[Any, ...]:
        with closing(sqlite3.connect(path)) as connection:
            schema = connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE '%audit%' ORDER BY name;"
            ).fetchall()
            data = tuple(
                connection.execute(f"SELECT * FROM {table} ORDER BY id;").fetchall()
                for table in ("regulations", "document_pages", "users")
            )
        return schema, data

    before = snapshot()
    init_audit_tables(path)
    init_audit_tables(path)

    assert snapshot() == before
    assert "audit_events" in _schema(path, "table")


# --------------------------------------------------------------------------- #
# Appending
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("action", sorted(ACTIONS))
def test_every_approved_action_can_be_appended(db_path: Path, action: str) -> None:
    event = append_audit_event(action, db_path=db_path, **VALID_EVENTS[action])

    assert event.action == action
    assert len(_rows(db_path)) == 1


def test_valid_events_cover_every_approved_action() -> None:
    assert set(VALID_EVENTS) == set(ACTIONS)


def test_appended_event_matches_the_stored_row(db_path: Path) -> None:
    moment = datetime(2026, 3, 1, 9, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    event = _login_failed(db_path, occurred_at=moment)

    [row] = _rows(db_path)
    assert event == AuditEvent(
        id=row[0],
        occurred_at="2026-03-01T04:00:00.000000+00:00",
        action="auth.login_failed",
        outcome="failure",
        actor_type="anonymous",
        actor_user_id=None,
        actor_role=None,
        target_type="user",
        target_id=7,
        details=event.details,
    )
    assert dict(event.details) == {"failed_login_count": 2, "reason": "invalid_password"}
    assert row[9] == '{"failed_login_count":2,"reason":"invalid_password"}'


def test_default_timestamp_is_current_utc(db_path: Path) -> None:
    before = datetime.now(timezone.utc)

    event = _login_failed(db_path)

    stamp = datetime.fromisoformat(event.occurred_at)
    assert stamp.tzinfo is not None and stamp.utcoffset() == timedelta(0)
    assert before - timedelta(seconds=1) <= stamp <= datetime.now(timezone.utc) + timedelta(seconds=1)


def test_events_are_appended_in_order(db_path: Path) -> None:
    ids = [_login_failed(db_path).id for _ in range(3)]

    assert ids == sorted(ids) and len(set(ids)) == 3
    assert [row[0] for row in _rows(db_path)] == ids


def test_details_are_normalized(db_path: Path) -> None:
    event = append_audit_event(
        "auth.account_locked",
        outcome="success",
        actor_type="system",
        target_type="user",
        target_id="12",
        details={"failed_login_count": 5, "locked_until": datetime(2026, 1, 1, 15, 45, tzinfo=timezone(timedelta(hours=5, minutes=30)))},
        db_path=db_path,
    )
    updated = append_audit_event(
        "user.updated",
        outcome="success",
        actor_type="user",
        actor_user_id=1,
        actor_role="administrator",
        target_type="user",
        target_id=12,
        details={"changed_fields": ["programme", "admission_batch"], "new_programme": "  BSc DS  "},
        db_path=db_path,
    )

    assert event.target_id == 12
    assert event.details["locked_until"] == "2026-01-01T10:15:00.000000+00:00"
    assert updated.details == {"changed_fields": ["admission_batch", "programme"], "new_programme": "BSc DS"}


def test_details_cannot_be_modified_through_the_returned_event(db_path: Path) -> None:
    event = _login_failed(db_path)

    with pytest.raises(TypeError):
        event.details["reason"] = "account_locked"  # type: ignore[index]
    with pytest.raises(AttributeError):
        event.outcome = "success"  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"outcome": "success"},  # not allowed for auth.login_failed
        {"outcome": "maybe"},
        {"actor_type": "administrator"},
        {"actor_type": "user"},  # user actor without id/role
        {"actor_type": "user", "actor_user_id": 1},  # missing role
        {"actor_type": "user", "actor_user_id": 1, "actor_role": "superuser"},
        {"actor_user_id": 3},  # anonymous actor with an id
        {"actor_role": "student"},  # anonymous actor with a role
        {"target_type": None, "target_id": None},  # login failures must name a known account
        {"target_type": "regulation"},
        {"target_id": None},
        {"target_id": 0},
        {"target_id": -4},
        {"target_id": True},
        {"target_id": "abc"},
        {"occurred_at": datetime(2026, 1, 1)},  # naive
        {"details": ["reason"]},
    ],
)
def test_invalid_events_are_rejected_and_nothing_is_stored(db_path: Path, overrides: dict[str, Any]) -> None:
    with pytest.raises(AuditEventError):
        _login_failed(db_path, **overrides)

    assert _rows(db_path) == []


@pytest.mark.parametrize("action", ["auth.login", "user.deleted", "", "AUTH.LOGIN_FAILED", None])
def test_unknown_actions_are_rejected(db_path: Path, action: Any) -> None:
    with pytest.raises(AuditEventError):
        append_audit_event(action, outcome="failure", actor_type="anonymous", db_path=db_path)

    assert _rows(db_path) == []


@pytest.mark.parametrize(
    "details",
    [
        {"reason": "Student typed the wrong password twice"},  # free text
        {"reason": "invalid_password", "failed_login_count": -1},
        {"reason": "invalid_password", "failed_login_count": True},
        {"reason": "invalid_password", "failed_login_count": "2"},
    ],
)
def test_detail_values_are_validated(db_path: Path, details: dict[str, Any]) -> None:
    with pytest.raises(AuditEventError):
        _login_failed(db_path, details=details)

    assert _rows(db_path) == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/cohorts/2024/BSc CS/regulations",  # concrete URL with user data
        "/api/v1/regulations?token=abc",
        "api/v1/regulations",
        "/" + "a" * 250,
    ],
)
def test_denied_path_must_be_a_route_template(db_path: Path, path: str) -> None:
    arguments = dict(VALID_EVENTS["authorization.denied"])
    arguments["details"] = {**arguments["details"], "path": path}

    with pytest.raises(AuditEventError):
        append_audit_event("authorization.denied", db_path=db_path, **arguments)


def test_denied_event_target_is_optional_and_typed(db_path: Path) -> None:
    base = VALID_EVENTS["authorization.denied"]

    append_audit_event("authorization.denied", db_path=db_path, **{**base, "target_type": "regulation", "target_id": 3})
    append_audit_event("authorization.denied", db_path=db_path, **{**base, "target_type": "user", "target_id": 9})
    with pytest.raises(AuditEventError):
        append_audit_event("authorization.denied", db_path=db_path, **{**base, "target_type": "document", "target_id": 1})

    assert len(_rows(db_path)) == 2


def test_details_size_is_limited_by_the_database(db_path: Path) -> None:
    oversized = '{"changed_fields":"' + "x" * MAX_DETAILS_BYTES + '"}'

    with closing(sqlite3.connect(db_path)) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO audit_events (occurred_at, action, outcome, actor_type, details) VALUES (?, ?, ?, ?, ?);",
            ("2026-01-01T00:00:00+00:00", "user.updated", "success", "system", oversized),
        )


@pytest.mark.parametrize(
    "values",
    [
        ("x", "auth.login_failed", "unknown", "anonymous", None, None, "{}"),  # bad outcome
        ("x", "auth.login_failed", "failure", "user", None, None, "{}"),  # user actor without id
        ("x", "auth.login_failed", "failure", "anonymous", 5, None, "{}"),  # id without user actor
        ("x", "auth.login_failed", "failure", "anonymous", None, "student", "{}"),  # role without user actor
        ("x", "auth.login_failed", "failure", "anonymous", None, None, "[]"),  # details not an object
        ("x", "auth.login_failed", "failure", "anonymous", None, None, "not json"),
        ("x", "", "failure", "anonymous", None, None, "{}"),
    ],
)
def test_database_constraints_reject_malformed_rows(db_path: Path, values: tuple[Any, ...]) -> None:
    """Defence in depth for anything that bypasses the repository."""
    with closing(sqlite3.connect(db_path)) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO audit_events (occurred_at, action, outcome, actor_type, actor_user_id, actor_role, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?);",
            values,
        )


# --------------------------------------------------------------------------- #
# Append-only behaviour
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET outcome = 'success';",
        "UPDATE audit_events SET details = '{}' WHERE id = 1;",
        "DELETE FROM audit_events WHERE id = 1;",
        "DELETE FROM audit_events;",  # would otherwise use the truncate optimization
        "INSERT OR REPLACE INTO audit_events (id, occurred_at, action, outcome, actor_type, details) "
        "VALUES (1, 'x', 'user.updated', 'success', 'system', '{}');",
        "REPLACE INTO audit_events (id, occurred_at, action, outcome, actor_type, details) "
        "VALUES (1, 'x', 'user.updated', 'success', 'system', '{}');",
        "INSERT INTO audit_events (id, occurred_at, action, outcome, actor_type, details) "
        "VALUES (1, 'x', 'user.updated', 'success', 'system', '{}') "
        "ON CONFLICT(id) DO UPDATE SET outcome = 'denied';",
    ],
)
def test_stored_events_cannot_be_changed_or_removed(db_path: Path, statement: str) -> None:
    _login_failed(db_path)
    before = _rows(db_path)

    with closing(get_connection(db_path)) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute(statement)
        connection.rollback()

    assert _rows(db_path) == before


def test_new_events_can_still_be_appended_with_explicit_new_ids(db_path: Path) -> None:
    _login_failed(db_path)

    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "INSERT INTO audit_events (id, occurred_at, action, outcome, actor_type, details) "
            "VALUES (50, 'x', 'user.updated', 'success', 'system', '{}');"
        )
        connection.commit()

    assert [row[0] for row in _rows(db_path)] == [1, 50]


def test_repository_offers_no_way_to_change_or_remove_events() -> None:
    public = {
        name
        for name, member in inspect.getmembers(audit)
        if callable(member) and not name.startswith("_") and getattr(member, "__module__", None) == audit.__name__
    }

    assert public == {
        "append_audit_event", "init_audit_tables", "list_audit_events",
        "ActionSpec", "AuditEvent", "AuditEventError", "AuditEventPage",
    }
    source = inspect.getsource(audit)
    executable = [line for line in source.splitlines() if "execute(" in line or "_sql =" in line]
    assert not any(re.search(r"\b(UPDATE|DELETE)\b", line) for line in executable)


# --------------------------------------------------------------------------- #
# Sensitive data
# --------------------------------------------------------------------------- #


def test_table_has_no_column_for_sensitive_values(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events);")}

    assert not any(re.search(r"pass|hash|token|secret|email|question|pdf|content|ip|address", column) for column in columns)


def test_no_action_approves_a_sensitive_detail_key() -> None:
    for action, spec in ACTIONS.items():
        for key in spec.detail_keys:
            allowed_name_like = key in {"changed_fields"}
            assert allowed_name_like or not SENSITIVE_KEY.search(key), (action, key)


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "password_hash",
        "hash",
        "token",
        "access_token",
        "jwt",
        "jwt_secret_key",
        "secret",
        "question",
        "question_text",
        "pdf_content",
        "extracted_text",
        "page_text",
        "email",
        "attempted_email",
        "ip_address",
        "client_ip",
        "full_name",
        "user_agent",
    ],
)
def test_sensitive_detail_keys_are_rejected_without_echoing_values(db_path: Path, key: str) -> None:
    secret_value = "Kp4#" + secrets.token_urlsafe(18)

    with pytest.raises(AuditEventError) as excinfo:
        _login_failed(db_path, details={"reason": "invalid_password", key: secret_value})

    assert secret_value not in str(excinfo.value)
    assert _rows(db_path) == []


def _credential_like_values() -> list[str]:
    settings = Settings(app_env="test", jwt_secret_key=secrets.token_urlsafe(48))
    return [
        hash_password("Kp4#" + secrets.token_urlsafe(18)),
        create_access_token(1, 0, settings=settings),
        "prefix " + create_access_token(2, 0, settings=settings)[:60],
        "$2b$12$" + "a" * 53,
        "pbkdf2_sha256$600000$salt$hash",
    ]


@pytest.mark.parametrize("value", _credential_like_values(), ids=["argon2", "jwt", "jwt-fragment", "bcrypt", "pbkdf2"])
def test_credential_shaped_values_are_refused_without_echo(db_path: Path, value: str) -> None:
    for key in ("new_programme", "old_admission_batch"):
        with pytest.raises(AuditEventError) as excinfo:
            append_audit_event(
                "user.updated",
                outcome="success",
                actor_type="user",
                actor_user_id=1,
                actor_role="administrator",
                target_type="user",
                target_id=2,
                details={"changed_fields": ["programme"], key: value[:100]},
                db_path=db_path,
            )
        assert value[:20] not in str(excinfo.value)

    assert _rows(db_path) == []


def test_changed_fields_lists_names_only_and_never_secret_fields(db_path: Path) -> None:
    for names in (["password"], ["password_hash"], ["token_version"], ["email", "email"], [], "role"):
        with pytest.raises(AuditEventError):
            append_audit_event(
                "user.updated",
                outcome="success",
                actor_type="user",
                actor_user_id=1,
                actor_role="administrator",
                target_type="user",
                target_id=2,
                details={"changed_fields": names},
                db_path=db_path,
            )

    assert _rows(db_path) == []


def test_database_file_contains_no_secrets_after_many_events(db_path: Path) -> None:
    password = "Kp4#" + secrets.token_urlsafe(18)
    email = "private.person@uni.edu"
    for action, arguments in VALID_EVENTS.items():
        append_audit_event(action, db_path=db_path, **arguments)
    for details in ({"reason": "invalid_password", "password": password}, {"reason": "invalid_password", "email": email}):
        with pytest.raises(AuditEventError):
            _login_failed(db_path, details=details)

    raw = db_path.read_bytes()
    assert password.encode() not in raw and email.encode() not in raw
    assert len(_rows(db_path)) == len(VALID_EVENTS)


# --------------------------------------------------------------------------- #
# Shared transactions
# --------------------------------------------------------------------------- #


def test_event_on_a_caller_connection_is_not_committed_by_the_repository(db_path: Path) -> None:
    with closing(get_connection(db_path)) as connection:
        event = _login_failed(db_path, db_path=None, connection=connection)
        assert event.id > 0
        assert _rows(db_path) == []  # invisible to other connections until the caller commits
        connection.rollback()

    assert _rows(db_path) == []


def test_event_on_a_caller_connection_is_kept_when_the_caller_commits(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as connection:  # plain connection, no row factory
        event = _login_failed(db_path, db_path=None, connection=connection)
        connection.commit()

    assert [row[0] for row in _rows(db_path)] == [event.id]
    assert dict(event.details) == {"failed_login_count": 2, "reason": "invalid_password"}


def test_rejected_event_leaves_the_caller_transaction_usable(db_path: Path) -> None:
    with closing(get_connection(db_path)) as connection:
        first = _login_failed(db_path, db_path=None, connection=connection)
        with pytest.raises(AuditEventError):
            _login_failed(db_path, db_path=None, connection=connection, details={"token": "x"})
        connection.commit()

    assert [row[0] for row in _rows(db_path)] == [first.id]
