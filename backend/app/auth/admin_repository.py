"""Administrator user management for the CohortIQ AI backend (Part 4, Stage 5).

Repository operations behind the planned administrator API. They reuse the
users repository (validation, password policy, Argon2id hashing and
token-version revocation) and the audit repository; neither is duplicated.

Every change
    - runs in one ``BEGIN IMMEDIATE`` transaction, so SQLite's write lock is
      held before anything is read and concurrent administrative changes are
      serialized;
    - re-reads the acting administrator inside that transaction and refuses to
      act unless the account still exists, is active, is an administrator and
      still has the token version it authenticated with;
    - writes its audit event on the same connection, so the user change and its
      event are committed together or not at all.

Policy refusals (an administrator changing their own role or active status,
removing the last active administrator, promoting anyone to administrator,
resetting an administrator's password) commit a ``denied`` audit event and
nothing else, then raise :class:`AdminActionRefusedError`.

Not audited here: invalid input (the change is rejected before anything is
written), unknown target users, and an acting account that is no longer an
active administrator (authorization refusals are recorded by the API layer).

Decisions applied: administrators cannot be created or promoted here (only the
first-administrator CLI creates administrators); new accounts are students
with a cohort and an initial password set by the administrator under the
existing password policy; there is no hard delete.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from app.database import get_connection
from backend.app.audit.repository import append_audit_event
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT, ROLES, AuthenticatedUser
from backend.app.auth.repository import (
    _SELECT_COLUMNS,
    _UNSET,
    MAX_COHORT_VALUE_LENGTH,
    MAX_FULL_NAME_LENGTH,
    UserRecord,
    _insert_user,
    _integrity_error,
    _new_user_values,
    _optional_text,
    _parse_user_id,
    _row_to_record,
    _user_update_statement,
    get_user_by_id,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_OFFSET = 1_000_000

_REFUSAL_MESSAGES = {
    "actor_not_authorized": "The acting account is not an active administrator.",
    "self_change": "Administrators cannot change their own role, active status or password here.",
    "last_administrator": "The last active administrator cannot be deactivated or demoted.",
    "role_not_assignable": "The administrator role cannot be granted through user management.",
    "administrator_account": "Administrator passwords cannot be reset through user management.",
}


class UserNotFoundError(LookupError):
    """The target account does not exist."""

    def __init__(self) -> None:
        super().__init__("User not found.")


class ConcurrentModificationError(ValueError):
    """The account changed while the operation was being prepared; retrying is safe."""

    def __init__(self) -> None:
        super().__init__("The account changed during the operation; please retry.")


class AdminActionRefusedError(Exception):
    """A user-management change was refused by policy. ``reason`` is a stable code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(_REFUSAL_MESSAGES[reason])


@dataclass(frozen=True)
class UserPage:
    users: tuple[UserRecord, ...]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
    return value


def _cohort_filter(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    cleaned = _optional_text(value, name, MAX_COHORT_VALUE_LENGTH)
    if cleaned is None:
        raise ValueError(f"{name} filter must not be blank.")
    return cleaned


def list_users(
    *,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    admission_batch: Optional[str] = None,
    programme: Optional[str] = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> UserPage:
    """Return one page of accounts, ordered by id, with the total number of matches.

    Filters are exact (cohort values are matched exactly, as regulation
    applicability is). ``limit`` is 1-100 and ``offset`` 0-1,000,000.
    Records include the password hash for internal use only; serialize them
    with :func:`backend.app.auth.repository.serialize_user`.
    """
    clauses: list[str] = []
    parameters: list[Any] = []
    if role is not None:
        if role not in ROLES:
            raise ValueError("role filter must be 'student' or 'administrator'.")
        clauses.append("role = ?")
        parameters.append(role)
    if is_active is not None:
        if not isinstance(is_active, bool):
            raise ValueError("is_active filter must be a boolean.")
        clauses.append("is_active = ?")
        parameters.append(int(is_active))
    for column, value in (("admission_batch", admission_batch), ("programme", programme)):
        cleaned = _cohort_filter(value, column)
        if cleaned is not None:
            clauses.append(f"{column} = ?")
            parameters.append(cleaned)
    page_size = _bounded_int(limit, "limit", 1, MAX_PAGE_SIZE)
    start = _bounded_int(offset, "offset", 0, MAX_OFFSET)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    with closing(get_connection(db_path)) as connection:
        connection.isolation_level = None
        connection.execute("BEGIN;")  # one read snapshot for the count and the page
        try:
            total = int(connection.execute(f"SELECT COUNT(*) FROM users{where};", parameters).fetchone()[0])
            rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM users{where} ORDER BY id ASC LIMIT ? OFFSET ?;",
                (*parameters, page_size, start),
            ).fetchall()
        finally:
            connection.execute("COMMIT;")
    return UserPage(tuple(_row_to_record(row) for row in rows), total, page_size, start)


# --------------------------------------------------------------------------- #
# Transaction helpers
# --------------------------------------------------------------------------- #


@contextmanager
def _write_transaction(db_path: str | Path | None) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` ... ``COMMIT``; any exception rolls everything back."""
    with closing(get_connection(db_path)) as connection:
        connection.isolation_level = None  # explicit transaction control
        connection.execute("BEGIN IMMEDIATE;")
        try:
            yield connection
            connection.execute("COMMIT;")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK;")
            raise


def _fetch(connection: sqlite3.Connection, user_id: int) -> Optional[UserRecord]:
    row = connection.execute(f"SELECT {_SELECT_COLUMNS} FROM users WHERE id = ?;", (user_id,)).fetchone()
    return _row_to_record(row) if row else None


def _authorized_actor(connection: sqlite3.Connection, actor: AuthenticatedUser) -> UserRecord:
    actor_id = _parse_user_id(getattr(actor, "id", None))
    record = _fetch(connection, actor_id) if actor_id is not None else None
    if (
        record is None
        or not record.is_active
        or record.role != ROLE_ADMINISTRATOR
        or record.token_version != getattr(actor, "token_version", None)
    ):
        raise AdminActionRefusedError("actor_not_authorized")
    return record


def _target(connection: sqlite3.Connection, user_id: Any) -> UserRecord:
    parsed = _parse_user_id(user_id)
    record = _fetch(connection, parsed) if parsed is not None else None
    if record is None:
        raise UserNotFoundError()
    return record


def _active_administrators(connection: sqlite3.Connection) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM users WHERE role = ? AND is_active = 1;", (ROLE_ADMINISTRATOR,)
        ).fetchone()[0]
    )


def _apply(connection: sqlite3.Connection, target: UserRecord, **changes: Any) -> UserRecord:
    """Apply changes through the users repository's update rules; return the new record."""
    statement = _user_update_statement(target, **changes)
    if statement is not None:
        try:
            connection.execute(*statement)
        except sqlite3.IntegrityError as error:
            raise _integrity_error(error) from None
    updated = _fetch(connection, target.id)
    assert updated is not None
    return updated


def _audit(
    connection: sqlite3.Connection,
    action: str,
    outcome: str,
    actor: UserRecord,
    target: UserRecord,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    append_audit_event(
        action,
        outcome=outcome,
        actor_type="user",
        actor_user_id=actor.id,
        actor_role=actor.role,
        target_type="user",
        target_id=target.id,
        details=details,
        connection=connection,
    )


def _deny(
    connection: sqlite3.Connection,
    action: str,
    actor: UserRecord,
    target: UserRecord,
    reason: str,
    details: Optional[Mapping[str, Any]] = None,
) -> AdminActionRefusedError:
    """Record a denied event (committed with the transaction) and build the error to raise."""
    _audit(connection, action, "denied", actor, target, {**(details or {}), "reason": reason})
    return AdminActionRefusedError(reason)


def _would_remove_last_administrator(connection: sqlite3.Connection, target: UserRecord) -> bool:
    """Checked under the write lock, so concurrent attempts cannot both pass."""
    return target.role == ROLE_ADMINISTRATOR and target.is_active and _active_administrators(connection) <= 1


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


def create_student(
    actor: AuthenticatedUser,
    *,
    email: str,
    password: str,
    admission_batch: str,
    programme: str,
    full_name: Optional[str] = None,
    db_path: str | Path | None = None,
) -> UserRecord:
    """Create an active student account with a cohort and an administrator-set password.

    The role is always ``student``; there is deliberately no role parameter.

    Raises:
        ValueError, WeakPasswordError, DuplicateEmailError: invalid input.
        AdminActionRefusedError: the actor is not an active administrator.
    """
    for name, value in (("admission_batch", admission_batch), ("programme", programme)):
        if _optional_text(value, name, MAX_COHORT_VALUE_LENGTH) is None:
            raise ValueError("Students must have an admission batch and programme.")
    # Validated and hashed before taking the write lock (Argon2id is deliberately slow).
    values = _new_user_values(
        email,
        password,
        ROLE_STUDENT,
        full_name=full_name,
        admission_batch=admission_batch,
        programme=programme,
        is_active=True,
    )
    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        try:
            user_id = _insert_user(connection, values)
        except sqlite3.IntegrityError as error:
            raise _integrity_error(error) from None
        created = _fetch(connection, user_id)
        assert created is not None
        _audit(
            connection,
            "user.created",
            "success",
            administrator,
            created,
            {"role": created.role, "admission_batch": created.admission_batch, "programme": created.programme},
        )
    return created


def update_profile(
    actor: AuthenticatedUser,
    user_id: Any,
    *,
    full_name: Any = _UNSET,
    admission_batch: Any = _UNSET,
    programme: Any = _UNSET,
    db_path: str | Path | None = None,
) -> UserRecord:
    """Change an account's full name and/or cohort.

    A student must keep both an admission batch and a programme. The audit
    event lists the changed field names and old/new cohort values; the full
    name itself is never recorded. Unchanged values write nothing.
    """
    requested: dict[str, Optional[str]] = {}
    if full_name is not _UNSET:
        requested["full_name"] = _optional_text(full_name, "full_name", MAX_FULL_NAME_LENGTH)
    if admission_batch is not _UNSET:
        requested["admission_batch"] = _optional_text(admission_batch, "admission_batch", MAX_COHORT_VALUE_LENGTH)
    if programme is not _UNSET:
        requested["programme"] = _optional_text(programme, "programme", MAX_COHORT_VALUE_LENGTH)

    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        target = _target(connection, user_id)
        changes = {name: value for name, value in requested.items() if getattr(target, name) != value}
        if not changes:
            return target
        if target.role == ROLE_STUDENT and (
            changes.get("admission_batch", target.admission_batch) is None
            or changes.get("programme", target.programme) is None
        ):
            raise ValueError("Students must have an admission batch and programme.")
        updated = _apply(connection, target, **changes)
        details: dict[str, Any] = {"changed_fields": sorted(changes)}
        for name in ("admission_batch", "programme"):
            if name in changes:
                details[f"old_{name}"] = getattr(target, name)
                details[f"new_{name}"] = getattr(updated, name)
        _audit(connection, "user.updated", "success", administrator, target, details)
    return updated


def change_role(actor: AuthenticatedUser, user_id: Any, role: str, *, db_path: str | Path | None = None) -> UserRecord:
    """Demote an administrator to student. Promotion to administrator is always refused.

    Refused (and audited as denied): changing one's own role, granting the
    administrator role, and demoting the last active administrator. A role
    change revokes the account's existing tokens.
    """
    if role not in ROLES:
        raise ValueError("Role must be 'student' or 'administrator'.")
    refusal: Optional[AdminActionRefusedError] = None
    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        target = _target(connection, user_id)
        details = {"old_role": target.role, "new_role": role}
        if target.id == administrator.id:
            refusal = _deny(connection, "user.role_changed", administrator, target, "self_change", details)
        elif role == ROLE_ADMINISTRATOR and target.role != ROLE_ADMINISTRATOR:
            refusal = _deny(connection, "user.role_changed", administrator, target, "role_not_assignable", details)
        elif role == target.role:
            return target
        elif _would_remove_last_administrator(connection, target):
            refusal = _deny(connection, "user.role_changed", administrator, target, "last_administrator", details)
        else:
            updated = _apply(connection, target, role=role)
            _audit(connection, "user.role_changed", "success", administrator, target, details)
    if refusal is not None:
        raise refusal
    return updated


def deactivate_account(actor: AuthenticatedUser, user_id: Any, *, db_path: str | Path | None = None) -> UserRecord:
    """Deactivate an account and revoke its tokens.

    Refused (and audited as denied): deactivating oneself, and deactivating
    the last active administrator. Already-inactive accounts are unchanged.
    """
    refusal: Optional[AdminActionRefusedError] = None
    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        target = _target(connection, user_id)
        if target.id == administrator.id:
            refusal = _deny(connection, "user.deactivated", administrator, target, "self_change")
        elif not target.is_active:
            return target
        elif _would_remove_last_administrator(connection, target):
            refusal = _deny(connection, "user.deactivated", administrator, target, "last_administrator")
        else:
            updated = _apply(connection, target, is_active=False)
            _audit(connection, "user.deactivated", "success", administrator, target)
    if refusal is not None:
        raise refusal
    return updated


def reactivate_account(actor: AuthenticatedUser, user_id: Any, *, db_path: str | Path | None = None) -> UserRecord:
    """Reactivate an inactive account. Tokens revoked at deactivation stay revoked."""
    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        target = _target(connection, user_id)
        if target.is_active:
            return target
        updated = _apply(connection, target, is_active=True)
        _audit(connection, "user.reactivated", "success", administrator, target)
    return updated


def unlock_account(actor: AuthenticatedUser, user_id: Any, *, db_path: str | Path | None = None) -> UserRecord:
    """Clear the failed sign-in counter and any temporary lock."""
    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        target = _target(connection, user_id)
        if target.failed_login_count == 0 and target.locked_until is None:
            return target
        updated = _apply(connection, target, failed_login_count=0, locked_until=None)
        _audit(connection, "user.unlocked", "success", administrator, target, {"failed_login_count": target.failed_login_count})
    return updated


def revoke_sessions(actor: AuthenticatedUser, user_id: Any, *, db_path: str | Path | None = None) -> UserRecord:
    """Invalidate every access token issued to the account (increments its token version)."""
    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        target = _target(connection, user_id)
        updated = _apply(connection, target, increment_token_version=True)
        _audit(connection, "user.sessions_revoked", "success", administrator, target)
    return updated


def reset_password(
    actor: AuthenticatedUser, user_id: Any, new_password: str, *, db_path: str | Path | None = None
) -> UserRecord:
    """Set a student's password (existing policy, Argon2id) and revoke their tokens.

    Refused (and audited as denied): resetting one's own password (self-service
    password change is deferred) and resetting an administrator's password.
    """
    preview = get_user_by_id(user_id, db_path=db_path)
    statement: Optional[tuple[str, list[Any]]] = None
    actor_id = _parse_user_id(getattr(actor, "id", None))
    if preview is not None and preview.role == ROLE_STUDENT and preview.id != actor_id:
        # Policy check and Argon2id hashing happen before taking the write lock.
        statement = _user_update_statement(preview, password=new_password)

    refusal: Optional[AdminActionRefusedError] = None
    with _write_transaction(db_path) as connection:
        administrator = _authorized_actor(connection, actor)
        target = _target(connection, user_id)
        if target.id == administrator.id:
            refusal = _deny(connection, "user.password_reset", administrator, target, "self_change")
        elif target.role == ROLE_ADMINISTRATOR:
            refusal = _deny(connection, "user.password_reset", administrator, target, "administrator_account")
        elif statement is None or preview is None or target.email != preview.email or target.role != preview.role:
            # The account changed between validation and the transaction.
            raise ConcurrentModificationError()
        else:
            connection.execute(*statement)
            updated = _fetch(connection, target.id)
            assert updated is not None
            _audit(connection, "user.password_reset", "success", administrator, target)
    if refusal is not None:
        raise refusal
    return updated
