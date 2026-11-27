"""Administrator audit-event listing (Part 4, Stage 5).

Repository tests call ``list_audit_events`` on temporary databases. API tests use
real accounts signed in through the login service; nothing overrides
``get_current_user``. An autouse guard verifies the real project database file
is never modified.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from backend.app.api.deps import FORBIDDEN_DETAIL, NOT_AUTHENTICATED_DETAIL
from backend.app.api.v1 import admin_audit as audit_routes
from backend.app.audit import repository as audit
from backend.app.audit.repository import (
    AuditEventPage,
    append_audit_event,
    init_audit_tables,
    list_audit_events,
)
from backend.app.auth import admin_repository
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT
from backend.app.auth.repository import init_auth_tables
from backend.app.main import app
from backend.app.schemas.admin import AUDIT_DETAIL_RESPONSE_KEYS, AuditEventListQuery
from backend.tests.auth_support import SignedInAccount, create_signed_in_account, make_auth_settings, use_auth_database

EVENTS = "/api/v1/admin/audit-events"
LOGIN = "/api/v1/auth/login"
EVENT_FIELDS = {
    "id", "occurred_at", "action", "outcome", "actor_type", "actor_user_id", "actor_role",
    "target_type", "target_id", "details",
}
T0 = datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _real_database_untouched() -> Iterator[None]:
    real_db = Path(app_config.get_settings().database_path).resolve()
    before = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    yield
    after = (real_db.stat().st_size, real_db.stat().st_mtime_ns) if real_db.exists() else None
    assert after == before, "The real project database was modified."


def _rows(db_path: Path) -> list[tuple]:
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute("SELECT * FROM audit_events ORDER BY id;").fetchall()


def _seed(db_path: Path) -> dict[str, int]:
    """A small, varied set of events in March 2025. Returns ids by label."""
    ids: dict[str, int] = {}

    def add(label: str, action: str, minutes: int, **fields: Any) -> None:
        fields.setdefault("outcome", "success")
        fields.setdefault("actor_type", "system")
        ids[label] = append_audit_event(action, occurred_at=T0 + timedelta(minutes=minutes), db_path=db_path, **fields).id

    admin = {"actor_type": "user", "actor_user_id": 1, "actor_role": ROLE_ADMINISTRATOR}
    add("created", "user.created", 0, target_type="user", target_id=7, details={"role": ROLE_STUDENT}, **admin)
    add("deactivated", "user.deactivated", 10, target_type="user", target_id=7, **admin)
    add("refused", "user.deactivated", 20, outcome="denied", target_type="user", target_id=1,
        details={"reason": "self_change"}, **admin)
    add("failed", "auth.login_failed", 30, outcome="failure", actor_type="anonymous", target_type="user", target_id=8,
        details={"reason": "invalid_password", "failed_login_count": 5})
    add("locked", "auth.account_locked", 30, target_type="user", target_id=8,
        details={"failed_login_count": 5, "locked_until": T0 + timedelta(minutes=45)})
    add("ingested", "regulation.ingested", 40, target_type="regulation", target_id=7, **admin)
    add("denied", "authorization.denied", 50, outcome="denied", actor_type="user", actor_user_id=2, actor_role=ROLE_STUDENT,
        details={"method": "GET", "path": "/api/v1/admin/users", "reason": "insufficient_role"})
    return ids


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "audit-list.db"
    init_audit_tables(path)
    return path


# --------------------------------------------------------------------------- #
# Repository: ordering and pagination
# --------------------------------------------------------------------------- #


def test_empty_log_returns_an_empty_page(db_path: Path) -> None:
    assert list_audit_events(db_path=db_path) == AuditEventPage((), 0, 50, 0)


def test_events_are_newest_first_with_id_breaking_ties(db_path: Path) -> None:
    ids = _seed(db_path)

    page = list_audit_events(db_path=db_path)

    # "failed" and "locked" share a timestamp: the later id comes first.
    assert [event.id for event in page.events] == [
        ids["denied"], ids["ingested"], ids["locked"], ids["failed"], ids["refused"], ids["deactivated"], ids["created"]
    ]
    assert page.total == 7


def test_order_follows_occurred_at_not_insertion(db_path: Path) -> None:
    late = append_audit_event("user.sessions_revoked", outcome="success", actor_type="system", target_type="user",
                              target_id=3, occurred_at=T0 + timedelta(days=1), db_path=db_path)
    early = append_audit_event("user.sessions_revoked", outcome="success", actor_type="system", target_type="user",
                               target_id=3, occurred_at=T0, db_path=db_path)

    assert [event.id for event in list_audit_events(db_path=db_path).events] == [late.id, early.id]


def test_many_identical_timestamps_paginate_without_gaps_or_repeats(db_path: Path) -> None:
    created = [
        append_audit_event("user.sessions_revoked", outcome="success", actor_type="system", target_type="user",
                           target_id=4, occurred_at=T0, db_path=db_path).id
        for _ in range(23)
    ]

    pages = [list_audit_events(limit=5, offset=offset, db_path=db_path) for offset in range(0, 25, 5)]
    seen = [event.id for page in pages for event in page.events]

    assert seen == sorted(created, reverse=True)
    assert {page.total for page in pages} == {23}
    assert [len(page.events) for page in pages] == [5, 5, 5, 5, 3]
    assert (pages[0].limit, pages[0].offset, pages[-1].offset) == (5, 0, 20)


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"outcome": "success"},
        {"actor_user_id": 5},
        {"target_type": "user", "target_id": 4},
        {"occurred_after": T0, "occurred_before": T0},
    ],
)
def test_ties_are_broken_by_id_under_every_query_plan(db_path: Path, filters: dict[str, Any]) -> None:
    actor = {"actor_type": "user", "actor_user_id": 5, "actor_role": ROLE_ADMINISTRATOR}
    created = [
        append_audit_event("user.sessions_revoked", outcome="success", target_type="user", target_id=4,
                           occurred_at=T0, db_path=db_path, **actor).id
        for _ in range(6)
    ]

    assert [event.id for event in list_audit_events(**filters, db_path=db_path).events] == sorted(created, reverse=True)


def test_tie_order_does_not_depend_on_indexes(db_path: Path) -> None:
    """Index scans happen to return ties by descending id; without indexes SQLite
    must sort, and only the explicit tie-breaker orders the ties."""
    with closing(sqlite3.connect(db_path)) as connection:
        for index in ("idx_audit_events_occurred_at", "idx_audit_events_actor", "idx_audit_events_target",
                      "idx_audit_events_action"):
            connection.execute(f"DROP INDEX {index};")  # temporary database only
        connection.commit()
    created = [
        append_audit_event("user.sessions_revoked", outcome="success", actor_type="system", target_type="user",
                           target_id=4, occurred_at=T0, db_path=db_path).id
        for _ in range(6)
    ]

    assert [event.id for event in list_audit_events(db_path=db_path).events] == sorted(created, reverse=True)
    assert [event.id for event in list_audit_events(limit=2, offset=2, db_path=db_path).events] == sorted(
        created, reverse=True)[2:4]


def test_offset_past_the_end_returns_no_events_but_the_total(db_path: Path) -> None:
    _seed(db_path)

    page = list_audit_events(limit=10, offset=100, db_path=db_path)

    assert (page.events, page.total, page.limit, page.offset) == ((), 7, 10, 100)


def test_largest_page_is_bounded(db_path: Path) -> None:
    for _ in range(audit.MAX_PAGE_SIZE + 5):
        append_audit_event("user.sessions_revoked", outcome="success", actor_type="system", target_type="user",
                           target_id=4, db_path=db_path)

    page = list_audit_events(limit=audit.MAX_PAGE_SIZE, db_path=db_path)

    assert len(page.events) == audit.MAX_PAGE_SIZE
    assert page.total == audit.MAX_PAGE_SIZE + 5


def test_pagination_bounds_match_the_user_listing_and_the_query_schema() -> None:
    assert (audit.DEFAULT_PAGE_SIZE, audit.MAX_PAGE_SIZE, audit.MAX_OFFSET) == (
        admin_repository.DEFAULT_PAGE_SIZE, admin_repository.MAX_PAGE_SIZE, admin_repository.MAX_OFFSET)
    fields = AuditEventListQuery.model_fields
    assert fields["limit"].default == audit.DEFAULT_PAGE_SIZE
    assert {"le": audit.MAX_PAGE_SIZE} in [{"le": getattr(m, "le", None)} for m in fields["limit"].metadata]
    assert {"le": audit.MAX_OFFSET} in [{"le": getattr(m, "le", None)} for m in fields["offset"].metadata]


# --------------------------------------------------------------------------- #
# Repository: filters
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"action": "user.deactivated"}, ["refused", "deactivated"]),
        ({"outcome": "denied"}, ["denied", "refused"]),
        ({"outcome": "failure"}, ["failed"]),
        ({"actor_user_id": 1}, ["ingested", "refused", "deactivated", "created"]),
        ({"actor_user_id": 2}, ["denied"]),
        ({"target_type": "regulation"}, ["ingested"]),
        ({"target_type": "user", "target_id": 7}, ["deactivated", "created"]),  # not regulation 7
        ({"target_type": "user", "target_id": 8}, ["locked", "failed"]),
        ({"action": "user.deactivated", "outcome": "denied", "actor_user_id": 1}, ["refused"]),
        ({"action": "user.reactivated"}, []),
        ({"actor_user_id": 999}, []),
    ],
)
def test_exact_filters(db_path: Path, filters: dict[str, Any], expected: list[str]) -> None:
    ids = _seed(db_path)

    page = list_audit_events(**filters, db_path=db_path)

    assert [event.id for event in page.events] == [ids[label] for label in expected]
    assert page.total == len(expected)


def test_time_bounds_are_inclusive(db_path: Path) -> None:
    ids = _seed(db_path)

    page = list_audit_events(occurred_after=T0 + timedelta(minutes=10), occurred_before=T0 + timedelta(minutes=30),
                             db_path=db_path)

    assert [event.id for event in page.events] == [ids["locked"], ids["failed"], ids["refused"], ids["deactivated"]]


def test_equal_time_bounds_select_one_instant(db_path: Path) -> None:
    ids = _seed(db_path)
    instant = T0 + timedelta(minutes=30)

    page = list_audit_events(occurred_after=instant, occurred_before=instant, db_path=db_path)

    assert [event.id for event in page.events] == [ids["locked"], ids["failed"]]


def test_time_bounds_in_other_offsets_mean_the_same_instant(db_path: Path) -> None:
    ids = _seed(db_path)
    india = timezone(timedelta(hours=5, minutes=30))

    page = list_audit_events(occurred_after=(T0 + timedelta(minutes=40)).astimezone(india), db_path=db_path)

    assert [event.id for event in page.events] == [ids["denied"], ids["ingested"]]


def test_sub_second_bounds_are_respected(db_path: Path) -> None:
    exact = append_audit_event("user.sessions_revoked", outcome="success", actor_type="system", target_type="user",
                               target_id=4, occurred_at=T0 + timedelta(microseconds=500), db_path=db_path)

    assert list_audit_events(occurred_after=T0 + timedelta(microseconds=501), db_path=db_path).total == 0
    assert list_audit_events(occurred_before=T0 + timedelta(microseconds=499), db_path=db_path).total == 0
    assert [e.id for e in list_audit_events(occurred_after=T0 + timedelta(microseconds=500), db_path=db_path).events] == [exact.id]


@pytest.mark.parametrize(
    ("bound", "expected_total"),
    [
        ({"occurred_after": datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5)))}, 7),  # earlier than year 1 UTC
        ({"occurred_before": datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=5)))}, 0),
        ({"occurred_after": datetime(9999, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=-5)))}, 0),  # after 9999
        ({"occurred_before": datetime(9999, 12, 31, 23, 0, tzinfo=timezone(timedelta(hours=-5)))}, 7),
    ],
)
def test_bounds_beyond_the_datetime_range_are_handled(db_path: Path, bound: dict[str, datetime], expected_total: int) -> None:
    _seed(db_path)

    assert list_audit_events(**bound, db_path=db_path).total == expected_total


@pytest.mark.parametrize(
    "filters",
    [
        {"action": "user.deleted"},
        {"action": "auth.login"},
        {"outcome": "maybe"},
        {"actor_user_id": 0},
        {"actor_user_id": True},
        {"actor_user_id": "3"},
        {"target_type": "document"},
        {"target_id": 7},  # without target_type
        {"target_type": "user", "target_id": -1},
        {"occurred_after": datetime(2025, 1, 1)},  # naive
        {"occurred_before": "2025-01-01T00:00:00+00:00"},
        {"limit": 0},
        {"limit": audit.MAX_PAGE_SIZE + 1},
        {"limit": True},
        {"offset": -1},
        {"offset": audit.MAX_OFFSET + 1},
    ],
)
def test_invalid_filters_are_rejected(db_path: Path, filters: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        list_audit_events(**filters, db_path=db_path)


def test_filter_values_are_parameters_not_sql(db_path: Path) -> None:
    _seed(db_path)
    hostile = datetime(2025, 3, 1, tzinfo=timezone.utc)

    # Only typed values reach SQL; strings that are not approved actions are refused before any query.
    with pytest.raises(ValueError):
        list_audit_events(action="user.created' OR '1'='1", db_path=db_path)
    assert list_audit_events(occurred_after=hostile, db_path=db_path).total == 7


def test_listing_is_read_only(db_path: Path) -> None:
    _seed(db_path)
    before = _rows(db_path)

    for filters in ({}, {"action": "user.created"}, {"limit": 1, "offset": 3}):
        list_audit_events(**filters, db_path=db_path)

    assert _rows(db_path) == before


def test_repository_returns_events_as_stored(db_path: Path) -> None:
    """The repository is internal: it keeps every recorded key; the API filters them."""
    ids = _seed(db_path)

    [locked] = list_audit_events(action="auth.account_locked", db_path=db_path).events

    assert locked.id == ids["locked"]
    assert set(locked.details) == {"failed_login_count", "locked_until"}


def test_missing_table_raises_instead_of_returning_nothing(tmp_path: Path) -> None:
    path = tmp_path / "no-audit.db"
    init_auth_tables(path)

    with pytest.raises(sqlite3.OperationalError):
        list_audit_events(db_path=path)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


class Env:
    def __init__(self, db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.db_path = db_path
        init_auth_tables(db_path)
        init_audit_tables(db_path)
        self.settings = make_auth_settings()
        use_auth_database(app, monkeypatch, db_path, self.settings)
        self.client = TestClient(app)
        self.admin = create_signed_in_account(db_path, self.settings, ROLE_ADMINISTRATOR)
        self.student = create_signed_in_account(db_path, self.settings, ROLE_STUDENT, admission_batch="2024",
                                                programme="BSc CS")

    def get(self, who: Optional[SignedInAccount] = None, **params: Any) -> Any:
        headers = (who or self.admin).headers
        return self.client.get(EVENTS, params=params, headers=headers)

    def body(self, **params: Any) -> dict[str, Any]:
        response = self.get(**params)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        return response.json()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path / "audit-api.db", monkeypatch)


MARCH = {"occurred_after": "2025-03-01T00:00:00Z", "occurred_before": "2025-03-31T23:59:59Z"}


def test_administrator_lists_events_with_the_approved_shape(env: Env) -> None:
    _seed(env.db_path)

    body = env.body()

    assert set(body) == {"events", "total", "limit", "offset"}
    assert (body["total"], body["limit"], body["offset"]) == (9, 50, 0)  # 7 seeded + 2 sign-ins
    for event in body["events"]:
        assert set(event) == EVENT_FIELDS
        assert set(event["details"]) <= AUDIT_DETAIL_RESPONSE_KEYS
    # The two sign-ins happened "now", after the seeded March 2025 events.
    assert [event["action"] for event in body["events"][:2]] == ["auth.login_succeeded"] * 2
    assert body["events"][0]["actor_user_id"] == env.student.user.id


def test_api_returns_events_newest_first_with_id_tie_breaker(env: Env) -> None:
    ids = _seed(env.db_path)

    body = env.body(**MARCH)

    assert [event["id"] for event in body["events"]] == [
        ids["denied"], ids["ingested"], ids["locked"], ids["failed"], ids["refused"], ids["deactivated"], ids["created"]
    ]
    assert body["events"][0]["details"] == {"method": "GET", "path": "/api/v1/admin/users", "reason": "insufficient_role"}
    assert datetime.fromisoformat(body["events"][0]["occurred_at"]) == T0 + timedelta(minutes=50)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"action": "user.deactivated"}, ["refused", "deactivated"]),
        ({"outcome": "failure"}, ["failed"]),
        ({"actor_user_id": "2"}, ["denied"]),
        ({"target_type": "regulation"}, ["ingested"]),
        ({"target_type": "user", "target_id": "7"}, ["deactivated", "created"]),
        ({"occurred_after": "2025-03-01T12:40:00+00:00", "occurred_before": "2025-03-01T18:20:00+05:30"},
         ["denied", "ingested"]),
        ({"action": "user.deactivated", "outcome": "denied"}, ["refused"]),
    ],
)
def test_api_filters(env: Env, params: dict[str, str], expected: list[str]) -> None:
    ids = _seed(env.db_path)

    body = env.body(**{**MARCH, **params})

    assert [event["id"] for event in body["events"]] == [ids[label] for label in expected]
    assert body["total"] == len(expected)


def test_api_pagination(env: Env) -> None:
    ids = _seed(env.db_path)

    first = env.body(**MARCH, limit=3)
    second = env.body(**MARCH, limit=3, offset=3)
    last = env.body(**MARCH, limit=3, offset=6)
    beyond = env.body(**MARCH, limit=3, offset=50)

    combined = [event["id"] for page in (first, second, last) for event in page["events"]]
    assert combined == [ids[label] for label in
                        ("denied", "ingested", "locked", "failed", "refused", "deactivated", "created")]
    assert {page["total"] for page in (first, second, last, beyond)} == {7}
    assert (beyond["events"], beyond["limit"], beyond["offset"]) == ([], 3, 50)


def test_empty_results(env: Env) -> None:
    _seed(env.db_path)

    for params in ({"action": "user.reactivated"}, {"actor_user_id": "999"},
                   {"target_type": "regulation", "target_id": "8"}, {"occurred_before": "2000-01-01T00:00:00Z"}):
        assert env.body(**params) == {"events": [], "total": 0, "limit": 50, "offset": 0}, params


@pytest.mark.parametrize(
    "params",
    [
        {"action": "user.deleted"},
        {"outcome": "maybe"},
        {"actor_user_id": "0"},
        {"actor_user_id": "abc"},
        {"target_id": "7"},
        {"target_type": "document"},
        {"occurred_after": "2025-03-01T00:00:00"},  # no offset
        {"occurred_after": "yesterday"},
        {"occurred_after": "2025-04-01T00:00:00Z", "occurred_before": "2025-03-01T00:00:00Z"},
        {"limit": "0"},
        {"limit": "101"},
        {"offset": "-1"},
        {"offset": "1000001"},
        {"details": "x"},
        {"email": "someone@uni.edu"},
        {"actor_id": "1"},
    ],
)
def test_invalid_parameters_are_rejected(env: Env, params: dict[str, str]) -> None:
    response = env.get(**params)

    assert response.status_code == 422
    assert "someone@uni.edu" not in response.text


def test_bounds_beyond_the_datetime_range_do_not_fail(env: Env) -> None:
    _seed(env.db_path)

    assert env.body(occurred_after="0001-01-01T00:00:00+05:00")["total"] == 9
    assert env.body(occurred_before="0001-01-01T00:00:00+05:00")["total"] == 0
    assert env.body(occurred_after="9999-12-31T23:00:00-05:00")["total"] == 0


def test_withheld_and_sensitive_details_are_never_returned(env: Env) -> None:
    """Real sign-in failures and a lockout record counters and lock expiry; the API withholds them."""
    victim = create_signed_in_account(env.db_path, env.settings, ROLE_STUDENT, admission_batch="2024", programme="BSc CS")
    wrong = "Wr0ng#" + "x" * 12
    for _ in range(5):
        assert env.client.post(LOGIN, json={"email": victim.user.email, "password": wrong}).status_code == 401
    _seed(env.db_path)

    response = env.get()
    events = response.json()["events"]

    actions = {event["action"] for event in events}
    assert {"auth.login_failed", "auth.account_locked"} <= actions
    locks = [event for event in events if event["action"] == "auth.account_locked"]
    assert all(event["details"] == {} for event in locks)
    failures = [event for event in events if event["action"] == "auth.login_failed"]
    assert {event["details"]["reason"] for event in failures} == {"invalid_password"}
    # ("invalid_password" is an approved reason value, so the bare word "password" may appear.)
    for marker in ("failed_login_count", "locked_until", "password_hash", "$argon2", "token", wrong, victim.password,
                   victim.token, env.admin.token, victim.user.email, env.admin.user.email):
        assert marker not in response.text, marker
    for event in events:
        assert set(event["details"]) <= AUDIT_DETAIL_RESPONSE_KEYS


def test_unknown_stored_detail_keys_are_dropped(env: Env) -> None:
    """Even a row written outside the repository cannot pass an unapproved key through."""
    with closing(sqlite3.connect(env.db_path)) as connection:
        connection.execute(
            "INSERT INTO audit_events (occurred_at, action, outcome, actor_type, target_type, target_id, details) "
            "VALUES ('2025-03-01T00:00:00.000000+00:00', 'user.unlocked', 'success', 'system', 'user', 3, ?);",
            (json.dumps({"failed_login_count": 4, "password_hash": "$argon2id$v=19$x", "email": "x@uni.edu"}),),
        )
        connection.commit()

    response = env.get(action="user.unlocked")

    assert response.json()["events"][0]["details"] == {}
    for marker in ("$argon2", "password_hash", "x@uni.edu", "failed_login_count"):
        assert marker not in response.text


def test_successful_reads_record_nothing_and_change_nothing(env: Env) -> None:
    _seed(env.db_path)
    before = _rows(env.db_path)

    for params in ({}, {"action": "user.created"}, {"limit": "1", "offset": "2"}, {"action": "user.reactivated"}):
        env.body(**params)
    assert env.get(limit="0").status_code == 422  # an administrator's invalid request is not audited either

    assert _rows(env.db_path) == before


def test_anonymous_requests_are_refused_and_not_recorded(env: Env) -> None:
    before = _rows(env.db_path)

    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        response = env.client.get(EVENTS, headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": NOT_AUTHENTICATED_DETAIL}

    assert _rows(env.db_path) == before


def test_students_are_refused_and_the_refusal_is_recorded(env: Env) -> None:
    _seed(env.db_path)

    response = env.get(who=env.student, action="user.created")

    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}
    assert "events" not in response.text
    [denied] = env.body(action="authorization.denied", occurred_after="2026-01-01T00:00:00Z")["events"]
    assert (denied["actor_user_id"], denied["actor_role"], denied["outcome"]) == (env.student.user.id, ROLE_STUDENT, "denied")
    assert denied["details"] == {"method": "GET", "path": EVENTS, "reason": "insufficient_role"}


def test_inactive_or_revoked_administrators_are_refused(env: Env) -> None:
    inactive = create_signed_in_account(env.db_path, env.settings, ROLE_ADMINISTRATOR, is_active=False)
    assert env.get(who=inactive).status_code == 401

    with closing(sqlite3.connect(env.db_path)) as connection:
        connection.execute("UPDATE users SET token_version = token_version + 1 WHERE id = ?;", (env.admin.user.id,))
        connection.commit()
    assert env.get().status_code == 401


def test_storage_failure_returns_a_generic_500(env: Env, monkeypatch: pytest.MonkeyPatch,
                                               caplog: pytest.LogCaptureFixture) -> None:
    def broken(**_: Any) -> AuditEventPage:
        raise sqlite3.OperationalError("disk I/O error at C:/secret/location.db")

    monkeypatch.setattr(audit_routes, "list_audit_events", broken)

    with caplog.at_level(logging.ERROR, logger=audit_routes.__name__):
        response = env.get()

    assert response.status_code == 500
    assert response.json() == {"detail": audit_routes.AUDIT_LIST_ERROR_DETAIL}
    assert "secret" not in response.text
    assert "Listing audit events failed." in caplog.text


def test_missing_audit_table_returns_a_generic_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = Env(tmp_path / "drop.db", monkeypatch)
    # Point listing (only) at a database without the table.
    empty = tmp_path / "empty.db"
    init_auth_tables(empty)
    real_list = audit_routes.list_audit_events
    monkeypatch.setattr(audit_routes, "list_audit_events", lambda **kw: real_list(**{**kw, "db_path": empty}))

    response = env.get()

    assert response.status_code == 500
    assert response.json() == {"detail": audit_routes.AUDIT_LIST_ERROR_DETAIL}


def test_route_is_documented_as_administrator_only() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    operation = schema["paths"][EVENTS]["get"]

    assert operation["security"] == [{"HTTPBearer": []}]
    assert {"401", "403", "422", "500"} <= set(operation["responses"])
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "action", "outcome", "actor_user_id", "target_type", "target_id", "occurred_after", "occurred_before",
        "limit", "offset",
    }
    assert set(schema["paths"]) & {f"{EVENTS}/{{event_id}}"} == set()
    assert set(schema["paths"][EVENTS]) == {"get"}  # no write operations
