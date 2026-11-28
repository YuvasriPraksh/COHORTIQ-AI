"""First-administrator bootstrap script (Part 4, Stage 2).

The script is driven with injected prompt functions and output streams, plus
two subprocess runs of ``python -m backend.scripts.create_admin``. Every run uses
a temporary database; passwords are generated at runtime.
"""

from __future__ import annotations

import io
import logging
import os
import secrets
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from backend.app.auth.repository import create_user, get_user_by_email, init_auth_tables
from backend.app.core.security import verify_password
from backend.app.main import app as api_app
from backend.scripts import create_admin

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def strong_password() -> str:
    return "Kp4#" + secrets.token_urlsafe(18)


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    yield
    after = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    assert after == before, "The real project database was modified."


@pytest.fixture(autouse=True)
def _configured_administrator_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMINISTRATOR_EMAIL_DOMAIN", "uni.edu")


class Run:
    def __init__(self, code: int, out: str, err: str, prompts: list[str]) -> None:
        self.code, self.out, self.err, self.prompts = code, out, err, prompts

    @property
    def text(self) -> str:
        return self.out + self.err


def run_script(
    argv: list[str],
    *,
    passwords: Optional[list[Any]] = None,
    lines: Optional[list[Any]] = None,
    interactive: bool = True,
) -> Run:
    prompts: list[str] = []
    password_queue = list(passwords or [])
    line_queue = list(lines or [])

    def next_value(queue: list[Any]) -> str:
        value = queue.pop(0)
        if isinstance(value, BaseException) or (isinstance(value, type) and issubclass(value, BaseException)):
            raise value
        return value

    def read_password(prompt: str) -> str:
        prompts.append(prompt)
        return next_value(password_queue)

    def read_line(prompt: str) -> str:
        prompts.append(prompt)
        return next_value(line_queue)

    out, err = io.StringIO(), io.StringIO()
    code = create_admin.main(
        argv,
        read_password=read_password,
        read_line=read_line,
        is_interactive=lambda: interactive,
        out=out,
        err=err,
    )
    return Run(code, out.getvalue(), err.getvalue(), prompts)


def _user_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with closing(sqlite3.connect(db_path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table';")}
        if "users" not in tables:
            return 0
        return connection.execute("SELECT COUNT(*) FROM users;").fetchone()[0]


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "cohortiq.db"


# --------------------------------------------------------------------------- #
# Successful creation
# --------------------------------------------------------------------------- #


def test_creates_administrator_without_exposing_the_password(db_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    password = strong_password()

    with caplog.at_level(logging.DEBUG):
        run = run_script(
            ["--email", "Registrar@Uni.EDU", "--full-name", "Registrar Office", "--db-path", str(db_path)],
            passwords=[password, password],
        )

    assert run.code == 0, run.text
    assert run.prompts == ["Password: ", "Confirm password: "]
    user = get_user_by_email("registrar@uni.edu", db_path=db_path)
    assert user is not None
    assert (user.role, user.is_active, user.full_name) == ("administrator", True, "Registrar Office")
    assert verify_password(password, user.password_hash)
    assert "registrar@uni.edu" in run.out and f"id={user.id}" in run.out
    for secret in (password, user.password_hash, "$argon2"):
        assert secret not in run.text
        assert secret not in caplog.text


def test_initializes_a_fresh_database(db_path: Path) -> None:
    password = strong_password()

    assert run_script(["--email", "first@uni.edu", "--db-path", str(db_path)], passwords=[password, password]).code == 0

    with closing(sqlite3.connect(db_path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table';")}
    assert {"regulations", "document_pages", "users"} <= tables


def test_prompts_for_email_when_not_given(db_path: Path) -> None:
    password = strong_password()

    run = run_script(["--db-path", str(db_path)], lines=["  Dean@Uni.EDU  "], passwords=[password, password])

    assert run.code == 0
    assert run.prompts[0] == "Administrator email: "
    assert get_user_by_email("dean@uni.edu", db_path=db_path) is not None


# --------------------------------------------------------------------------- #
# Password validation and confirmation
# --------------------------------------------------------------------------- #


def test_weak_password_is_rejected_then_strong_accepted(db_path: Path) -> None:
    weak, strong = "Password1!xx", strong_password()

    run = run_script(["--email", "policy@uni.edu", "--db-path", str(db_path)], passwords=[weak, strong, strong])

    assert run.code == 0
    assert "Password rejected" in run.err
    assert "common words" in run.err
    assert weak not in run.text and strong not in run.text


def test_mismatched_confirmation_retries(db_path: Path) -> None:
    first, second = strong_password(), strong_password()

    run = run_script(["--email", "confirm@uni.edu", "--db-path", str(db_path)], passwords=[first, second, second, second])

    assert run.code == 0
    assert "Passwords do not match." in run.err
    user = get_user_by_email("confirm@uni.edu", db_path=db_path)
    assert verify_password(second, user.password_hash) and not verify_password(first, user.password_hash)
    assert first not in run.text and second not in run.text


def test_too_many_failed_attempts_creates_nothing(db_path: Path) -> None:
    run = run_script(
        ["--email", "attempts@uni.edu", "--db-path", str(db_path)],
        passwords=["short", strong_password(), "different-Value-9!", "weakweakweakweak"],
    )

    assert run.code == 1
    assert "Too many unsuccessful attempts" in run.err
    assert _user_count(db_path) == 0


# --------------------------------------------------------------------------- #
# Duplicates and invalid input
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("existing_role", ["administrator", "student"])
def test_existing_email_in_any_case_or_role_is_never_modified(db_path: Path, existing_role: str) -> None:
    db_path.parent.mkdir(parents=True)
    init_auth_tables(db_path)
    original = create_user("owner@uni.edu", strong_password(), existing_role, db_path=db_path)

    run = run_script(["--email", "OWNER@Uni.edu", "--db-path", str(db_path)], passwords=[strong_password()] * 2)

    assert run.code == 1
    assert "already exists" in run.err
    assert run.prompts == [], "No password should be requested for an existing account."
    assert get_user_by_email("owner@uni.edu", db_path=db_path) == original  # not upgraded or changed
    assert _user_count(db_path) == 1


@pytest.mark.parametrize("email", ["not-an-email", "", "a@b", "two@@uni.edu"])
def test_invalid_email_creates_nothing_and_touches_no_database(db_path: Path, email: str) -> None:
    run = run_script(["--email", email, "--db-path", str(db_path)], passwords=[strong_password()] * 2)

    assert run.code == 1
    assert "not valid" in run.err
    assert not db_path.exists()


def test_wrong_administrator_domain_creates_nothing(db_path: Path) -> None:
    run = run_script(
        ["--email", "admin@other.edu", "--db-path", str(db_path)],
        passwords=[strong_password(), strong_password()],
    )

    assert run.code == 1
    assert "must end in @uni.edu" in run.err
    assert run.prompts == []
    assert not db_path.exists()


def test_invalid_full_name_creates_nothing(db_path: Path) -> None:
    password = strong_password()

    run = run_script(["--email", "name@uni.edu", "--full-name", "n" * 201, "--db-path", str(db_path)], passwords=[password, password])

    assert run.code == 1
    assert "full_name" in run.err and password not in run.text
    assert _user_count(db_path) == 0


# --------------------------------------------------------------------------- #
# Interactive-only, cancellation and argument safety
# --------------------------------------------------------------------------- #


def test_non_interactive_run_is_refused_before_touching_the_database(db_path: Path) -> None:
    run = run_script(["--email", "pipe@uni.edu", "--db-path", str(db_path)], passwords=[strong_password()] * 2, interactive=False)

    assert run.code == 1
    assert "interactive terminal" in run.err
    assert run.prompts == []
    assert not db_path.exists()


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, EOFError])
def test_cancelling_at_the_password_prompt_creates_nothing(db_path: Path, interrupt: type[BaseException]) -> None:
    run = run_script(["--email", "cancel@uni.edu", "--db-path", str(db_path)], passwords=[interrupt])

    assert run.code == 1
    assert "Cancelled. No account was created." in run.err
    assert _user_count(db_path) == 0


def test_cancelling_at_the_email_prompt_creates_nothing(db_path: Path) -> None:
    run = run_script(["--db-path", str(db_path)], lines=[EOFError])

    assert run.code == 1
    assert not db_path.exists()


@pytest.mark.parametrize("argv", [["--password", "Secret-Value-123!"], ["--pass", "x"], ["-p", "x"], ["--email", "a@uni.edu", "Secret-Value-123!"]])
def test_password_cannot_be_given_as_an_argument(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        create_admin.main(argv, is_interactive=lambda: True)

    assert excinfo.value.code == 2


def test_parser_defines_no_password_option() -> None:
    destinations = {action.dest for action in create_admin.build_parser()._actions}
    assert destinations == {"help", "email", "full_name", "db_path"}


def test_api_cannot_create_or_promote_administrators() -> None:
    """Administrators are created only by this script.

    The API can create students and administrator-provisioned staff, each via a
    role-fixed route that accepts no role field.
    Promotion requests are refused by the repository (tested in
    test_admin_users_api.py). There is still no registration or sign-up route.
    """
    schema = TestClient(api_app).get("/openapi.json").json()
    paths = schema["paths"]

    assert {method for method in paths["/api/v1/auth/login"]} == {"post"}
    assert {method for method in paths["/api/v1/auth/me"]} == {"get"}
    creation = paths["/api/v1/admin/users"]["post"]
    body_ref = creation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    body = schema["components"]["schemas"][body_ref.rsplit("/", 1)[-1]]
    assert body_ref.endswith("/StudentCreateRequest")
    assert "role" not in body["properties"] and body.get("additionalProperties") is False
    assert {method for method in paths["/api/v1/admin/users/{user_id}/role"]} == {"patch"}
    assert set(paths) == {
        "/",
        "/api/v1/health",
        "/api/v1/regulations",
        "/api/v1/regulations/{regulation_id}",
        "/api/v1/regulations/{regulation_id}/pages",
        "/api/v1/cohorts",
        "/api/v1/cohorts/{admission_batch}/{programme}/regulations",
        "/api/v1/regulations/ingest",
        "/api/v1/regulations/{regulation_id}/verification",
        "/api/v1/change-radar/reviews",
        "/api/v1/change-radar/reviews/{review_id}",
        "/api/v1/updates",
        "/api/v1/impact-twin",
        "/api/v1/query/ask",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/register",  # students only (no role field)
        "/api/v1/admin/users",
        "/api/v1/admin/users/staff",
        "/api/v1/admin/users/{user_id}",
        "/api/v1/admin/users/{user_id}/role",
        "/api/v1/admin/users/{user_id}/password",
        "/api/v1/admin/users/{user_id}/deactivate",
        "/api/v1/admin/users/{user_id}/reactivate",
        "/api/v1/admin/users/{user_id}/unlock",
        "/api/v1/admin/users/{user_id}/revoke-sessions",
        "/api/v1/admin/audit-events",  # read-only listing
    }
    assert {method for method in paths["/api/v1/admin/audit-events"]} == {"get"}
    assert not any(word in path for path in paths for word in ("signup", "promote"))
    # Self-registration exists but can only create students: its schema has no role field.
    assert {method for method in paths["/api/v1/auth/register"]} == {"post"}
    register_ref = paths["/api/v1/auth/register"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    register_body = schema["components"]["schemas"][register_ref.rsplit("/", 1)[-1]]
    assert "role" not in register_body["properties"] and register_body.get("additionalProperties") is False
    assert not any(
        path.startswith("/api/v1/admin/") and "admin/users" not in path and path != "/api/v1/admin/audit-events"
        for path in paths
    )


# --------------------------------------------------------------------------- #
# Running as a module
# --------------------------------------------------------------------------- #


def _run_module(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-m", "backend.scripts.create_admin", *args],
        cwd=PROJECT_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )


def test_module_help_runs_and_offers_no_password_option() -> None:
    result = _run_module("--help")

    assert result.returncode == 0
    assert "python -m backend.scripts.create_admin" in result.stdout
    assert "--password" not in result.stdout


def test_module_refuses_piped_input(tmp_path: Path) -> None:
    db_path = tmp_path / "piped.db"
    password = strong_password()

    result = _run_module("--email", "piped@uni.edu", "--db-path", str(db_path), stdin=f"{password}\n{password}\n")

    assert result.returncode == 1
    assert "interactive terminal" in result.stderr
    assert password not in result.stdout + result.stderr
    assert not db_path.exists()
