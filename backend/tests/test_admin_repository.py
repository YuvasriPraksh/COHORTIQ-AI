"""Administrator user-management repository (Part 4, Stage 5, Task 2).

Every test uses a temporary SQLite database; an autouse guard verifies the real
project database file is never modified. Passwords are generated at runtime.
No API route or existing flow is involved.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest

from app import config as app_config
from backend.app.audit.repository import AuditEventError, init_audit_tables
from backend.app.auth import admin_repository as admin
from backend.app.auth.admin_repository import (
    MAX_PAGE_SIZE,
    AdminActionRefusedError,
    UserNotFoundError,
    change_role,
    create_student,
    deactivate_account,
    list_users,
    reactivate_account,
    reset_password,
    revoke_sessions,
    unlock_account,
    update_profile,
)
from backend.app.auth.models import AuthenticatedUser
from backend.app.auth.repository import (
    DuplicateEmailError,
    UserRecord,
    WeakPasswordError,
    create_user,
    get_user_by_id,
    init_auth_tables,
    is_locked,
    to_authenticated_user,
    update_user,
)
from backend.app.core.security import verify_password


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
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.passwords: dict[int, str] = {}
        init_auth_tables(db_path)
        init_audit_tables(db_path)

    def user(self, role: str = "student", *, batch: Optional[str] = "2024", programme: Optional[str] = "BSc CS",
             active: bool = True) -> UserRecord:
        password = strong_password()
        record = create_user(
            f"{role}-{secrets.token_hex(5)}@uni.edu",
            password,
            role,
            admission_batch=batch if role == "student" else None,
            programme=programme if role == "student" else None,
            is_active=active,
            db_path=self.db_path,
        )
        self.passwords[record.id] = password
        return record

    def admin(self) -> AuthenticatedUser:
        return to_authenticated_user(self.user("administrator"))

    def get(self, user_id: int) -> UserRecord:
        record = get_user_by_id(user_id, db_path=self.db_path)
        assert record is not None
        return record

    def events(self, action: Optional[str] = None) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM audit_events ORDER BY id;").fetchall()
        events = [{**dict(row), "details": json.loads(row["details"])} for row in rows]
        return [event for event in events if action is None or event["action"] == action]

    def active_admins(self) -> int:
        return list_users(role="administrator", is_active=True, db_path=self.db_path).total


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path / "admin.db")


def _event_matches(event: dict[str, Any], action: str, outcome: str, actor: Any, target_id: int) -> bool:
    return (
        event["action"] == action
        and event["outcome"] == outcome
        and event["actor_type"] == "user"
        and event["actor_user_id"] == int(actor.id)
        and event["actor_role"] == "administrator"
        and event["target_type"] == "user"
        and event["target_id"] == target_id
    )


# --------------------------------------------------------------------------- #
# list_users
# --------------------------------------------------------------------------- #


def test_list_users_on_an_empty_database(env: Env) -> None:
    page = list_users(db_path=env.db_path)

    assert (page.users, page.total, page.limit, page.offset) == ((), 0, 50, 0)


def test_list_users_filters_and_orders(env: Env) -> None:
    administrator = env.user("administrator")
    a = env.user(batch="2024", programme="BSc CS")
    b = env.user(batch="2024", programme="BA Econ")
    c = env.user(batch="2023", programme="BSc CS", active=False)

    def ids(**filters: Any) -> list[int]:
        return [user.id for user in list_users(db_path=env.db_path, **filters).users]

    assert ids() == [administrator.id, a.id, b.id, c.id]
    assert ids(role="administrator") == [administrator.id]
    assert ids(role="student") == [a.id, b.id, c.id]
    assert ids(is_active=False) == [c.id]
    assert ids(is_active=True, role="student") == [a.id, b.id]
    assert ids(admission_batch="2024") == [a.id, b.id]
    assert ids(admission_batch="2024", programme="BSc CS") == [a.id]
    assert ids(programme="  BSc CS  ") == [a.id, c.id]
    assert ids(programme="bsc cs") == []  # exact, like regulation applicability


def test_list_users_paginates_with_a_stable_total(env: Env) -> None:
    created = [env.user().id for _ in range(7)]

    first = list_users(limit=3, db_path=env.db_path)
    second = list_users(limit=3, offset=3, db_path=env.db_path)
    last = list_users(limit=3, offset=6, db_path=env.db_path)
    beyond = list_users(limit=3, offset=50, db_path=env.db_path)

    assert [u.id for u in first.users + second.users + last.users] == created
    assert {first.total, second.total, last.total, beyond.total} == {7}
    assert beyond.users == ()


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": MAX_PAGE_SIZE + 1},
        {"limit": -5},
        {"limit": True},
        {"limit": "10"},
        {"offset": -1},
        {"offset": 1_000_001},
        {"offset": 1.5},
        {"role": "superuser"},
        {"is_active": "yes"},
        {"admission_batch": "   "},
        {"programme": "x" * 101},
    ],
)
def test_list_users_rejects_invalid_arguments(env: Env, arguments: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        list_users(db_path=env.db_path, **arguments)


def test_list_users_accepts_the_maximum_page_size(env: Env) -> None:
    assert list_users(limit=MAX_PAGE_SIZE, db_path=env.db_path).limit == MAX_PAGE_SIZE


# --------------------------------------------------------------------------- #
# create_student
# --------------------------------------------------------------------------- #


def test_create_student_stores_hash_and_audits_without_secrets(env: Env) -> None:
    actor = env.admin()
    password = strong_password()

    created = create_student(
        actor,
        email="New.Student@Uni.EDU",
        password=password,
        admission_batch=" 2024 ",
        programme="BSc CS",
        full_name="Private Person",
        db_path=env.db_path,
    )

    assert (created.email, created.role, created.is_active) == ("new.student@uni.edu", "student", True)
    assert (created.admission_batch, created.programme) == ("2024", "BSc CS")
    assert verify_password(password, created.password_hash)
    [event] = env.events()
    assert _event_matches(event, "user.created", "success", actor, created.id)
    assert event["details"] == {"role": "student", "admission_batch": "2024", "programme": "BSc CS"}
    raw = env.db_path.read_bytes()
    audit_text = json.dumps(env.events())
    for secret in (password, created.password_hash, "new.student@uni.edu", "Private Person"):
        assert secret not in audit_text
    assert password.encode() not in raw


def test_create_student_has_no_role_parameter() -> None:
    assert "role" not in inspect.signature(create_student).parameters


@pytest.mark.parametrize("batch, programme", [(None, "BSc CS"), ("2024", None), ("", "BSc CS"), ("2024", "   ")])
def test_create_student_requires_a_cohort(env: Env, batch: Any, programme: Any) -> None:
    actor = env.admin()

    with pytest.raises(ValueError):
        create_student(actor, email="c@uni.edu", password=strong_password(), admission_batch=batch, programme=programme,
                       db_path=env.db_path)

    assert list_users(role="student", db_path=env.db_path).total == 0
    assert env.events() == []


def test_create_student_enforces_the_password_policy(env: Env) -> None:
    actor = env.admin()

    with pytest.raises(WeakPasswordError):
        create_student(actor, email="weak@uni.edu", password="password12345", admission_batch="2024",
                       programme="BSc CS", db_path=env.db_path)

    assert list_users(role="student", db_path=env.db_path).total == 0
    assert env.events() == []


def test_create_student_rejects_duplicate_email_in_any_case(env: Env) -> None:
    actor = env.admin()
    existing = env.user()

    with pytest.raises(DuplicateEmailError):
        create_student(actor, email=existing.email.upper(), password=strong_password(), admission_batch="2024",
                       programme="BSc CS", db_path=env.db_path)

    assert env.get(existing.id) == existing
    assert env.events() == []


# --------------------------------------------------------------------------- #
# update_profile
# --------------------------------------------------------------------------- #


def test_update_profile_changes_cohort_and_audits_old_and_new(env: Env) -> None:
    actor = env.admin()
    student = env.user(batch="2024", programme="BSc CS")

    updated = update_profile(actor, student.id, admission_batch="2025", programme="BSc DS", full_name="New Name",
                             db_path=env.db_path)

    assert (updated.admission_batch, updated.programme, updated.full_name) == ("2025", "BSc DS", "New Name")
    assert updated.token_version == student.token_version  # cohort is read per request; no revocation needed
    [event] = env.events()
    assert _event_matches(event, "user.updated", "success", actor, student.id)
    assert event["details"] == {
        "changed_fields": ["admission_batch", "full_name", "programme"],
        "old_admission_batch": "2024",
        "new_admission_batch": "2025",
        "old_programme": "BSc CS",
        "new_programme": "BSc DS",
    }
    assert "New Name" not in json.dumps(env.events())


def test_update_profile_with_unchanged_values_writes_nothing(env: Env) -> None:
    actor = env.admin()
    student = env.user(batch="2024", programme="BSc CS")

    result = update_profile(actor, student.id, admission_batch=" 2024 ", programme="BSc CS", db_path=env.db_path)

    assert result == student == env.get(student.id)
    assert env.events() == []


@pytest.mark.parametrize("changes", [{"admission_batch": None}, {"programme": ""}, {"admission_batch": "  "}])
def test_students_must_keep_a_cohort(env: Env, changes: dict[str, Any]) -> None:
    actor = env.admin()
    student = env.user()

    with pytest.raises(ValueError):
        update_profile(actor, student.id, db_path=env.db_path, **changes)

    assert env.get(student.id) == student
    assert env.events() == []


def test_update_profile_rejects_invalid_values_and_unknown_users(env: Env) -> None:
    actor = env.admin()
    student = env.user()

    with pytest.raises(ValueError):
        update_profile(actor, student.id, full_name="n" * 201, db_path=env.db_path)
    with pytest.raises(UserNotFoundError):
        update_profile(actor, 999_999, full_name="Someone", db_path=env.db_path)

    assert env.get(student.id) == student
    assert env.events() == []


# --------------------------------------------------------------------------- #
# change_role
# --------------------------------------------------------------------------- #


def test_administrator_can_demote_another_administrator(env: Env) -> None:
    actor = env.admin()
    other = env.user("administrator")

    demoted = change_role(actor, other.id, "student", db_path=env.db_path)

    assert demoted.role == "student"
    assert demoted.token_version == other.token_version + 1  # existing tokens revoked
    [event] = env.events()
    assert _event_matches(event, "user.role_changed", "success", actor, other.id)
    assert event["details"] == {"old_role": "administrator", "new_role": "student"}


def test_promotion_to_administrator_is_refused_and_audited(env: Env) -> None:
    actor = env.admin()
    student = env.user()

    with pytest.raises(AdminActionRefusedError) as excinfo:
        change_role(actor, student.id, "administrator", db_path=env.db_path)

    assert excinfo.value.reason == "role_not_assignable"
    assert env.get(student.id) == student
    [event] = env.events()
    assert _event_matches(event, "user.role_changed", "denied", actor, student.id)
    assert event["details"] == {"old_role": "student", "new_role": "administrator", "reason": "role_not_assignable"}


def test_administrator_cannot_change_own_role(env: Env) -> None:
    actor = env.admin()
    env.user("administrator")  # another administrator exists, so this is about self-change

    with pytest.raises(AdminActionRefusedError) as excinfo:
        change_role(actor, actor.id, "student", db_path=env.db_path)

    assert excinfo.value.reason == "self_change"
    assert env.get(int(actor.id)).role == "administrator"
    assert env.events()[0]["details"]["reason"] == "self_change"


def test_unchanged_role_writes_nothing(env: Env) -> None:
    actor = env.admin()
    student = env.user()

    assert change_role(actor, student.id, "student", db_path=env.db_path) == student
    assert env.events() == []


def test_unknown_role_is_rejected(env: Env) -> None:
    with pytest.raises(ValueError):
        change_role(env.admin(), env.user().id, "superuser", db_path=env.db_path)


# --------------------------------------------------------------------------- #
# deactivate / reactivate
# --------------------------------------------------------------------------- #


def test_deactivate_and_reactivate_a_student(env: Env) -> None:
    actor = env.admin()
    student = env.user()

    deactivated = deactivate_account(actor, student.id, db_path=env.db_path)
    reactivated = reactivate_account(actor, student.id, db_path=env.db_path)

    assert not deactivated.is_active and deactivated.token_version == student.token_version + 1
    assert reactivated.is_active
    assert reactivated.token_version == deactivated.token_version  # old tokens stay revoked
    assert [(e["action"], e["outcome"]) for e in env.events()] == [
        ("user.deactivated", "success"),
        ("user.reactivated", "success"),
    ]


def test_administrator_can_deactivate_another_administrator(env: Env) -> None:
    actor = env.admin()
    other = env.user("administrator")

    assert not deactivate_account(actor, other.id, db_path=env.db_path).is_active
    assert env.active_admins() == 1


def test_administrator_cannot_deactivate_themselves(env: Env) -> None:
    actor = env.admin()
    env.user("administrator")

    with pytest.raises(AdminActionRefusedError) as excinfo:
        deactivate_account(actor, actor.id, db_path=env.db_path)

    assert excinfo.value.reason == "self_change"
    assert env.get(int(actor.id)).is_active
    [event] = env.events()
    assert _event_matches(event, "user.deactivated", "denied", actor, int(actor.id))


def test_repeated_activation_changes_write_nothing(env: Env) -> None:
    actor = env.admin()
    inactive = env.user(active=False)
    active = env.user()

    assert deactivate_account(actor, inactive.id, db_path=env.db_path) == inactive
    assert reactivate_account(actor, active.id, db_path=env.db_path) == active
    assert env.events() == []


# --------------------------------------------------------------------------- #
# unlock / revoke sessions / reset password
# --------------------------------------------------------------------------- #


def test_unlock_clears_lock_and_counter(env: Env) -> None:
    actor = env.admin()
    student = env.user()
    update_user(student.id, failed_login_count=5, locked_until=datetime.now(timezone.utc) + timedelta(minutes=10),
                db_path=env.db_path)
    assert is_locked(env.get(student.id))

    unlocked = unlock_account(actor, student.id, db_path=env.db_path)

    assert (unlocked.failed_login_count, unlocked.locked_until) == (0, None)
    assert not is_locked(unlocked)
    [event] = env.events()
    assert _event_matches(event, "user.unlocked", "success", actor, student.id)
    assert event["details"] == {"failed_login_count": 5}


def test_unlocking_an_unlocked_account_writes_nothing(env: Env) -> None:
    student = env.user()

    assert unlock_account(env.admin(), student.id, db_path=env.db_path) == student
    assert env.events() == []


def test_revoke_sessions_increments_token_version(env: Env) -> None:
    actor = env.admin()
    student = env.user()

    revoked = revoke_sessions(actor, student.id, db_path=env.db_path)

    assert revoked.token_version == student.token_version + 1
    assert _event_matches(env.events()[0], "user.sessions_revoked", "success", actor, student.id)


def test_reset_password_for_a_student(env: Env) -> None:
    actor = env.admin()
    student = env.user()
    new_password = strong_password()

    updated = reset_password(actor, student.id, new_password, db_path=env.db_path)

    assert verify_password(new_password, updated.password_hash)
    assert not verify_password(env.passwords[student.id], updated.password_hash)
    assert updated.token_version == student.token_version + 1
    [event] = env.events()
    assert _event_matches(event, "user.password_reset", "success", actor, student.id)
    assert event["details"] == {}
    audit_text = json.dumps(env.events())
    assert new_password not in audit_text and updated.password_hash not in audit_text


def test_reset_password_enforces_the_policy(env: Env) -> None:
    student = env.user()

    with pytest.raises(WeakPasswordError):
        reset_password(env.admin(), student.id, "password12345", db_path=env.db_path)

    assert env.get(student.id) == student
    assert env.events() == []


@pytest.mark.parametrize("target, reason", [("self", "self_change"), ("other_admin", "administrator_account")])
def test_administrator_passwords_cannot_be_reset_here(env: Env, target: str, reason: str) -> None:
    actor = env.admin()
    other = env.user("administrator")
    target_id = int(actor.id) if target == "self" else other.id
    before = env.get(target_id)

    with pytest.raises(AdminActionRefusedError) as excinfo:
        reset_password(actor, target_id, strong_password(), db_path=env.db_path)

    assert excinfo.value.reason == reason
    assert env.get(target_id) == before
    [event] = env.events()
    assert _event_matches(event, "user.password_reset", "denied", actor, target_id)
    assert event["details"] == {"reason": reason}


def test_reset_password_is_refused_if_the_account_changed_meanwhile(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    student = env.user()
    stale = dataclasses.replace(student, email="old.address@uni.edu")
    monkeypatch.setattr(admin, "get_user_by_id", lambda *_a, **_k: stale)

    with pytest.raises(ValueError, match="retry"):
        reset_password(env.admin(), student.id, strong_password(), db_path=env.db_path)

    assert env.get(student.id) == student
    assert env.events() == []


# --------------------------------------------------------------------------- #
# The acting administrator is re-checked inside every transaction
# --------------------------------------------------------------------------- #

OPERATIONS: dict[str, Callable[..., Any]] = {
    "create_student": lambda actor, target, db: create_student(
        actor, email=f"s-{secrets.token_hex(4)}@uni.edu", password=strong_password(), admission_batch="2024",
        programme="BSc CS", db_path=db),
    "update_profile": lambda actor, target, db: update_profile(actor, target, programme="BSc DS", db_path=db),
    "change_role": lambda actor, target, db: change_role(actor, target, "administrator", db_path=db),
    "deactivate_account": lambda actor, target, db: deactivate_account(actor, target, db_path=db),
    "reactivate_account": lambda actor, target, db: reactivate_account(actor, target, db_path=db),
    "unlock_account": lambda actor, target, db: unlock_account(actor, target, db_path=db),
    "revoke_sessions": lambda actor, target, db: revoke_sessions(actor, target, db_path=db),
    "reset_password": lambda actor, target, db: reset_password(actor, target, strong_password(), db_path=db),
}


def _unauthorized_actors(env: Env) -> dict[str, AuthenticatedUser]:
    student = to_authenticated_user(env.user())
    inactive_admin = to_authenticated_user(env.user("administrator", active=False))
    stale = env.admin()
    revoke_sessions(env.admin(), stale.id, db_path=env.db_path)  # stale.token_version is now outdated
    forged = dataclasses.replace(student, role="administrator")
    missing = AuthenticatedUser(id="999999", role="administrator", is_active=True, token_version=0)
    return {"student": student, "inactive_admin": inactive_admin, "stale_token": stale, "forged_role": forged,
            "missing": missing}


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_operations_refuse_actors_that_are_not_active_administrators(env: Env, operation: str) -> None:
    actors = _unauthorized_actors(env)
    target = env.user(active=operation != "reactivate_account")
    update_user(target.id, failed_login_count=3, db_path=env.db_path)
    baseline_users = list_users(limit=100, db_path=env.db_path)
    baseline_events = env.events()

    for name, actor in actors.items():
        with pytest.raises(AdminActionRefusedError) as excinfo:
            OPERATIONS[operation](actor, target.id, env.db_path)
        assert excinfo.value.reason == "actor_not_authorized", name

    assert list_users(limit=100, db_path=env.db_path) == baseline_users
    assert env.events() == baseline_events


@pytest.mark.parametrize("operation", sorted(set(OPERATIONS) - {"create_student"}))
def test_operations_on_unknown_users_change_nothing(env: Env, operation: str) -> None:
    actor = env.admin()

    for missing in (999_999, "abc", None, 0):
        with pytest.raises(UserNotFoundError):
            OPERATIONS[operation](actor, missing, env.db_path)

    assert env.events() == []


# --------------------------------------------------------------------------- #
# Atomicity: the user change and its audit event are kept or discarded together
# --------------------------------------------------------------------------- #


def _users_and_events(env: Env) -> tuple[Any, Any]:
    return list_users(limit=100, db_path=env.db_path), env.events()


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
@pytest.mark.parametrize("failure", ["before_event", "after_event"])
def test_failure_rolls_back_the_change_and_the_event(env: Env, monkeypatch: pytest.MonkeyPatch, operation: str,
                                                     failure: str) -> None:
    actor = env.admin()
    env.user("administrator")  # so administrator demotion would otherwise be allowed
    target = env.user(active=operation != "reactivate_account")
    update_user(target.id, failed_login_count=3, db_path=env.db_path)
    operations = dict(OPERATIONS)
    if operation == "change_role":  # use a change that would succeed: demoting an administrator
        target = env.user("administrator")
        operations["change_role"] = lambda a, t, db: change_role(a, t, "student", db_path=db)
    before = _users_and_events(env)
    real_append = admin.append_audit_event

    def failing_append(*args: Any, **kwargs: Any) -> Any:
        if failure == "after_event":
            real_append(*args, **kwargs)  # the event is written, then something fails
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(admin, "append_audit_event", failing_append)

    with pytest.raises(RuntimeError, match="simulated failure"):
        operations[operation](actor, target.id, env.db_path)

    assert _users_and_events(env) == before


def test_rejected_audit_details_roll_back_the_user_change(env: Env) -> None:
    """A real failure path: the user update succeeds, then the audit repository refuses a credential-like value."""
    actor = env.admin()
    student = env.user()
    token_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0"

    with pytest.raises(AuditEventError):
        update_profile(actor, student.id, programme=token_like, db_path=env.db_path)

    assert env.get(student.id) == student
    assert env.events() == []


def test_missing_audit_table_rolls_back_the_user_change(tmp_path: Path) -> None:
    db_path = tmp_path / "no-audit.db"
    init_auth_tables(db_path)  # audit table deliberately not created
    administrator = create_user("a@uni.edu", strong_password(), "administrator", db_path=db_path)
    student = create_user("s@uni.edu", strong_password(), "student", admission_batch="2024", programme="BSc CS",
                          db_path=db_path)

    with pytest.raises(sqlite3.OperationalError):
        deactivate_account(to_authenticated_user(administrator), student.id, db_path=db_path)
    with pytest.raises(sqlite3.OperationalError):
        create_student(to_authenticated_user(administrator), email="n@uni.edu", password=strong_password(),
                       admission_batch="2024", programme="BSc CS", db_path=db_path)

    assert get_user_by_id(student.id, db_path=db_path) == student
    assert list_users(db_path=db_path).total == 2


# --------------------------------------------------------------------------- #
# Last active administrator, including concurrent attempts
# --------------------------------------------------------------------------- #


def _run_concurrently(*calls: Callable[[], Any]) -> list[Any]:
    """Run calls at the same moment; return each result or raised exception."""
    barrier = threading.Barrier(len(calls))
    results: list[Any] = [None] * len(calls)

    def worker(index: int, call: Callable[[], Any]) -> None:
        barrier.wait()
        try:
            results[index] = call()
        except BaseException as error:  # noqa: BLE001 - collected for assertions
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i, call)) for i, call in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a concurrent operation hung"
    return results


@pytest.mark.parametrize("round_number", range(5))
@pytest.mark.parametrize(
    "operation",
    [
        lambda actor, target, db: deactivate_account(actor, target, db_path=db),
        lambda actor, target, db: change_role(actor, target, "student", db_path=db),
    ],
    ids=["mutual-deactivation", "mutual-demotion"],
)
def test_two_administrators_cannot_remove_each_other_at_once(tmp_path: Path, round_number: int, operation: Any) -> None:
    env = Env(tmp_path / f"race-{round_number}.db")
    first, second = env.admin(), env.admin()

    results = _run_concurrently(
        lambda: operation(first, int(second.id), env.db_path),
        lambda: operation(second, int(first.id), env.db_path),
    )

    successes = [result for result in results if isinstance(result, UserRecord)]
    refusals = [result for result in results if isinstance(result, AdminActionRefusedError)]
    assert len(successes) == 1 and len(refusals) == 1, results
    assert refusals[0].reason == "actor_not_authorized"  # the loser was already removed
    assert env.active_admins() == 1
    assert [event["outcome"] for event in env.events()] == ["success"]


def test_ring_of_administrators_always_leaves_one_active(env: Env) -> None:
    admins = [env.admin() for _ in range(4)]

    results = _run_concurrently(
        *[lambda i=i: deactivate_account(admins[i], int(admins[(i + 1) % 4].id), db_path=env.db_path) for i in range(4)]
    )

    successes = [result for result in results if isinstance(result, UserRecord)]
    assert all(isinstance(r, (UserRecord, AdminActionRefusedError)) for r in results), results
    assert env.active_admins() >= 1
    assert 1 <= len(successes) <= 3
    assert len(env.events("user.deactivated")) == len(successes)


def _without_actor_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a trusted caller so the last-administrator guard is the only safeguard left.

    With the normal actor check, an acting administrator plus a distinct
    administrator target always means two active administrators, so the guard
    is defence in depth. This isolates it to prove it holds on its own.
    """
    def trusted(connection: sqlite3.Connection, actor: AuthenticatedUser) -> UserRecord:
        record = admin._fetch(connection, int(actor.id))
        assert record is not None
        return record

    monkeypatch.setattr(admin, "_authorized_actor", trusted)


@pytest.mark.parametrize(
    "operation, action",
    [
        (lambda actor, target, db: deactivate_account(actor, target, db_path=db), "user.deactivated"),
        (lambda actor, target, db: change_role(actor, target, "student", db_path=db), "user.role_changed"),
    ],
    ids=["deactivate", "demote"],
)
def test_last_active_administrator_guard(env: Env, monkeypatch: pytest.MonkeyPatch, operation: Any, action: str) -> None:
    caller = to_authenticated_user(env.user("student"))
    only_admin = env.user("administrator")
    env.user("administrator", active=False)  # inactive administrators do not count
    _without_actor_check(monkeypatch)

    with pytest.raises(AdminActionRefusedError) as excinfo:
        operation(caller, only_admin.id, env.db_path)

    assert excinfo.value.reason == "last_administrator"
    assert env.get(only_admin.id) == only_admin
    [event] = env.events(action)
    assert event["outcome"] == "denied" and event["details"]["reason"] == "last_administrator"


@pytest.mark.parametrize("round_number", range(5))
def test_last_administrator_guard_holds_under_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                          round_number: int) -> None:
    env = Env(tmp_path / f"guard-{round_number}.db")
    first, second = env.admin(), env.admin()
    _without_actor_check(monkeypatch)

    results = _run_concurrently(
        lambda: deactivate_account(first, int(second.id), db_path=env.db_path),
        lambda: deactivate_account(second, int(first.id), db_path=env.db_path),
    )

    refusals = [result for result in results if isinstance(result, AdminActionRefusedError)]
    assert sum(isinstance(result, UserRecord) for result in results) == 1, results
    assert [refusal.reason for refusal in refusals] == ["last_administrator"]
    assert env.active_admins() == 1
    assert sorted(event["outcome"] for event in env.events()) == ["denied", "success"]


def test_concurrent_session_revocations_are_all_applied(env: Env) -> None:
    actor = env.admin()
    student = env.user()

    results = _run_concurrently(*[lambda: revoke_sessions(actor, student.id, db_path=env.db_path) for _ in range(10)])

    assert all(isinstance(result, UserRecord) for result in results), results
    assert env.get(student.id).token_version == student.token_version + 10
    assert len(env.events("user.sessions_revoked")) == 10
