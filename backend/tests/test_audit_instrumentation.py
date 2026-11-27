"""Audit-event instrumentation of existing flows (Part 4, Stage 5).

Covers sign-in and lockout (atomic with the counter update), regulation
ingestion and verification (written after the workflow, with compensation if
the audit write fails), authorization refusals (best effort; the refusal always
stands) and the first-administrator CLI (atomic with account creation).

Every test uses one temporary database for regulations, users and audit
events; an autouse guard verifies the real project database is never modified.
"""

from __future__ import annotations

import io
import json
import logging
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import fitz
import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app.database import get_regulation_by_id, init_database, insert_regulation
from backend.app.api import deps
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.audit.repository import init_audit_tables
from backend.app.auth import repository as auth_repository
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT
from backend.app.auth.repository import apply_login_attempt, create_user, get_user_by_id, init_auth_tables, update_user
from backend.app.main import app
from backend.app.services import auth_service, regulation_service
from backend.scripts import create_admin
from backend.tests.auth_support import SignedInAccount, create_signed_in_account, make_auth_settings, use_auth_database

API = "/api/v1"
LOGIN = f"{API}/auth/login"
INGEST = f"{API}/regulations/ingest"


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
        init_database(db_path)
        init_auth_tables(db_path)
        init_audit_tables(db_path)
        self.settings = make_auth_settings()
        use_auth_database(app, monkeypatch, db_path, self.settings)
        monkeypatch.setitem(app.dependency_overrides, regulation_routes.get_db_path, lambda: str(db_path))
        monkeypatch.setitem(app.dependency_overrides, query_routes.get_db_path, lambda: str(db_path))
        self.client = TestClient(app)

    def account(self, role: str = ROLE_STUDENT, **options: Any) -> SignedInAccount:
        if role == ROLE_STUDENT:
            options.setdefault("admission_batch", "2024")
            options.setdefault("programme", "BSc CS")
        return create_signed_in_account(self.db_path, self.settings, role, **options)

    def user(self, email: str, role: str = ROLE_STUDENT, **options: Any) -> tuple[Any, str]:
        password = strong_password()
        return create_user(email, password, role, db_path=self.db_path, **options), password

    def login(self, email: str, password: str) -> Any:
        return self.client.post(LOGIN, json={"email": email, "password": password})

    def events(self, action: Optional[str] = None, *, since: int = 0) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM audit_events WHERE id > ? ORDER BY id;", (since,)).fetchall()
        events = [{**dict(row), "details": json.loads(row["details"])} for row in rows]
        return [event for event in events if action is None or event["action"] == action]

    def last_event_id(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute("SELECT COALESCE(MAX(id), 0) FROM audit_events;").fetchone()[0]

    def audit_text(self) -> str:
        return json.dumps(self.events())

    def seed_regulation(self, status: Optional[str] = "pending", batch: str = "2024", programme: str = "BSc CS") -> int:
        return insert_regulation(
            {
                "document_name": "Secret Draft Rules",
                "regulation_version": "v1",
                "effective_date": "2024-08-01",
                "applicable_batches": [batch],
                "applicable_programmes": [programme],
                "upload_date": "2024-08-01",
                "total_pages": 0,
                "processing_status": "extracted",
                "verification_status": status,
            },
            db_path=self.db_path,
        )

    def regulation_count(self) -> int:
        with closing(sqlite3.connect(self.db_path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM regulations;").fetchone()[0]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path / "audit-flows.db", monkeypatch)


def _pdf(text: str = "Students must attend all laboratory sessions.") -> bytes:
    document = fitz.open()
    document.new_page().insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def _ingest(env: Env, account: SignedInAccount, content: Optional[bytes] = None, filename: str = "lab-rules.pdf") -> Any:
    return env.client.post(
        INGEST,
        files={"file": (filename, content if content is not None else _pdf(), "application/pdf")},
        data={
            "document_name": "Laboratory Rules Confidential",
            "regulation_version": "2025",
            "effective_date": "2025-01-01",
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc CS"],
        },
        headers=account.headers,
    )


def _failing_append(*_args: Any, **_kwargs: Any) -> None:
    raise sqlite3.OperationalError("simulated audit storage failure")


# --------------------------------------------------------------------------- #
# Sign-in and lockout (atomic with the counter update)
# --------------------------------------------------------------------------- #


def test_successful_login_is_audited_with_the_account_as_actor(env: Env) -> None:
    user, password = env.user("success@uni.edu", ROLE_ADMINISTRATOR)

    assert env.login("SUCCESS@uni.edu", password).status_code == 200

    [event] = env.events()
    assert (event["action"], event["outcome"], event["actor_type"], event["actor_user_id"], event["actor_role"]) == (
        "auth.login_succeeded", "success", "user", user.id, "administrator")
    assert (event["target_type"], event["target_id"], event["details"]) == ("user", user.id, {})


def test_wrong_password_is_audited_against_the_known_account(env: Env) -> None:
    user, _password = env.user("wrong@uni.edu")

    assert env.login("wrong@uni.edu", strong_password()).status_code == 401

    [event] = env.events()
    assert (event["action"], event["outcome"], event["actor_type"], event["actor_user_id"], event["target_id"]) == (
        "auth.login_failed", "failure", "anonymous", None, user.id)
    assert event["details"] == {"reason": "invalid_password", "failed_login_count": 1}


def test_lockout_sequence_is_audited(env: Env) -> None:
    user, password = env.user("lock@uni.edu")
    started = datetime.now(timezone.utc)

    for _ in range(env.settings.login_max_failed_attempts):
        env.login("lock@uni.edu", strong_password())
    env.login("lock@uni.edu", password)  # correct password while locked

    failed = env.events("auth.login_failed")
    assert [e["details"] for e in failed[:5]] == [
        {"reason": "invalid_password", "failed_login_count": count} for count in range(1, 6)
    ]
    assert failed[5]["details"] == {"reason": "account_locked", "failed_login_count": 5}
    [locked] = env.events("auth.account_locked")
    assert (locked["actor_type"], locked["actor_user_id"], locked["target_id"]) == ("system", None, user.id)
    assert locked["details"]["failed_login_count"] == 5
    until = datetime.fromisoformat(locked["details"]["locked_until"])
    assert started + timedelta(minutes=14) < until < started + timedelta(minutes=16)
    assert env.events("auth.login_succeeded") == []


def test_inactive_account_refusal_is_audited(env: Env) -> None:
    user, password = env.user("inactive@uni.edu", is_active=False)

    assert env.login("inactive@uni.edu", password).status_code == 401

    [event] = env.events()
    assert (event["action"], event["target_id"], event["details"]["reason"]) == ("auth.login_failed", user.id, "account_inactive")


def test_unknown_emails_and_invalid_requests_are_never_audited(env: Env) -> None:
    env.user("someone@uni.edu")

    env.login("ghost.person@uni.edu", strong_password())
    env.client.post(LOGIN, json={"email": "not-an-email", "password": "x"})
    env.client.post(LOGIN, json={})
    env.client.get(f"{API}/regulations")  # anonymous 401

    assert env.events() == []
    assert b"ghost.person" not in env.db_path.read_bytes()


def test_missing_signing_secret_records_nothing(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.core.config import Settings

    _user, password = env.user("nosecret@uni.edu")
    monkeypatch.setitem(app.dependency_overrides, deps.get_auth_settings, lambda: Settings(app_env="test", jwt_secret_key=None))

    assert env.login("nosecret@uni.edu", password).status_code == 503
    assert env.events() == []


@pytest.mark.parametrize("correct", [False, True], ids=["failed-login", "successful-login"])
def test_audit_failure_rolls_back_the_sign_in_and_fails_closed(env: Env, monkeypatch: pytest.MonkeyPatch, correct: bool) -> None:
    user, password = env.user("atomic@uni.edu")
    before = get_user_by_id(user.id, db_path=env.db_path)
    monkeypatch.setattr(auth_repository, "append_audit_event", _failing_append)

    response = env.login("atomic@uni.edu", password if correct else strong_password())

    assert response.status_code == 503
    assert "access_token" not in response.text and "simulated" not in response.text
    assert get_user_by_id(user.id, db_path=env.db_path) == before  # counter and last_login_at rolled back
    assert env.events() == []


def test_concurrent_failures_produce_one_event_per_counted_attempt(env: Env) -> None:
    user, _password = env.user("burst@uni.edu")
    threshold = env.settings.login_max_failed_attempts
    barrier = threading.Barrier(threshold + 3)

    def attempt() -> None:
        barrier.wait()
        try:
            auth_service.login("burst@uni.edu", strong_password(), settings=env.settings, db_path=env.db_path)
        except auth_service.LoginFailedError:
            pass

    threads = [threading.Thread(target=attempt) for _ in range(threshold + 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    failed = env.events("auth.login_failed")
    counted = [e["details"]["failed_login_count"] for e in failed if e["details"]["reason"] == "invalid_password"]
    assert sorted(counted) == list(range(1, threshold + 1))  # no lost or duplicated counts
    assert [e["details"]["reason"] for e in failed].count("account_locked") == 3
    assert len(env.events("auth.account_locked")) == 1
    assert get_user_by_id(user.id, db_path=env.db_path).failed_login_count == threshold


def test_password_change_race_is_refused_without_an_event(env: Env) -> None:
    user, _password = env.user("race@uni.edu")
    update_user(user.id, password=strong_password(), db_path=env.db_path)

    result = apply_login_attempt(
        user.id,
        verified_password_hash=user.password_hash,
        password_matches=True,
        max_failed_attempts=5,
        lockout_duration=timedelta(minutes=15),
        db_path=env.db_path,
    )

    assert result is None
    assert env.events() == []


# --------------------------------------------------------------------------- #
# Regulation ingestion (after the workflow; compensated if the audit write fails)
# --------------------------------------------------------------------------- #


def test_successful_ingestion_is_audited(env: Env) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    since = env.last_event_id()

    response = _ingest(env, admin)

    assert response.status_code == 200, response.text
    regulation_id = response.json()["regulation_id"]
    [event] = env.events(since=since)
    assert (event["action"], event["outcome"], event["actor_user_id"], event["actor_role"]) == (
        "regulation.ingested", "success", admin.user.id, "administrator")
    assert (event["target_type"], event["target_id"], event["details"]) == ("regulation", regulation_id, {})
    assert "Laboratory" not in env.audit_text() and "lab-rules" not in env.audit_text()


def test_invalid_pdf_ingestion_is_audited_as_failure(env: Env) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    since = env.last_event_id()

    response = _ingest(env, admin, content=b"%PDF-1.4 definitely not a real pdf")

    assert response.status_code == 422
    [event] = env.events(since=since)
    assert (event["action"], event["outcome"], event["target_id"], event["details"]) == (
        "regulation.ingested", "failure", None, {"reason": "invalid_pdf"})
    assert env.regulation_count() == 0


@pytest.mark.parametrize(
    "message, status_code, reason",
    [("Invalid regulation metadata: document_name is required.", 400, "invalid_metadata"),
     ("Failed to store regulation: disk full", 500, "internal_error")],
)
def test_workflow_failures_are_audited_with_their_reason(env: Env, monkeypatch: pytest.MonkeyPatch, message: str,
                                                         status_code: int, reason: str) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    since = env.last_event_id()
    monkeypatch.setattr(regulation_service, "ingest_regulation", lambda **_k: {"status": "error", "message": message})

    response = _ingest(env, admin)

    assert response.status_code == status_code
    [event] = env.events(since=since)
    assert (event["outcome"], event["details"]) == ("failure", {"reason": reason})
    assert "disk full" not in env.audit_text()


def test_rejections_before_the_workflow_are_not_audited(env: Env) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    since = env.last_event_id()

    response = env.client.post(INGEST, files={"file": ("notes.txt", b"text", "text/plain")},
                               data={"document_name": "x", "regulation_version": "1", "effective_date": "2025-01-01",
                                     "applicable_batches": ["2024"], "applicable_programmes": ["BSc CS"]},
                               headers=admin.headers)

    assert response.status_code == 400
    assert env.events(since=since) == []


def test_audit_failure_after_ingestion_removes_the_regulation(env: Env, monkeypatch: pytest.MonkeyPatch,
                                                              caplog: pytest.LogCaptureFixture) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    since = env.last_event_id()
    monkeypatch.setattr(regulation_routes, "append_audit_event", _failing_append)

    with caplog.at_level(logging.ERROR):
        response = _ingest(env, admin)

    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.INGESTION_INTERNAL_ERROR_DETAIL}
    assert env.regulation_count() == 0  # compensated
    assert env.events(since=since) == []
    assert "removing it" in caplog.text and "simulated" not in response.text


def test_failed_compensation_is_logged_as_critical(env: Env, monkeypatch: pytest.MonkeyPatch,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    monkeypatch.setattr(regulation_routes, "append_audit_event", _failing_append)
    monkeypatch.setattr(regulation_service, "remove_unaudited_regulation", lambda *_a, **_k: False)

    with caplog.at_level(logging.ERROR):
        response = _ingest(env, admin)

    assert response.status_code == 500
    assert any(record.levelno == logging.CRITICAL and "neither audited nor removed" in record.getMessage()
               for record in caplog.records)


def test_failure_event_that_cannot_be_written_keeps_the_original_response(env: Env, monkeypatch: pytest.MonkeyPatch,
                                                                          caplog: pytest.LogCaptureFixture) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    monkeypatch.setattr(regulation_routes, "append_audit_event", _failing_append)

    with caplog.at_level(logging.ERROR):
        response = _ingest(env, admin, content=b"not a pdf at all")

    assert response.status_code == 422
    assert "Could not record a failed regulation ingestion" in caplog.text


# --------------------------------------------------------------------------- #
# Regulation verification (after the workflow; compensated if the audit write fails)
# --------------------------------------------------------------------------- #


def _verify(env: Env, account: SignedInAccount, regulation_id: int, status: str) -> Any:
    return env.client.patch(f"{API}/regulations/{regulation_id}/verification", json={"verification_status": status},
                            headers=account.headers)


def test_verification_change_is_audited_with_old_and_new_status(env: Env) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    regulation_id = env.seed_regulation("pending")
    since = env.last_event_id()

    assert _verify(env, admin, regulation_id, " Approved ").status_code == 200

    [event] = env.events(since=since)
    assert (event["action"], event["outcome"], event["actor_user_id"], event["target_type"], event["target_id"]) == (
        "regulation.verification_changed", "success", admin.user.id, "regulation", regulation_id)
    assert event["details"] == {"old_status": "pending", "new_status": "approved"}
    assert "Secret Draft" not in env.audit_text()


def test_unusual_previous_status_is_recorded_as_null(env: Env) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    regulation_id = env.seed_regulation("v2-approved!")
    since = env.last_event_id()

    assert _verify(env, admin, regulation_id, "rejected").status_code == 200

    assert env.events(since=since)[0]["details"] == {"old_status": None, "new_status": "rejected"}


def test_audit_failure_after_verification_restores_the_status(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    regulation_id = env.seed_regulation("pending")
    since = env.last_event_id()
    monkeypatch.setattr(regulation_routes, "append_audit_event", _failing_append)

    response = _verify(env, admin, regulation_id, "approved")

    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.VERIFICATION_INTERNAL_ERROR_DETAIL}
    assert get_regulation_by_id(regulation_id, db_path=env.db_path)["verification_status"] == "pending"
    assert env.events(since=since) == []


def test_status_restore_never_overwrites_a_concurrent_change(env: Env) -> None:
    regulation_id = env.seed_regulation("rejected")  # another administrator already changed it

    assert not regulation_service.restore_verification_status(regulation_id, expected="approved", previous="pending",
                                                              db_path=env.db_path)
    assert get_regulation_by_id(regulation_id, db_path=env.db_path)["verification_status"] == "rejected"
    assert regulation_service.restore_verification_status(regulation_id, expected="rejected", previous=None,
                                                          db_path=env.db_path)
    assert get_regulation_by_id(regulation_id, db_path=env.db_path)["verification_status"] is None


def test_unchanged_verification_requests_are_not_audited(env: Env) -> None:
    admin = env.account(ROLE_ADMINISTRATOR)
    since = env.last_event_id()

    assert _verify(env, admin, 999_999, "approved").status_code == 404
    assert _verify(env, admin, env.seed_regulation(), "maybe").status_code == 400
    assert env.events(since=since) == []


# --------------------------------------------------------------------------- #
# Authorization refusals (best effort; the refusal always stands)
# --------------------------------------------------------------------------- #


def test_role_refusals_are_audited_with_the_route_template(env: Env) -> None:
    student = env.account()
    regulation_id = env.seed_regulation()
    since = env.last_event_id()

    assert _ingest(env, student).status_code == 403
    assert _verify(env, student, regulation_id, "approved").status_code == 403

    events = env.events(since=since)
    assert [(e["action"], e["outcome"], e["actor_user_id"], e["actor_role"]) for e in events] == [
        ("authorization.denied", "denied", student.user.id, "student")] * 2
    assert [e["details"] for e in events] == [
        {"method": "POST", "path": "/api/v1/regulations/ingest", "reason": "insufficient_role"},
        {"method": "PATCH", "path": "/api/v1/regulations/{regulation_id}/verification", "reason": "insufficient_role"},
    ]
    assert all(e["target_type"] is None for e in events)
    assert get_regulation_by_id(regulation_id, db_path=env.db_path)["verification_status"] == "pending"


def test_cohort_refusals_are_audited_without_the_requested_cohort(env: Env) -> None:
    student = env.account()
    since = env.last_event_id()

    cohort = env.client.get(f"{API}/cohorts/2023/Private Programme/regulations", headers=student.headers)
    query = env.client.post(f"{API}/query/ask", headers=student.headers,
                            json={"question": "Confidential question?", "admission_batch": "2023", "programme": "Private Programme"})

    assert cohort.status_code == query.status_code == 403
    events = env.events(since=since)
    assert [e["details"] for e in events] == [
        {"method": "GET", "path": "/api/v1/cohorts/{admission_batch}/{programme}/regulations", "reason": "cohort_mismatch"},
        {"method": "POST", "path": "/api/v1/query/ask", "reason": "cohort_mismatch"},
    ]
    assert "Private Programme" not in env.audit_text() and "Confidential" not in env.audit_text()


def test_permitted_requests_and_hidden_regulations_record_no_refusal(env: Env) -> None:
    student = env.account()
    admin = env.account(ROLE_ADMINISTRATOR)
    pending = env.seed_regulation("pending")
    since = env.last_event_id()

    assert env.client.get(f"{API}/cohorts/2024/BSc CS/regulations", headers=student.headers).status_code == 200
    assert env.client.get(f"{API}/cohorts/2023/Other/regulations", headers=admin.headers).status_code == 200
    assert env.client.get(f"{API}/regulations/{pending}", headers=student.headers).status_code == 404

    assert env.events("authorization.denied", since=since) == []


def test_refusal_stands_when_its_audit_event_cannot_be_written(env: Env, monkeypatch: pytest.MonkeyPatch,
                                                               caplog: pytest.LogCaptureFixture) -> None:
    student = env.account()
    monkeypatch.setattr(deps, "append_audit_event", _failing_append)

    with caplog.at_level(logging.ERROR):
        response = _ingest(env, student)
        cohort = env.client.get(f"{API}/cohorts/2023/Other/regulations", headers=student.headers)

    assert response.status_code == 403 and response.json() == {"detail": deps.FORBIDDEN_DETAIL}
    assert cohort.status_code == 403
    assert caplog.text.count("Could not record an authorization refusal") == 2
    assert env.regulation_count() == 0


# --------------------------------------------------------------------------- #
# First-administrator CLI (atomic with account creation)
# --------------------------------------------------------------------------- #


def _run_cli(db_path: Path, email: str, password: str, full_name: Optional[str] = None) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    argv = ["--email", email, "--db-path", str(db_path)] + (["--full-name", full_name] if full_name else [])
    code = create_admin.main(argv, read_password=lambda _p: password, read_line=lambda _p: email,
                             is_interactive=lambda: True, out=out, err=err)
    return code, out.getvalue() + err.getvalue()


def _cli_events(db_path: Path) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return [{**dict(r), "details": json.loads(r["details"])} for r in connection.execute("SELECT * FROM audit_events;")]


def test_cli_bootstrap_creates_the_audit_table_and_records_the_administrator(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh" / "cohortiq.db"
    password = strong_password()

    code, output = _run_cli(db_path, "first.admin@admin.smvec.ac.in", password, full_name="Private Name")

    assert code == 0, output
    [event] = _cli_events(db_path)
    user = auth_repository.get_user_by_email("first.admin@admin.smvec.ac.in", db_path=db_path)
    assert (event["action"], event["outcome"], event["actor_type"], event["actor_user_id"], event["actor_role"]) == (
        "user.created", "success", "cli", None, None)
    assert (event["target_type"], event["target_id"], event["details"]) == ("user", user.id, {"role": "administrator"})
    audit = json.dumps(_cli_events(db_path))
    for personal in ("first.admin", "Private Name"):
        assert personal not in audit  # the CLI's own success message names the email by design
    for secret in (password, user.password_hash):
        assert secret not in audit and secret not in output


def test_cli_duplicate_records_nothing(tmp_path: Path) -> None:
    db_path = tmp_path / "dup.db"
    assert _run_cli(db_path, "dup@admin.smvec.ac.in", strong_password())[0] == 0

    code, output = _run_cli(db_path, "DUP@admin.smvec.ac.in", strong_password())

    assert code == 1 and "already exists" in output
    assert len(_cli_events(db_path)) == 1


def test_cli_audit_failure_creates_no_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "atomic-cli.db"
    password = strong_password()
    monkeypatch.setattr(auth_repository, "append_audit_event", _failing_append)

    code, output = _run_cli(db_path, "atomic.admin@admin.smvec.ac.in", password)

    assert code == 1
    assert "could not be stored. No account was created." in output
    assert "simulated" not in output and password not in output
    assert auth_repository.get_user_by_email("atomic.admin@admin.smvec.ac.in", db_path=db_path) is None
    assert _cli_events(db_path) == []


# --------------------------------------------------------------------------- #
# Sensitive data across all instrumented flows
# --------------------------------------------------------------------------- #


def test_no_secrets_reach_the_audit_log(env: Env) -> None:
    admin = env.account(ROLE_ADMINISTRATOR, email="private.admin@uni.edu")
    student = env.account(email="private.student@uni.edu")
    attempt = strong_password()
    env.login("private.student@uni.edu", attempt)
    _ingest(env, admin)
    _ingest(env, student)
    env.client.post(f"{API}/query/ask", headers=student.headers,
                    json={"question": "What is my secret grade?", "admission_batch": "1999", "programme": "Hidden"})

    audit = env.audit_text()
    raw = env.db_path.read_bytes()
    for secret in (admin.password, student.password, attempt, admin.token, student.token,
                   get_user_by_id(student.user.id, db_path=env.db_path).password_hash,
                   env.settings.jwt_secret_key, "private.admin", "private.student", "secret grade", "Hidden",
                   "Laboratory Rules Confidential", "lab-rules.pdf", "laboratory sessions", "testclient"):
        assert secret not in audit, secret
    assert attempt.encode() not in raw and student.password.encode() not in raw
    with closing(sqlite3.connect(env.db_path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_events);")}
    assert not any(word in column for column in columns for word in ("ip", "address", "email", "agent"))
