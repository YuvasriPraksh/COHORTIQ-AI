"""Append-only audit event repository for the CohortIQ AI backend (Part 4, Stage 5).

The ``audit_events`` table is additive: it lives in the same SQLite database as
the regulation and users tables but is created and used only by the FastAPI
backend. Existing tables are never altered.

Append-only
    The repository offers no update or delete operation, and SQLite triggers
    abort any ``UPDATE`` or ``DELETE`` on the table, and any insert that would
    replace an existing row, whatever the caller. (As
    with any SQLite file, someone with direct write access to the database file
    can still alter it; the triggers protect against application mistakes, not
    against file access.)

Only approved content
    Each action has a specification fixing its allowed outcomes, its target type
    and the detail keys it may carry, and every detail key has a typed
    validator. There is no column or detail key for email addresses, passwords,
    hashes, tokens, secrets, question text or document content, and string
    values that look like a password hash or a JWT are refused as a further
    safeguard. Unknown actions or keys are rejected, never silently stored.
    Error messages name the offending key but never echo its value, so a secret
    passed by mistake does not end up in logs.

Reading
    :func:`list_audit_events` returns bounded, filtered pages, newest first.
    It opens its connection in SQLite's ``query_only`` mode, so a read can
    never change the table.

Atomicity
    :func:`append_audit_event` accepts an open connection so a later caller can
    record an event in the same transaction as the change it describes; with a
    connection it neither commits nor rolls back.

Events are retained indefinitely; there is no automatic retention or deletion.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from app.database import get_connection
from backend.app.auth.models import ROLES

MAX_DETAILS_BYTES = 2048
MAX_IDENTIFIER_LENGTH = 100

# Listing bounds; the same values as the user listing (a test keeps them aligned).
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
MAX_OFFSET = 1_000_000

OUTCOMES = ("success", "failure", "denied")
ACTOR_TYPES = ("user", "anonymous", "cli", "system")
TARGET_TYPES = ("user", "regulation")

AUDIT_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at TEXT NOT NULL CHECK (length(occurred_at) > 0),
        action TEXT NOT NULL CHECK (length(action) BETWEEN 1 AND 64),
        outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'denied')),
        actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'anonymous', 'cli', 'system')),
        actor_user_id INTEGER CHECK (actor_user_id IS NULL OR actor_user_id > 0),
        actor_role TEXT CHECK (actor_role IS NULL OR actor_role IN ('student', 'staff', 'administrator')),
        target_type TEXT CHECK (target_type IS NULL OR target_type IN ('user', 'regulation')),
        target_id INTEGER CHECK (target_id IS NULL OR target_id > 0),
        details TEXT NOT NULL DEFAULT '{}'
            CHECK (json_valid(details) AND json_type(details) = 'object' AND length(details) <= 2048),
        CHECK ((actor_type = 'user') = (actor_user_id IS NOT NULL AND actor_role IS NOT NULL)),
        CHECK (actor_type = 'user' OR (actor_user_id IS NULL AND actor_role IS NULL)),
        CHECK ((target_type IS NULL) = (target_id IS NULL))
    );
"""

AUDIT_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_audit_events_occurred_at ON audit_events (occurred_at);",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events (actor_user_id, occurred_at);",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_target ON audit_events (target_type, target_id, occurred_at);",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events (action, occurred_at);",
)

AUDIT_TRIGGER_SQL = (
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only');
    END;
    """,
    # INSERT OR REPLACE deletes a conflicting row without firing DELETE triggers
    # (unless recursive_triggers is on), so reusing an existing id is refused.
    """
    CREATE TRIGGER IF NOT EXISTS audit_events_no_replace
    BEFORE INSERT ON audit_events
    WHEN NEW.id IS NOT NULL AND EXISTS (SELECT 1 FROM audit_events WHERE id = NEW.id)
    BEGIN
        SELECT RAISE(ABORT, 'audit_events is append-only');
    END;
    """,
)

_SELECT_COLUMNS = (
    "id, occurred_at, action, outcome, actor_type, actor_user_id, actor_role, target_type, target_id, details"
)


class AuditEventError(ValueError):
    """An audit event was rejected. The message never contains submitted values."""


# --------------------------------------------------------------------------- #
# Approved actions and detail keys
# --------------------------------------------------------------------------- #

USER_FIELDS = ("email", "full_name", "admission_batch", "programme", "role", "is_active")
"""User fields whose *names* may be listed in ``changed_fields`` (never their values)."""

REASONS = (
    # auth.login_failed
    "invalid_password",
    "account_locked",
    "account_inactive",
    # authorization.denied
    "insufficient_role",
    "cohort_mismatch",
    # regulation.ingested failures
    "invalid_metadata",
    "invalid_pdf",
    "internal_error",
    # Refused administrative user changes
    "self_change",
    "last_administrator",
    "role_not_assignable",
    "administrator_account",
)

HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# query.answered: how a question was handled. The question itself is never stored.
QUESTION_ROUTES = ("out_of_scope", "clarify", "clause_lookup", "low_evidence", "general")
ANSWER_STATUSES = ("answered", "insufficient_evidence", "conflicting_evidence")

_ROUTE_TEMPLATE = re.compile(r"^/[A-Za-z0-9_./{}-]{0,199}$")
_STATUS_VALUE = re.compile(r"^[A-Za-z_ -]{1,32}$")
# A JWT starts with a base64url JSON header ("eyJ...") followed by ".payload";
# matching that prefix also catches truncated tokens.
_JWT_SHAPE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")
_HASH_MARKERS = ("$argon2", "$2a$", "$2b$", "$2y$", "pbkdf2")


def _looks_secret(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _HASH_MARKERS) or bool(_JWT_SHAPE.search(value))


def _choice(allowed: tuple[str, ...]) -> Callable[[str, Any], Any]:
    def validate(key: str, value: Any) -> Any:
        if not isinstance(value, str) or value not in allowed:
            raise AuditEventError(f"Detail {key!r} must be one of the approved values.")
        return value

    return validate


def _identifier(key: str, value: Any) -> Any:
    """A cohort value (admission batch or programme), or None."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_IDENTIFIER_LENGTH:
        raise AuditEventError(f"Detail {key!r} must be a short identifier or null.")
    if _looks_secret(value):
        raise AuditEventError(f"Detail {key!r} looks like a credential and was refused.")
    return value.strip()


def _status(key: str, value: Any) -> Any:
    """A verification status (including legacy values), or None."""
    if value is None:
        return None
    if not isinstance(value, str) or not _STATUS_VALUE.match(value):
        raise AuditEventError(f"Detail {key!r} must be a short status word or null.")
    return value


def _boolean(key: str, value: Any) -> Any:
    if not isinstance(value, bool):
        raise AuditEventError(f"Detail {key!r} must be a boolean.")
    return value


def _count(key: str, value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
        raise AuditEventError(f"Detail {key!r} must be a non-negative integer.")
    return value


def _timestamp(key: str, value: Any) -> Any:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise AuditEventError(f"Detail {key!r} must be an ISO 8601 timestamp.") from None
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AuditEventError(f"Detail {key!r} must be a timezone-aware timestamp.")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _field_names(key: str, value: Any) -> Any:
    if (
        not isinstance(value, (list, tuple))
        or not value
        or len(set(value)) != len(value)
        or not all(isinstance(name, str) and name in USER_FIELDS for name in value)
    ):
        raise AuditEventError(f"Detail {key!r} must list distinct approved user field names.")
    return sorted(value)


def _route_template(key: str, value: Any) -> Any:
    """A route template such as ``/api/v1/regulations/{regulation_id}``, not a concrete URL."""
    if not isinstance(value, str) or not _ROUTE_TEMPLATE.match(value):
        raise AuditEventError(f"Detail {key!r} must be a route template without query string.")
    return value


_DETAIL_VALIDATORS: Mapping[str, Callable[[str, Any], Any]] = MappingProxyType(
    {
        "changed_fields": _field_names,
        "role": _choice(ROLES),
        "old_role": _choice(ROLES),
        "new_role": _choice(ROLES),
        "admission_batch": _identifier,
        "programme": _identifier,
        "old_admission_batch": _identifier,
        "new_admission_batch": _identifier,
        "old_programme": _identifier,
        "new_programme": _identifier,
        "old_is_active": _boolean,
        "new_is_active": _boolean,
        "failed_login_count": _count,
        "locked_until": _timestamp,
        "old_status": _status,
        "new_status": _status,
        "reason": _choice(REASONS),
        "method": _choice(HTTP_METHODS),
        "path": _route_template,
        "route": _choice(QUESTION_ROUTES),
        "answer_status": _choice(ANSWER_STATUSES),
    }
)


@dataclass(frozen=True)
class ActionSpec:
    outcomes: frozenset[str]
    target_type: Optional[str]
    target_required: bool
    detail_keys: frozenset[str]


def _spec(outcomes: tuple[str, ...], target_type: Optional[str], *keys: str, target_required: bool = True) -> ActionSpec:
    return ActionSpec(frozenset(outcomes), target_type, target_required and target_type is not None, frozenset(keys))


_USER_CHANGE = ("changed_fields", "old_admission_batch", "new_admission_batch", "old_programme", "new_programme",
                "old_is_active", "new_is_active")

ACTIONS: Mapping[str, ActionSpec] = MappingProxyType(
    {
        # User management (administrator API or the first-administrator CLI)
        "user.created": _spec(("success",), "user", "role", "admission_batch", "programme"),
        "user.updated": _spec(("success", "failure", "denied"), "user", *_USER_CHANGE, "reason"),
        "user.role_changed": _spec(("success", "denied"), "user", "old_role", "new_role", "reason"),
        "user.deactivated": _spec(("success", "denied"), "user", "reason"),
        "user.reactivated": _spec(("success",), "user"),
        "user.unlocked": _spec(("success",), "user", "failed_login_count"),
        "user.sessions_revoked": _spec(("success",), "user"),
        "user.password_reset": _spec(("success", "denied"), "user", "reason"),
        # Authentication (known accounts only: the target is always a user id)
        "auth.login_succeeded": _spec(("success",), "user"),
        "auth.login_failed": _spec(("failure",), "user", "reason", "failed_login_count"),
        "auth.account_locked": _spec(("success",), "user", "failed_login_count", "locked_until"),
        # Regulations
        "regulation.ingested": _spec(("success", "failure"), "regulation", "reason", target_required=False),
        "regulation.verification_changed": _spec(("success",), "regulation", "old_status", "new_status"),
        "regulation.change_reviewed": _spec(("success",), "regulation", "old_status", "new_status"),
        # Student and administrator questions: outcome of the request only, never its text
        "query.answered": _spec(("success",), None, "route", "answer_status", "admission_batch", "programme"),
        # Authorization refusals (403); anonymous 401s are never audited
        "authorization.denied": _spec(("denied",), None, "method", "path", "reason"),
    }
)
"""Every approved action. Adding an action or detail key is a deliberate code change."""

_DENIED_TARGET_TYPES = ("user", "regulation")


# --------------------------------------------------------------------------- #
# Record
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AuditEvent:
    id: int
    occurred_at: str
    action: str
    outcome: str
    actor_type: str
    actor_user_id: Optional[int]
    actor_role: Optional[str]
    target_type: Optional[str]
    target_id: Optional[int]
    details: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


def _row_to_event(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        id=int(row["id"]),
        occurred_at=row["occurred_at"],
        action=row["action"],
        outcome=row["outcome"],
        actor_type=row["actor_type"],
        actor_user_id=row["actor_user_id"],
        actor_role=row["actor_role"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        details=MappingProxyType(json.loads(row["details"])),
    )


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def init_audit_tables(db_path: str | Path | None = None) -> None:
    """Create the ``audit_events`` table, its indexes and append-only triggers.

    Existing events are preserved when the role constraint is expanded to
    include staff. The migration is atomic and keeps the append-only triggers.
    """
    with closing(get_connection(db_path)) as connection:
        existing = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'audit_events';"
        ).fetchone()
        if existing and "'staff'" not in (existing["sql"] or ""):
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE;")
            try:
                connection.execute("ALTER TABLE audit_events RENAME TO audit_events_before_staff;")
                connection.execute(AUDIT_TABLE_SQL)
                columns = (
                    "id, occurred_at, action, outcome, actor_type, actor_user_id, actor_role, "
                    "target_type, target_id, details"
                )
                connection.execute(
                    f"INSERT INTO audit_events ({columns}) "
                    f"SELECT {columns} FROM audit_events_before_staff;"
                )
                connection.execute("DROP TABLE audit_events_before_staff;")
                connection.execute("COMMIT;")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK;")
                raise
        connection.execute(AUDIT_TABLE_SQL)
        for statement in (*AUDIT_INDEX_SQL, *AUDIT_TRIGGER_SQL):
            connection.execute(statement)
        connection.commit()


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _positive_id(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AuditEventError(f"{name} must be a positive integer.")
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or value <= 0:
        raise AuditEventError(f"{name} must be a positive integer.")
    return value


def _occurred_at(value: Optional[datetime]) -> str:
    moment = value or datetime.now(timezone.utc)
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise AuditEventError("occurred_at must be a timezone-aware datetime.")
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _validated_details(action: str, spec: ActionSpec, details: Optional[Mapping[str, Any]]) -> str:
    if details is None:
        details = {}
    if not isinstance(details, Mapping):
        raise AuditEventError("details must be a mapping.")
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        if not isinstance(key, str) or key not in spec.detail_keys:
            # The key may itself be sensitive (e.g. "password"), but naming it
            # helps fix the caller and does not reveal the value.
            raise AuditEventError(f"Detail {str(key)[:40]!r} is not approved for action {action!r}.")
        cleaned[key] = _DETAIL_VALIDATORS[key](key, value)
    encoded = json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(encoded) > MAX_DETAILS_BYTES:
        raise AuditEventError(f"details exceed {MAX_DETAILS_BYTES} bytes.")
    return encoded


def _validated_row(
    action: Any,
    outcome: Any,
    actor_type: Any,
    actor_user_id: Any,
    actor_role: Any,
    target_type: Any,
    target_id: Any,
    details: Optional[Mapping[str, Any]],
    occurred_at: Optional[datetime],
) -> tuple[Any, ...]:
    if not isinstance(action, str) or action not in ACTIONS:
        raise AuditEventError("action is not an approved audit action.")
    spec = ACTIONS[action]
    if outcome not in spec.outcomes:
        raise AuditEventError(f"outcome is not allowed for action {action!r}.")

    if actor_type not in ACTOR_TYPES:
        raise AuditEventError("actor_type is not an approved actor type.")
    actor_id = _positive_id(actor_user_id, "actor_user_id")
    if actor_type == "user":
        if actor_id is None or actor_role not in ROLES:
            raise AuditEventError("A user actor needs actor_user_id and a valid actor_role.")
    elif actor_id is not None or actor_role is not None:
        raise AuditEventError("Only a user actor may carry actor_user_id or actor_role.")

    resolved_target_id = _positive_id(target_id, "target_id")
    if spec.target_type is None:
        # authorization.denied: the target is optional and may be a user or a regulation.
        allowed_types: tuple[Optional[str], ...] = (None, *_DENIED_TARGET_TYPES)
    else:
        allowed_types = (spec.target_type,) if spec.target_required else (None, spec.target_type)
    if target_type not in allowed_types:
        raise AuditEventError(f"target_type is not allowed for action {action!r}.")
    if (target_type is None) != (resolved_target_id is None):
        raise AuditEventError("target_type and target_id must be given together.")

    return (
        _occurred_at(occurred_at),
        action,
        outcome,
        actor_type,
        actor_id,
        actor_role,
        target_type,
        resolved_target_id,
        _validated_details(action, spec, details),
    )


# --------------------------------------------------------------------------- #
# Append
# --------------------------------------------------------------------------- #


def append_audit_event(
    action: str,
    *,
    outcome: str,
    actor_type: str,
    actor_user_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    details: Optional[Mapping[str, Any]] = None,
    occurred_at: Optional[datetime] = None,
    db_path: str | Path | None = None,
    connection: Optional[sqlite3.Connection] = None,
) -> AuditEvent:
    """Validate and append one audit event; return the stored event.

    With ``connection``, the event is written inside the caller's transaction
    and is neither committed nor rolled back here, so it is kept or discarded
    together with the change it describes. Without it, a new connection is
    opened and the event is committed immediately.

    Raises:
        AuditEventError: the event uses an unapproved action, outcome, actor,
            target or detail, or a detail value fails validation.
    """
    values = _validated_row(
        action, outcome, actor_type, actor_user_id, actor_role, target_type, target_id, details, occurred_at
    )
    insert_sql = (
        "INSERT INTO audit_events (occurred_at, action, outcome, actor_type, actor_user_id, actor_role, "
        "target_type, target_id, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);"
    )
    select_sql = f"SELECT {_SELECT_COLUMNS} FROM audit_events WHERE id = ?;"

    if connection is not None:
        cursor = connection.cursor()
        cursor.row_factory = sqlite3.Row  # independent of the caller's row factory
        cursor.execute(insert_sql, values)
        event_id = cursor.lastrowid
        return _row_to_event(cursor.execute(select_sql, (event_id,)).fetchone())

    with closing(get_connection(db_path)) as own_connection:
        try:
            cursor = own_connection.execute(insert_sql, values)
            row = own_connection.execute(select_sql, (cursor.lastrowid,)).fetchone()
            own_connection.commit()
        except BaseException:
            own_connection.rollback()
            raise
    return _row_to_event(row)


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AuditEventPage:
    events: tuple[AuditEvent, ...]
    total: int
    limit: int
    offset: int


# Stored timestamps are UTC ISO 8601 text with microseconds, so they sort
# chronologically as text. A bound outside datetime's range once converted to
# UTC (before year 1 or after year 9999) becomes text that sorts before or after
# every stored value.
_BEFORE_ALL_TIMESTAMPS = "0000"
_AFTER_ALL_TIMESTAMPS = "9999-13"


def _bounded_int(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer from {low} to {high}.")
    return value


def _timestamp_bound(value: Any, name: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime.")
    try:
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except OverflowError:
        return _BEFORE_ALL_TIMESTAMPS if value.year == 1 else _AFTER_ALL_TIMESTAMPS


def list_audit_events(
    *,
    action: Optional[str] = None,
    outcome: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    occurred_after: Optional[datetime] = None,
    occurred_before: Optional[datetime] = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> AuditEventPage:
    """Return one page of audit events, newest first, with the total number of matches.

    Filters are exact, except the time bounds, which are inclusive:
    ``occurred_after <= occurred_at <= occurred_before``. Events are ordered by
    ``occurred_at`` descending, with ties broken by ``id`` descending, so pages
    are deterministic. ``limit`` is 1-100 and ``offset`` 0-1,000,000.

    Events are returned as stored, including every detail key; callers that
    show events to people must filter the details (see
    ``backend.app.schemas.admin.public_audit_details``).

    Raises:
        ValueError: a filter or bound is invalid. Messages never echo values.
    """
    clauses: list[str] = []
    parameters: list[Any] = []
    if action is not None:
        if not isinstance(action, str) or action not in ACTIONS:
            raise ValueError("action filter is not an approved audit action.")
        clauses.append("action = ?")
        parameters.append(action)
    if outcome is not None:
        if outcome not in OUTCOMES:
            raise ValueError("outcome filter is not an approved outcome.")
        clauses.append("outcome = ?")
        parameters.append(outcome)
    if actor_user_id is not None:
        clauses.append("actor_user_id = ?")
        parameters.append(_bounded_int(actor_user_id, "actor_user_id", 1, 2**63 - 1))
    if target_type is not None:
        if target_type not in TARGET_TYPES:
            raise ValueError("target_type filter is not an approved target type.")
        clauses.append("target_type = ?")
        parameters.append(target_type)
    if target_id is not None:
        if target_type is None:
            raise ValueError("target_id filter requires target_type.")
        clauses.append("target_id = ?")
        parameters.append(_bounded_int(target_id, "target_id", 1, 2**63 - 1))
    if occurred_after is not None:
        clauses.append("occurred_at >= ?")
        parameters.append(_timestamp_bound(occurred_after, "occurred_after"))
    if occurred_before is not None:
        clauses.append("occurred_at <= ?")
        parameters.append(_timestamp_bound(occurred_before, "occurred_before"))
    page_size = _bounded_int(limit, "limit", 1, MAX_PAGE_SIZE)
    start = _bounded_int(offset, "offset", 0, MAX_OFFSET)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    with closing(get_connection(db_path)) as connection:
        connection.isolation_level = None
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON;")
        connection.execute("BEGIN;")  # one read snapshot for the count and the page
        try:
            total = int(connection.execute(f"SELECT COUNT(*) FROM audit_events{where};", parameters).fetchone()[0])
            rows = connection.execute(
                f"SELECT {_SELECT_COLUMNS} FROM audit_events{where} "
                "ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?;",
                (*parameters, page_size, start),
            ).fetchall()
        finally:
            connection.execute("COMMIT;")
    return AuditEventPage(tuple(_row_to_event(row) for row in rows), total, page_size, start)
