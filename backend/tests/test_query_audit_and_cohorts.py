"""Question auditing and the public cohort list."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import init_database, insert_regulation
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.audit.repository import list_audit_events
from backend.app.main import app
from backend.tests.auth_support import create_signed_in_account, make_auth_settings, use_auth_database

QUESTION = "Who won the cricket world cup in 2011?"  # out of scope: no model call


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cohortiq.db"
    init_database(path)
    for dependency in (query_routes.get_db_path, regulation_routes.get_db_path):
        monkeypatch.setitem(app.dependency_overrides, dependency, lambda: str(path))
    return path


def _student(db_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = make_auth_settings()
    account = create_signed_in_account(db_path, settings, "student", admission_batch="2024", programme="BSc CS")
    use_auth_database(app, monkeypatch, db_path, settings)
    return account


def _ask(account):
    return TestClient(app).post(
        "/api/v1/query/ask",
        headers=account.headers,
        json={"question": QUESTION, "admission_batch": "2024", "programme": "BSc CS"},
    )


def test_question_is_audited_without_its_text(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account = _student(db_path, monkeypatch)

    assert _ask(account).status_code == 200

    [event] = list_audit_events(action="query.answered", db_path=db_path).events
    assert event.actor_user_id == account.user.id
    assert dict(event.details) == {
        "route": "out_of_scope",
        "answer_status": "insufficient_evidence",
        "admission_batch": "2024",
        "programme": "BSc CS",
    }
    assert "cricket" not in json.dumps(dict(event.details))


def test_audit_failure_does_not_lose_the_answer(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    account = _student(db_path, monkeypatch)

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(query_routes, "append_audit_event", broken)

    assert _ask(account).status_code == 200


def _regulation(db_path: Path, batches: list[str], programmes: list[str], status: str) -> None:
    insert_regulation(
        {
            "document_name": "Rules",
            "regulation_version": "1",
            "applicable_batches": batches,
            "applicable_programmes": programmes,
            "upload_date": "2024-01-01",
            "verification_status": status,
        },
        db_path=db_path,
    )


def test_cohort_list_is_public_distinct_and_approved_only(db_path: Path) -> None:
    _regulation(db_path, ["2025", "2024"], ["BSc CS"], "approved")
    _regulation(db_path, ["2024"], ["BSc CS"], "approved")
    _regulation(db_path, ["2030"], ["Hidden"], "pending")
    _regulation(db_path, ["2031"], ["Hidden"], "rejected")

    response = TestClient(app).get("/api/v1/cohorts")

    assert response.status_code == 200
    assert response.json() == {
        "cohorts": [
            {"admission_batch": "2024", "programme": "BSc CS"},
            {"admission_batch": "2025", "programme": "BSc CS"},
        ]
    }


def test_cohort_list_is_empty_without_approved_regulations(db_path: Path) -> None:
    assert TestClient(app).get("/api/v1/cohorts").json() == {"cohorts": []}
