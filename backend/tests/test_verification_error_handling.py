"""Error handling for ``PATCH /api/v1/regulations/{regulation_id}/verification``.

Status-code contract:
- 200: status updated (approved, pending or rejected; case-insensitive)
- 400: blank status, or a status outside the allowed set
- 404: regulation does not exist
- 500: unexpected database/server failure, with a generic body; the original
  exception and traceback are logged server-side only

Every test uses an isolated temporary SQLite database. Gemini is never called.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.database import get_regulation_by_id, init_database, insert_document_pages, insert_regulation
from app.models import GroundedAnswer, GroundedCitation
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.app.services import regulation_service

BATCH = "2024"
PROGRAMME = "BSc CS"
PAGE_TEXT = "Students must maintain at least 75 percent attendance in each course."

SECRET_MARKER = "sk-PLANTED-SECRET-verification-5678"
PRIVATE_PATH = r"C:\srv\cohortiq\private\cohortiq.db"

ROUTE_LOGGER = "backend.app.api.v1.regulations"
WORKFLOW_LOGGER = "app.workflow"


class Env:
    def __init__(self, client: TestClient, db_path: Path, tmp_path: Path, regulation_id: int) -> None:
        self.client = client
        self.db_path = db_path
        self.tmp_path = tmp_path
        self.regulation_id = regulation_id

    def patch_status(self, status: Any, regulation_id: int | None = None):
        target = self.regulation_id if regulation_id is None else regulation_id
        return self.client.patch(
            f"/api/v1/regulations/{target}/verification",
            json={"verification_status": status},
        )

    def stored_status(self) -> str | None:
        regulation = get_regulation_by_id(self.regulation_id, db_path=self.db_path)
        assert regulation is not None
        return regulation["verification_status"]

    def cohort_ids(self) -> list[int]:
        response = self.client.get(f"/api/v1/cohorts/{BATCH}/BSc%20CS/regulations")
        assert response.status_code == 200
        return [item["id"] for item in response.json()["regulations"]]

    def planted_text(self) -> str:
        return f"disk I/O error at {PRIVATE_PATH} temp={self.db_path} key={SECRET_MARKER}"


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    db_path = tmp_path / "verification.db"
    init_database(db_path)
    regulation_id = insert_regulation(
        {
            "document_name": "Attendance Rules",
            "regulation_version": "R2024",
            "effective_date": "2024-08-01",
            "applicable_batches": [BATCH],
            "applicable_programmes": [PROGRAMME],
            "upload_date": "2024-07-01",
            "total_pages": 1,
            "processing_status": "extracted",
            "verification_status": "pending",
        },
        db_path=db_path,
    )
    insert_document_pages(
        regulation_id,
        [{"page_number": 1, "extracted_text": PAGE_TEXT, "extraction_status": "success"}],
        db_path=db_path,
    )
    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    try:
        yield Env(TestClient(app), db_path, tmp_path, regulation_id)
    finally:
        app.dependency_overrides.pop(regulation_routes.get_db_path, None)
        app.dependency_overrides.pop(query_routes.get_db_path, None)


def _assert_generic_500(response: Any, env: Env) -> None:
    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.VERIFICATION_INTERNAL_ERROR_DETAIL}
    detail = response.json()["detail"]
    for forbidden in (
        SECRET_MARKER,
        PRIVATE_PATH,
        str(env.tmp_path),
        str(env.db_path),
        "disk I/O",
        "Traceback",
        'File "',
        "OperationalError",
        "RuntimeError",
        "Failed to update regulation verification status",
    ):
        assert forbidden not in detail, f"Response leaked {forbidden!r}"
        assert forbidden not in response.text, f"Response leaked {forbidden!r}"


# --------------------------------------------------------------------------- #
# 200: successful updates
# --------------------------------------------------------------------------- #


def test_successful_approval(env: Env) -> None:
    response = env.patch_status("approved")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "updated"
    assert body["updated"] is True
    assert body["regulation_id"] == env.regulation_id
    assert body["verification_status"] == "approved"
    assert env.stored_status() == "approved"
    assert env.cohort_ids() == [env.regulation_id]


def test_successful_rejection(env: Env) -> None:
    env.patch_status("approved")

    response = env.patch_status("rejected")

    assert response.status_code == 200
    assert response.json()["verification_status"] == "rejected"
    assert env.stored_status() == "rejected"
    assert env.cohort_ids() == [], "Rejected regulations must not be visible to students."


def test_returning_regulation_to_pending(env: Env) -> None:
    env.patch_status("approved")

    response = env.patch_status("pending")

    assert response.status_code == 200
    assert env.stored_status() == "pending"
    assert env.cohort_ids() == []


def test_status_is_normalized_to_canonical_lower_case(env: Env) -> None:
    response = env.patch_status("  Approved ")

    assert response.status_code == 200
    assert response.json()["verification_status"] == "approved"
    assert env.stored_status() == "approved"


# --------------------------------------------------------------------------- #
# 400: blank or unsupported statuses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status",
    [
        "verified",
        "unverified",
        "administrator_verified",
        "pending_review",
        "deleted",
        "approved; DROP TABLE regulations",
        "<script>alert(1)</script>",
    ],
)
def test_unsupported_status_rejected_with_400(env: Env, status: str) -> None:
    response = env.patch_status(status)

    assert response.status_code == 400
    assert response.json() == {"detail": regulation_routes.INVALID_VERIFICATION_STATUS_DETAIL}
    assert status not in response.text, "Client input must not be reflected in the error."
    assert env.stored_status() == "pending", "Rejected requests must not change stored status."


def test_invalid_status_detail_lists_allowed_values() -> None:
    assert regulation_routes.INVALID_VERIFICATION_STATUS_DETAIL == (
        "Invalid verification_status. Allowed values: approved, pending, rejected."
    )


@pytest.mark.parametrize("status", ["", "   "])
def test_blank_status_rejected_with_400(env: Env, status: str) -> None:
    response = env.patch_status(status)

    assert response.status_code == 400
    assert response.json() == {"detail": "An explicit verification_status value is required."}
    assert env.stored_status() == "pending"


def test_status_is_validated_before_database_access(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(regulation_service, "approve_or_verify_regulation", lambda **kw: calls.append(kw))

    assert env.patch_status("verified").status_code == 400
    assert env.patch_status("   ").status_code == 400
    assert calls == []


# --------------------------------------------------------------------------- #
# 404: missing regulation
# --------------------------------------------------------------------------- #


def test_missing_regulation_returns_404(env: Env) -> None:
    response = env.patch_status("approved", regulation_id=999999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Regulation not found"}


def test_invalid_status_for_missing_regulation_is_still_400(env: Env) -> None:
    assert env.patch_status("verified", regulation_id=999999).status_code == 400


# --------------------------------------------------------------------------- #
# 500: unexpected server failures are generic and logged
# --------------------------------------------------------------------------- #


def test_database_exception_returns_generic_500_and_is_logged(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    planted = env.planted_text()

    def failing_update(*_args: Any, **_kwargs: Any) -> bool:
        raise sqlite3.OperationalError(planted)

    monkeypatch.setattr("app.workflow.update_regulation_verification_status", failing_update)

    with caplog.at_level(logging.ERROR):
        response = env.patch_status("approved")

    _assert_generic_500(response, env)
    assert env.stored_status() == "pending"

    # Original technical details (with traceback) are retained in server logs.
    workflow_records = [r for r in caplog.records if r.name == WORKFLOW_LOGGER]
    assert workflow_records and workflow_records[0].exc_info is not None
    assert isinstance(workflow_records[0].exc_info[1], sqlite3.OperationalError)
    assert planted in caplog.text
    assert "Traceback" in caplog.text
    route_records = [r for r in caplog.records if r.name == ROUTE_LOGGER]
    assert route_records and route_records[0].levelno == logging.ERROR


def test_unusable_database_returns_generic_500(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    """A real SQLite failure (database path is a directory) is a server error, not a 400."""
    broken_db = env.tmp_path / "database_is_a_directory"
    broken_db.mkdir()
    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(broken_db)

    with caplog.at_level(logging.ERROR):
        response = env.patch_status("approved")

    _assert_generic_500(response, env)
    assert str(broken_db) not in response.text
    assert any(r.exc_info for r in caplog.records if r.name == WORKFLOW_LOGGER)


def test_exception_raised_by_service_returns_generic_500(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    planted = env.planted_text()

    def exploding_service(**_kwargs: Any) -> Any:
        raise RuntimeError(planted)

    monkeypatch.setattr(regulation_service, "approve_or_verify_regulation", exploding_service)

    with caplog.at_level(logging.ERROR, logger=ROUTE_LOGGER):
        response = env.patch_status("approved")

    _assert_generic_500(response, env)
    records = [r for r in caplog.records if r.name == ROUTE_LOGGER]
    assert records and records[0].exc_info is not None
    assert planted in caplog.text


@pytest.mark.parametrize(
    "result",
    [
        {"status": "error", "regulation_id": 1, "updated": False, "message": f"boom {SECRET_MARKER}"},
        {"status": "something_unexpected", "message": f"odd {SECRET_MARKER}"},
        {},
    ],
)
def test_unrecognized_workflow_outcomes_are_server_errors(
    env: Env, monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]
) -> None:
    monkeypatch.setattr(regulation_service, "approve_or_verify_regulation", lambda **_kw: result)

    response = env.patch_status("approved")

    _assert_generic_500(response, env)


# --------------------------------------------------------------------------- #
# Other endpoints remain functional
# --------------------------------------------------------------------------- #


def test_regulation_and_query_endpoints_still_work_after_verification(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert env.patch_status("approved").status_code == 200

    listing = env.client.get("/api/v1/regulations")
    assert listing.status_code == 200
    assert [item["verification_status"] for item in listing.json()["regulations"]] == ["approved"]
    assert env.client.get(f"/api/v1/regulations/{env.regulation_id}/pages").status_code == 200

    def answer(**kwargs: Any) -> GroundedAnswer:
        chunk = dict(kwargs["evidence_chunks"][0])
        return GroundedAnswer(
            answer="Students must maintain at least 75 percent attendance.",
            status="answered",
            citations=[
                GroundedCitation(
                    chunk_id=str(chunk["chunk_id"]),
                    relevant_supporting_text="at least 75 percent attendance",
                )
            ],
        )

    monkeypatch.setattr("app.workflow.generate_grounded_answer", answer)
    query = env.client.post(
        "/api/v1/query/ask",
        json={"question": "What is the attendance requirement?", "admission_batch": BATCH, "programme": PROGRAMME},
    )
    assert query.status_code == 200
    assert query.json()["status"] == "answered"
    assert query.json()["citations"][0]["document_name"] == "Attendance Rules"


def test_openapi_documents_verification_responses(env: Env) -> None:
    schema = env.client.get("/openapi.json").json()
    operation = schema["paths"]["/api/v1/regulations/{regulation_id}/verification"]["patch"]
    assert {"200", "400", "404", "500"} <= set(operation["responses"])
    field = schema["components"]["schemas"]["VerificationUpdateRequest"]["properties"]["verification_status"]
    assert "approved, pending, rejected" in field["description"]
