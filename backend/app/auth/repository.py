"""Users database repository for the CohortIQ AI backend.

The ``users`` table is additive: it lives in the same SQLite database as the
regulation tables but is created and used only by the FastAPI backend. The
existing ``regulations`` and ``document_pages`` tables and the Streamlit
application are not affected.

Security properties
- Passwords are stored only as Argon2id hashes. The database itself rejects any
  ``password_hash`` that is not an Argon2id hash, so plaintext cannot be stored
  even by mistake.
- Emails are normalized (trimmed, lower-cased) and unique case-insensitively
  (``COLLATE NOCASE`` plus normalization).
- Roles are restricted to ``student`` and ``administrator`` by a CHECK constraint.
- ``UserRecord`` hides the hash from ``repr``; :func:`serialize_user` returns
  only public fields and never the hash or internal security counters.
- Changing a password, role or email, or deactivating an account, increments
  ``token_version`` so existing access tokens stop working immediately.
- Sign-in outcomes (failure counter, temporary lock, last login) are applied by
  :func:`apply_login_attempt` in a single ``BEGIN IMMEDIATE`` transaction, so
  concurrent attempts cannot lose counter updates or slip past a lock.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.database import get_connection
from backend.app.auth.models import ROLES, AuthenticatedUser
from backend.app.auth.password_policy import validate_password_strength
from backend.app.core.security import hash_password

logger = logging.getLogger(__name__)

MAX_EMAIL_LENGTH = 254
MAX_FULL_NAME_LENGTH = 200
MAX_COHORT_VALUE_LENGTH = 100
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PUBLIC_USER_FIELDS = (
    "id",
    "email",
    "role",
    "full_name",
    "admission_batch",
    "programme",
    "is_active",
    "last_login_at",
    "created_at",
    "updated_at",
)

USERS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE
            CHECK (length(trim(email)) > 0 AND length(email) <= 254),
        password_hash TEXT NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
        role TEXT NOT NULL CHECK (role IN ('student', 'administrator')),
        full_name TEXT,
        admission_batch TEXT,
        programme TEXT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        token_version INTEGER NOT NULL DEFAULT 0 CHECK (token_version >= 0),
        failed_login_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_login_count >= 0),
        locked_until TEXT,
        last_login_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
"""

_SELECT_COLUMNS = (
    "id, email, password_hash, role, full_name, admission_batch, programme, is_active, "
    "token_version, failed_login_count, locked_until, last_login_at, created_at, updated_at"
)

_UNSET: Any = object()


class DuplicateEmailError(ValueError):
    """An account with the same (case-insensitive) email already exists."""

    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class WeakPasswordError(ValueError):
    """The password does not meet the policy. The message never contains the password."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("Password does not meet the password policy: " + " ".join(self.problems))


@dataclass(frozen=True)
class UserRecord:
    """A full users-table row. Internal use only; never return it from an API."""

    id: int
    email: str
    password_hash: str = field(repr=False)
    role: str
    full_name: Optional[str]
    admission_batch: Optional[str]
    programme: Optional[str]
    is_active: bool
    token_version: int
    failed_login_count: int
    locked_until: Optional[str]
    last_login_at: Optional[str]
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def normalize_email(email: Any) -> str:
    """Return the canonical (trimmed, lower-case) email or raise ``ValueError``."""
    if not isinstance(email, str):
        raise ValueError("Email must be text.")
    normalized = email.strip().lower()
    if not normalized or len(normalized) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(normalized):
        raise ValueError("Email address is not valid.")
    return normalized


def _validate_role(role: Any) -> str:
    if role not in ROLES:
        raise ValueError("Role must be 'student' or 'administrator'.")
    return role


def _optional_text(value: Any, name: str, max_length: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise ValueError(f"{name} must be at most {max_length} characters.")
    return cleaned


def _optional_timestamp(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware.")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{name} must be an ISO 8601 timestamp.") from None
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware.")
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    raise ValueError(f"{name} must be a datetime or ISO 8601 timestamp.")


def _parse_user_id(user_id: Any) -> Optional[int]:
    if isinstance(user_id, bool):
        return None
    if isinstance(user_id, int):
        return user_id if user_id > 0 else None
    if isinstance(user_id, str) and user_id.isascii() and user_id.isdigit():
        parsed = int(user_id)
        return parsed if parsed > 0 else None
    return None


def _validated_password_hash(password: Any, email: str) -> str:
    problems = validate_password_strength(password, email=email)
    if problems:
        raise WeakPasswordError(problems)
    return hash_password(password)


def _row_to_record(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        id=int(row["id"]),
        email=row["email"],
        password_hash=row["password_hash"],
        role=row["role"],
        full_name=row["full_name"],
        admission_batch=row["admission_batch"],
        programme=row["programme"],
        is_active=bool(row["is_active"]),
        token_version=int(row["token_version"]),
        failed_login_count=int(row["failed_login_count"]),
        locked_until=row["locked_until"],
        last_login_at=row["last_login_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _is_duplicate_email(error: sqlite3.IntegrityError) -> bool:
    return "UNIQUE constraint failed: users.email" in str(error)


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def init_auth_tables(db_path: str | Path | None = None) -> None:
    """Create the ``users`` table if it does not exist. Never alters other tables."""
    with closing(get_connection(db_path)) as connection:
        connection.execute(USERS_TABLE_SQL)
        connection.commit()


# --------------------------------------------------------------------------- #
# Queries and commands
# --------------------------------------------------------------------------- #


def create_user(
    email: str,
    password: str,
    role: str,
    *,
    full_name: Optional[str] = None,
    admission_batch: Optional[str] = None,
    programme: Optional[str] = None,
    is_active: bool = True,
    db_path: str | Path | None = None,
) -> UserRecord:
    """Create an account, storing only an Argon2id hash of ``password``.

    Raises:
        ValueError: invalid email, role or profile values.
        WeakPasswordError: the password does not meet the policy.
        DuplicateEmailError: the email is already registered (any letter case).
    """
    normalized_email = normalize_email(email)
    _validate_role(role)
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be a boolean.")
    values = (
        normalized_email,
        _validated_password_hash(password, normalized_email),
        role,
        _optional_text(full_name, "full_name", MAX_FULL_NAME_LENGTH),
        _optional_text(admission_batch, "admission_batch", MAX_COHORT_VALUE_LENGTH),
        _optional_text(programme, "programme", MAX_COHORT_VALUE_LENGTH),
        int(is_active),
    )
    now = _now_iso()

    with closing(get_connection(db_path)) as connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    email, password_hash, role, full_name, admission_batch, programme,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (*values, now, now),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if _is_duplicate_email(error):
                raise DuplicateEmailError() from None
            raise ValueError("User data violates database constraints.") from None
        user_id = int(cursor.lastrowid)

    created = get_user_by_id(user_id, db_path=db_path)
    assert created is not None
    return created


def get_user_by_id(user_id: Any, *, db_path: str | Path | None = None) -> Optional[UserRecord]:
    """Return the account with ``user_id`` (int or digit string), or None."""
    parsed = _parse_user_id(user_id)
    if parsed is None:
        return None
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(f"SELECT {_SELECT_COLUMNS} FROM users WHERE id = ?;", (parsed,)).fetchone()
    return _row_to_record(row) if row else None


def get_user_by_email(email: Any, *, db_path: str | Path | None = None) -> Optional[UserRecord]:
    """Return the account with ``email`` (case-insensitive), or None."""
    try:
        normalized = normalize_email(email)
    except ValueError:
        return None
    with closing(get_connection(db_path)) as connection:
        row = connection.execute(f"SELECT {_SELECT_COLUMNS} FROM users WHERE email = ?;", (normalized,)).fetchone()
    return _row_to_record(row) if row else None


def update_user(
    user_id: Any,
    *,
    email: Any = _UNSET,
    password: Any = _UNSET,
    role: Any = _UNSET,
    full_name: Any = _UNSET,
    admission_batch: Any = _UNSET,
    programme: Any = _UNSET,
    is_active: Any = _UNSET,
    failed_login_count: Any = _UNSET,
    locked_until: Any = _UNSET,
    last_login_at: Any = _UNSET,
    increment_token_version: bool = False,
    db_path: str | Path | None = None,
) -> Optional[UserRecord]:
    """Update selected fields of an account and return the updated record.

    Only the keyword arguments supplied are changed. Changing the email,
    password or role, or deactivating the account, also increments
    ``token_version`` so previously issued tokens are revoked.

    Returns ``None`` if the account does not exist.
    """
    existing = get_user_by_id(user_id, db_path=db_path)
    if existing is None:
        return None

    assignments: dict[str, Any] = {}
    revoke_tokens = bool(increment_token_version)

    if email is not _UNSET:
        new_email = normalize_email(email)
        if new_email != existing.email:
            assignments["email"] = new_email
            revoke_tokens = True
    if password is not _UNSET:
        assignments["password_hash"] = _validated_password_hash(password, assignments.get("email", existing.email))
        revoke_tokens = True
    if role is not _UNSET:
        _validate_role(role)
        if role != existing.role:
            assignments["role"] = role
            revoke_tokens = True
    if full_name is not _UNSET:
        assignments["full_name"] = _optional_text(full_name, "full_name", MAX_FULL_NAME_LENGTH)
    if admission_batch is not _UNSET:
        assignments["admission_batch"] = _optional_text(admission_batch, "admission_batch", MAX_COHORT_VALUE_LENGTH)
    if programme is not _UNSET:
        assignments["programme"] = _optional_text(programme, "programme", MAX_COHORT_VALUE_LENGTH)
    if is_active is not _UNSET:
        if not isinstance(is_active, bool):
            raise ValueError("is_active must be a boolean.")
        assignments["is_active"] = int(is_active)
        if existing.is_active and not is_active:
            revoke_tokens = True
    if failed_login_count is not _UNSET:
        if isinstance(failed_login_count, bool) or not isinstance(failed_login_count, int) or failed_login_count < 0:
            raise ValueError("failed_login_count must be a non-negative integer.")
        assignments["failed_login_count"] = failed_login_count
    if locked_until is not _UNSET:
        assignments["locked_until"] = _optional_timestamp(locked_until, "locked_until")
    if last_login_at is not _UNSET:
        assignments["last_login_at"] = _optional_timestamp(last_login_at, "last_login_at")

    if not assignments and not revoke_tokens:
        return existing

    set_clauses = [f"{column} = ?" for column in assignments]
    parameters = list(assignments.values())
    if revoke_tokens:
        set_clauses.append("token_version = token_version + 1")
    set_clauses.append("updated_at = ?")
    parameters.extend([_now_iso(), existing.id])

    with closing(get_connection(db_path)) as connection:
        try:
            connection.execute(f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?;", parameters)
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if _is_duplicate_email(error):
                raise DuplicateEmailError() from None
            raise ValueError("User data violates database constraints.") from None

    return get_user_by_id(existing.id, db_path=db_path)


def increment_token_version(user_id: Any, *, db_path: str | Path | None = None) -> Optional[int]:
    """Revoke all of the account's tokens; return the new version, or None if not found."""
    parsed = _parse_user_id(user_id)
    if parsed is None:
        return None
    with closing(get_connection(db_path)) as connection:
        cursor = connection.execute(
            "UPDATE users SET token_version = token_version + 1, updated_at = ? WHERE id = ?;",
            (_now_iso(), parsed),
        )
        connection.commit()
        if cursor.rowcount == 0:
            return None
        row = connection.execute("SELECT token_version FROM users WHERE id = ?;", (parsed,)).fetchone()
    return int(row["token_version"])


def deactivate_user(user_id: Any, *, db_path: str | Path | None = None) -> bool:
    """Deactivate the account and revoke its tokens. Returns False if not found."""
    parsed = _parse_user_id(user_id)
    if parsed is None:
        return False
    with closing(get_connection(db_path)) as connection:
        cursor = connection.execute(
            "UPDATE users SET is_active = 0, token_version = token_version + 1, updated_at = ? WHERE id = ?;",
            (_now_iso(), parsed),
        )
        connection.commit()
        return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Sign-in state
# --------------------------------------------------------------------------- #


def _utc_moment(now: Optional[datetime]) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    return moment.astimezone(timezone.utc)


def _parse_stored_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse a stored ISO timestamp; ``None`` for a missing or unreadable value."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def is_locked(user: UserRecord, now: Optional[datetime] = None) -> bool:
    """Return True while the account's temporary sign-in lock is in force.

    An unreadable ``locked_until`` value (which the application never writes)
    is treated as expired, so it can never cause a permanent lockout; the next
    sign-in attempt overwrites it.
    """
    locked_until = _parse_stored_timestamp(user.locked_until)
    return locked_until is not None and locked_until > _utc_moment(now)


def apply_login_attempt(
    user_id: Any,
    *,
    verified_password_hash: str,
    password_matches: bool,
    max_failed_attempts: int,
    lockout_duration: timedelta,
    now: Optional[datetime] = None,
    db_path: str | Path | None = None,
) -> Optional[UserRecord]:
    """Atomically apply the outcome of a password check to an account.

    ``verified_password_hash`` is the hash the password was checked against and
    ``password_matches`` the result. The account is re-read inside a
    ``BEGIN IMMEDIATE`` transaction (which takes SQLite's write lock before
    reading), so concurrent attempts are serialized and every failure is counted.

    Policy:
    - Inactive or currently locked account: sign-in refused; nothing changes
      (attempts during a lock neither extend it nor count towards the next one).
    - Password hash changed since it was verified: refused; nothing changes.
    - Wrong password: ``failed_login_count`` increases by one; once it reaches
      ``max_failed_attempts`` the account is locked for ``lockout_duration``.
      After a lock has expired, counting starts again from one.
    - Correct password: the failure count and lock are cleared and
      ``last_login_at`` is set.

    Returns the updated record when sign-in is permitted, otherwise ``None``.
    """
    if isinstance(max_failed_attempts, bool) or not isinstance(max_failed_attempts, int) or max_failed_attempts < 1:
        raise ValueError("max_failed_attempts must be a positive integer.")
    if not isinstance(lockout_duration, timedelta) or lockout_duration <= timedelta(0):
        raise ValueError("lockout_duration must be a positive timedelta.")
    parsed_id = _parse_user_id(user_id)
    if parsed_id is None:
        return None
    moment = _utc_moment(now)
    timestamp = moment.isoformat(timespec="microseconds")

    with closing(get_connection(db_path)) as connection:
        connection.isolation_level = None  # explicit transaction control below
        connection.execute("BEGIN IMMEDIATE;")
        try:
            select_sql = f"SELECT {_SELECT_COLUMNS} FROM users WHERE id = ?;"
            row = connection.execute(select_sql, (parsed_id,)).fetchone()
            signed_in: Optional[UserRecord] = None
            if row is not None:
                user = _row_to_record(row)
                if not user.is_active or is_locked(user, moment) or user.password_hash != verified_password_hash:
                    pass
                elif password_matches:
                    connection.execute(
                        "UPDATE users SET failed_login_count = 0, locked_until = NULL, "
                        "last_login_at = ?, updated_at = ? WHERE id = ?;",
                        (timestamp, timestamp, parsed_id),
                    )
                    # Read inside the transaction so the token version used for
                    # the new token is exactly the one this sign-in validated.
                    signed_in = _row_to_record(connection.execute(select_sql, (parsed_id,)).fetchone())
                else:
                    # A lock that has expired starts a fresh counting window.
                    previous = 0 if user.locked_until is not None else user.failed_login_count
                    failures = previous + 1
                    locked_until = None
                    if failures >= max_failed_attempts:
                        locked_until = (moment + lockout_duration).isoformat(timespec="microseconds")
                        logger.warning(
                            "Account %s temporarily locked after %d consecutive failed sign-in attempts.",
                            parsed_id,
                            failures,
                        )
                    connection.execute(
                        "UPDATE users SET failed_login_count = ?, locked_until = ?, updated_at = ? WHERE id = ?;",
                        (failures, locked_until, timestamp, parsed_id),
                    )
            connection.execute("COMMIT;")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK;")
            raise

    return signed_in


# --------------------------------------------------------------------------- #
# Safe views
# --------------------------------------------------------------------------- #


def serialize_user(user: UserRecord) -> dict[str, Any]:
    """Public representation of an account: never includes the password hash,
    token version, failed-login count or lock state."""
    return {name: getattr(user, name) for name in PUBLIC_USER_FIELDS}


def to_authenticated_user(user: UserRecord) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(user.id),
        role=user.role,
        is_active=user.is_active,
        token_version=user.token_version,
        email=user.email,
        admission_batch=user.admission_batch,
        programme=user.programme,
    )


class SQLiteUserStore:
    """``UserStore`` implementation backed by the users table."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path

    def get_user_by_id(self, user_id: str) -> Optional[AuthenticatedUser]:
        record = get_user_by_id(user_id, db_path=self.db_path)
        return to_authenticated_user(record) if record else None
