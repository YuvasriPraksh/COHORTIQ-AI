"""HTTP status-code handling for the regulation ingestion endpoint.

Status-code contract for ``POST /api/v1/regulations/ingest``:

- 200: regulation ingested (stored as pending)
- 400: unsupported file type, blank metadata, or workflow metadata rejection
- 422: omitted form fields (FastAPI validation) or an unreadable/corrupted PDF
- 500: server-side failures (storage, temp-file handling, unexpected errors)

Failure classification is driven by the real workflow wherever possible; only
server faults that cannot be triggered through the API are simulated. Every
test runs against an isolated temporary SQLite database.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

import fitz
import pytest
from fastapi.testclient import TestClient

from app import workflow
from app.database import init_database
from app.models import GroundedAnswer
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.app.services import regulation_service
from backend.app.services.regulation_service import (
    IngestionFailureKind,
    classify_ingestion_failure,
)
from backend.tests.auth_support import sign_in_module_clients_as_administrator


@pytest.fixture(autouse=True)
def _signed_in_as_administrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoints exercised here require an administrator since Stage 4.

    Every client this module creates sends the token of a real administrator
    account created for the test (see ``backend/tests/auth_support.py``).
    """
    sign_in_module_clients_as_administrator(sys.modules[__name__], app, tmp_path, monkeypatch)


INGEST_URL = "/api/v1/regulations/ingest"
SECRET_MARKER = "sk-test-SECRET-should-never-leak"

VALID_METADATA: dict[str, Any] = {
    "document_name": "Academic Regulations",
    "regulation_version": "R2024",
    "effective_date": "2024-08-01",
    "applicable_batches": ["2024"],
    "applicable_programmes": ["BSc CS"],
}


class IngestionHarness:
    """Test client plus a record of every temporary upload path that was created."""

    def __init__(self, client: TestClient, db_path: Path, tmp_path: Path) -> None:
        self.client = client
        self.db_path = db_path
        self.tmp_path = tmp_path
        self.temp_upload_paths: list[Path] = []

    def upload(
        self,
        content: bytes,
        *,
        filename: str = "regulation.pdf",
        content_type: str = "application/pdf",
        data: dict[str, Any] | None = None,
    ):
        return self.client.post(
            INGEST_URL,
            data=VALID_METADATA if data is None else data,
            files={"file": (filename, content, content_type)},
        )

    def stored_regulations(self) -> list[dict[str, Any]]:
        response = self.client.get("/api/v1/regulations")
        assert response.status_code == 200
        return response.json()["regulations"]

    def assert_temp_uploads_removed(self, expected_count: int = 1) -> None:
        assert len(self.temp_upload_paths) == expected_count
        for path in self.temp_upload_paths:
            assert not path.exists(), f"Temporary upload was not removed: {path}"


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[IngestionHarness]:
    db_path = tmp_path / "ingestion_errors.db"
    init_database(db_path)
    harness = IngestionHarness(TestClient(app), db_path, tmp_path)

    real_ingest = regulation_service.ingest_regulation

    def recording_ingest(pdf_path: Any, metadata: Any, db_path: Any = None) -> dict[str, Any]:
        harness.temp_upload_paths.append(Path(pdf_path))
        assert Path(pdf_path).exists(), "Upload must be written to disk before ingestion."
        return real_ingest(pdf_path=pdf_path, metadata=metadata, db_path=db_path)

    monkeypatch.setattr(regulation_service, "ingest_regulation", recording_ingest)
    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    try:
        yield harness
    finally:
        app.dependency_overrides.pop(regulation_routes.get_db_path, None)
        app.dependency_overrides.pop(query_routes.get_db_path, None)


def _valid_pdf_bytes(text: str = "Attendance requirement is 75 percent for all students.") -> bytes:
    document = fitz.open()
    try:
        document.new_page().insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


def _assert_no_internal_details(response: Any, *extra_forbidden: str) -> None:
    body_text = response.text
    for forbidden in ("Traceback", "File \"", "tmp", "Temp", ".py", *extra_forbidden):
        assert forbidden not in body_text, f"Response leaked {forbidden!r}: {body_text}"


# --------------------------------------------------------------------------- #
# Success path is unchanged
# --------------------------------------------------------------------------- #


def test_valid_pdf_returns_200_with_unchanged_success_body(harness: IngestionHarness) -> None:
    response = harness.upload(_valid_pdf_bytes())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ingested"
    assert body["verification_status"] == "pending"
    assert isinstance(body["regulation_id"], int)
    assert body["message"] == "Regulation ingested and stored as pending administrator verification."
    assert body["extraction_summary"]["total_pages"] == 1
    assert body["extraction_summary"]["successful_pages"] == 1
    assert len(harness.stored_regulations()) == 1
    harness.assert_temp_uploads_removed()


# --------------------------------------------------------------------------- #
# Client errors (4xx)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"%PDF-1.7\nthis body is not a real PDF structure", id="corrupted_pdf"),
        pytest.param(b"", id="empty_file"),
        pytest.param(b"Plain text renamed to look like a PDF.", id="text_renamed_pdf"),
        pytest.param(_valid_pdf_bytes()[:200], id="truncated_pdf"),
    ],
)
def test_unreadable_pdf_returns_422_and_stores_nothing(harness: IngestionHarness, content: bytes) -> None:
    response = harness.upload(content)

    assert response.status_code == 422
    assert response.json() == {"detail": regulation_routes.INVALID_PDF_DETAIL}
    _assert_no_internal_details(response)
    assert harness.stored_regulations() == []
    harness.assert_temp_uploads_removed()


def test_unsupported_file_type_still_rejected_with_400(harness: IngestionHarness) -> None:
    response = harness.upload(b"not a pdf", filename="notes.txt", content_type="text/plain")

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid file type. A PDF file is required."}
    assert harness.temp_upload_paths == [], "Rejected uploads must not reach ingestion."
    assert harness.stored_regulations() == []


def test_omitted_metadata_field_still_rejected_with_422(harness: IngestionHarness) -> None:
    data = {key: value for key, value in VALID_METADATA.items() if key != "regulation_version"}

    response = harness.upload(_valid_pdf_bytes(), data=data)

    assert response.status_code == 422
    assert harness.temp_upload_paths == []
    assert harness.stored_regulations() == []


@pytest.mark.parametrize("blank_field", ["document_name", "regulation_version", "effective_date"])
def test_blank_metadata_still_rejected_with_400(harness: IngestionHarness, blank_field: str) -> None:
    response = harness.upload(_valid_pdf_bytes(), data={**VALID_METADATA, blank_field: "   "})

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing required metadata."}
    assert harness.temp_upload_paths == []
    assert harness.stored_regulations() == []


def test_workflow_metadata_rejection_maps_to_400(
    harness: IngestionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the workflow's own metadata validation rejects input, the client gets 400."""
    real_validate = workflow._validate_admin_metadata

    def stricter_validation(metadata: Any) -> dict[str, Any]:
        return real_validate({**dict(metadata), "effective_date": None})

    monkeypatch.setattr(workflow, "_validate_admin_metadata", stricter_validation)

    response = harness.upload(_valid_pdf_bytes())

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid regulation metadata: Missing or invalid required metadata: effective_date"
    }
    assert harness.stored_regulations() == []
    harness.assert_temp_uploads_removed()


# --------------------------------------------------------------------------- #
# Server errors (500) are never reported as client errors
# --------------------------------------------------------------------------- #


def test_storage_failure_returns_500_without_leaking_details(
    harness: IngestionHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def failing_insert(*_args: Any, **_kwargs: Any) -> int:
        raise sqlite3.OperationalError(f"disk I/O error at C:\\private\\cohortiq.db {SECRET_MARKER}")

    # Ingestion stores the regulation and its pages through one atomic call.
    monkeypatch.setattr(workflow, "insert_regulation_with_pages", failing_insert)

    with caplog.at_level("ERROR", logger="backend.app.api.v1.regulations"):
        response = harness.upload(_valid_pdf_bytes())

    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.INGESTION_INTERNAL_ERROR_DETAIL}
    _assert_no_internal_details(response, SECRET_MARKER, "disk I/O", "private")
    assert harness.stored_regulations() == []
    harness.assert_temp_uploads_removed()
    # Full details are kept in server logs for operators.
    assert "internal_error" in caplog.text
    assert "disk I/O error" in caplog.text


def test_unexpected_extraction_error_returns_500_not_4xx(
    harness: IngestionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crashing_extractor(pdf_path: Any) -> Any:
        raise RuntimeError(f"Unexpected error while extracting PDF '{pdf_path}': boom")

    monkeypatch.setattr(workflow, "extract_text_from_pdf", crashing_extractor)

    response = harness.upload(_valid_pdf_bytes())

    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.INGESTION_INTERNAL_ERROR_DETAIL}
    _assert_no_internal_details(response, "boom")
    harness.assert_temp_uploads_removed()


def test_missing_temporary_file_is_a_server_error(
    harness: IngestionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_ingest = workflow.ingest_uploaded_regulation

    def ingest_after_temp_file_vanishes(pdf_path: Any, metadata: Any, db_path: Any = None) -> dict[str, Any]:
        Path(pdf_path).unlink()
        return real_ingest(pdf_path=pdf_path, metadata=metadata, db_path=db_path)

    monkeypatch.setattr(workflow, "ingest_uploaded_regulation", ingest_after_temp_file_vanishes)

    response = harness.upload(_valid_pdf_bytes())

    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.INGESTION_INTERNAL_ERROR_DETAIL}


def test_unexpected_exception_returns_generic_500_without_stack_trace(
    harness: IngestionHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def exploding_ingest(**_kwargs: Any) -> dict[str, Any]:
        raise KeyError(f"GEMINI_API_KEY={SECRET_MARKER}")

    monkeypatch.setattr(workflow, "ingest_uploaded_regulation", exploding_ingest)

    with caplog.at_level("ERROR", logger="backend.app.api.v1.regulations"):
        response = harness.upload(_valid_pdf_bytes())

    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.INGESTION_INTERNAL_ERROR_DETAIL}
    _assert_no_internal_details(response, SECRET_MARKER, "GEMINI_API_KEY", "KeyError")
    harness.assert_temp_uploads_removed()
    assert "Unexpected error during regulation ingestion" in caplog.text


def test_unrecognized_workflow_result_is_a_server_error(
    harness: IngestionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        workflow,
        "ingest_uploaded_regulation",
        lambda **_kwargs: {"status": "partially_done", "message": "Something odd happened."},
    )

    response = harness.upload(_valid_pdf_bytes())

    assert response.status_code == 500
    assert response.json() == {"detail": regulation_routes.INGESTION_INTERNAL_ERROR_DETAIL}


# --------------------------------------------------------------------------- #
# Classifier contract, pinned against the real workflow's messages
# --------------------------------------------------------------------------- #


def test_classifier_matches_real_workflow_results(tmp_path: Path) -> None:
    db_path = tmp_path / "classifier.db"
    init_database(db_path)

    valid_pdf = tmp_path / "valid.pdf"
    valid_pdf.write_bytes(_valid_pdf_bytes())
    corrupted_pdf = tmp_path / "corrupted.pdf"
    corrupted_pdf.write_bytes(b"%PDF-1.7 corrupted")

    success = workflow.ingest_uploaded_regulation(valid_pdf, VALID_METADATA, db_path)
    corrupted = workflow.ingest_uploaded_regulation(corrupted_pdf, VALID_METADATA, db_path)
    bad_metadata = workflow.ingest_uploaded_regulation(
        valid_pdf, {**VALID_METADATA, "document_name": ""}, db_path
    )
    missing_file = workflow.ingest_uploaded_regulation(tmp_path / "missing.pdf", VALID_METADATA, db_path)
    directory_path = workflow.ingest_uploaded_regulation(tmp_path, VALID_METADATA, db_path)

    assert classify_ingestion_failure(success) is None
    assert classify_ingestion_failure(corrupted) is IngestionFailureKind.INVALID_PDF
    assert classify_ingestion_failure(bad_metadata) is IngestionFailureKind.INVALID_METADATA
    assert classify_ingestion_failure(missing_file) is IngestionFailureKind.INTERNAL_ERROR
    assert classify_ingestion_failure(directory_path) is IngestionFailureKind.INTERNAL_ERROR


@pytest.mark.parametrize(
    "result",
    [
        {"status": "error", "message": "Failed to store regulation data: database is locked"},
        {"status": "error", "message": "PDF extraction failed: Unexpected error while extracting PDF"},
        {"status": "error", "message": ""},
        {"status": "error"},
        {"status": None, "message": "Invalid regulation metadata: spoofed"},
        {},
    ],
)
def test_classifier_defaults_unknown_failures_to_internal_error(result: dict[str, Any]) -> None:
    assert classify_ingestion_failure(result) is IngestionFailureKind.INTERNAL_ERROR


# --------------------------------------------------------------------------- #
# Approval and query endpoints are unaffected
# --------------------------------------------------------------------------- #


def test_approval_and_query_endpoints_still_work_after_ingestion(
    harness: IngestionHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    regulation_id = harness.upload(_valid_pdf_bytes()).json()["regulation_id"]

    approval = harness.client.patch(
        f"/api/v1/regulations/{regulation_id}/verification",
        json={"verification_status": "approved"},
    )
    assert approval.status_code == 200
    assert approval.json()["verification_status"] == "approved"

    missing = harness.client.patch(
        "/api/v1/regulations/999999/verification", json={"verification_status": "approved"}
    )
    assert missing.status_code == 404

    evidence_seen: list[Any] = []

    def fake_generate(**kwargs: Any) -> GroundedAnswer:
        evidence_seen.extend(kwargs.get("evidence_chunks") or [])
        return GroundedAnswer(
            answer="The supplied evidence does not answer this question.",
            status="insufficient_evidence",
            limitations="Test double.",
        )

    monkeypatch.setattr("app.workflow.generate_grounded_answer", fake_generate)

    query = harness.client.post(
        "/api/v1/query/ask",
        json={"question": "What is the attendance requirement?", "admission_batch": "2024", "programme": "BSc CS"},
    )
    assert query.status_code == 200
    assert query.json()["status"] == "insufficient_evidence"
    assert evidence_seen and all(chunk["regulation_id"] == regulation_id for chunk in evidence_seen)


def test_openapi_documents_ingestion_error_responses(harness: IngestionHarness) -> None:
    responses = harness.client.get("/openapi.json").json()["paths"][INGEST_URL]["post"]["responses"]
    assert {"200", "400", "422", "500"} <= set(responses)
