"""Tests for regulation ingestion and verification FastAPI endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import fitz
from fastapi.testclient import TestClient

from app.database import get_regulation_by_id, init_database
from backend.app.api.v1.regulations import get_db_path
from backend.app.main import app
from backend.tests.auth_support import sign_in_module_clients_as_administrator


@pytest.fixture(autouse=True)
def _signed_in_as_administrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoints exercised here require an administrator since Stage 4.

    Every client this module creates sends the token of a real administrator
    account created for the test (see ``backend/tests/auth_support.py``).
    """
    sign_in_module_clients_as_administrator(sys.modules[__name__], app, tmp_path, monkeypatch)


def _create_test_db(tmp_path: Path) -> Path:
    """Create an isolated SQLite database for API tests."""
    db_path = tmp_path / "test_admin_api.db"
    init_database(db_path)
    return db_path


def _create_test_pdf(tmp_path: Path, filename: str = "regulation.pdf") -> Path:
    """Create a small valid PDF file for ingestion tests."""
    pdf_path = tmp_path / filename
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Attendance requirement is 75 percent for all students.")
        document.save(pdf_path)
    finally:
        document.close()
    return pdf_path


def _ingest_form_data() -> dict[str, object]:
    """Return valid multipart form metadata for ingestion requests."""
    return {
        "document_name": "Academic Regulations",
        "regulation_version": "2024",
        "effective_date": "2024-08-01",
        "applicable_batches": ["2024", "2025"],
        "applicable_programmes": ["BSc CS"],
    }


def test_successful_pdf_ingestion(tmp_path: Path) -> None:
    """POST /api/v1/regulations/ingest stores a regulation via existing services."""
    db_path = _create_test_db(tmp_path)
    pdf_path = _create_test_pdf(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with pdf_path.open("rb") as pdf_file:
            response = client.post(
                "/api/v1/regulations/ingest",
                data=_ingest_form_data(),
                files={"file": ("regulation.pdf", pdf_file, "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ingested"
    assert isinstance(data["regulation_id"], int)
    assert data["verification_status"] == "pending"
    assert data["message"] == "Regulation ingested and stored as pending administrator verification."
    assert data["extraction_summary"] is not None
    assert isinstance(data["extraction_summary"]["filename"], str)
    assert data["extraction_summary"]["filename"].endswith(".pdf")
    assert data["extraction_summary"]["total_pages"] >= 1
    assert isinstance(data["extraction_summary"]["pages"], list)


def test_invalid_file_type_rejected(tmp_path: Path) -> None:
    """Ingestion should reject non-PDF uploads."""
    db_path = _create_test_db(tmp_path)
    text_path = tmp_path / "not_a_pdf.txt"
    text_path.write_text("not a pdf", encoding="utf-8")

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with text_path.open("rb") as text_file:
            response = client.post(
                "/api/v1/regulations/ingest",
                data=_ingest_form_data(),
                files={"file": ("not_a_pdf.txt", text_file, "text/plain")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid file type. A PDF file is required."


def test_missing_required_metadata_rejected(tmp_path: Path) -> None:
    """Ingestion should validate required metadata before calling the workflow."""
    db_path = _create_test_db(tmp_path)
    pdf_path = _create_test_pdf(tmp_path)
    data = _ingest_form_data()
    data.pop("regulation_version")

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with pdf_path.open("rb") as pdf_file:
            response = client.post(
                "/api/v1/regulations/ingest",
                data=data,
                files={"file": ("regulation.pdf", pdf_file, "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    # FastAPI form validation rejects omitted required fields.
    assert response.status_code == 422


def test_uploaded_regulation_remains_pending(tmp_path: Path) -> None:
    """Uploading/ingestion must never automatically approve a regulation."""
    db_path = _create_test_db(tmp_path)
    pdf_path = _create_test_pdf(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with pdf_path.open("rb") as pdf_file:
            ingest_response = client.post(
                "/api/v1/regulations/ingest",
                data=_ingest_form_data(),
                files={"file": ("regulation.pdf", pdf_file, "application/pdf")},
            )
        assert ingest_response.status_code == 200
        regulation_id = ingest_response.json()["regulation_id"]
        detail_response = client.get(f"/api/v1/regulations/{regulation_id}")
    finally:
        app.dependency_overrides.clear()

    assert ingest_response.json()["verification_status"] == "pending"
    assert detail_response.status_code == 200
    assert detail_response.json()["regulation"]["verification_status"] == "pending"
    stored = get_regulation_by_id(regulation_id, db_path=db_path)
    assert stored is not None
    assert stored["verification_status"] == "pending"


def test_explicit_approval_succeeds(tmp_path: Path) -> None:
    """Explicit approval should update verification status through the service layer."""
    db_path = _create_test_db(tmp_path)
    pdf_path = _create_test_pdf(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with pdf_path.open("rb") as pdf_file:
            ingest_response = client.post(
                "/api/v1/regulations/ingest",
                data=_ingest_form_data(),
                files={"file": ("regulation.pdf", pdf_file, "application/pdf")},
            )
        regulation_id = ingest_response.json()["regulation_id"]

        response = client.patch(
            f"/api/v1/regulations/{regulation_id}/verification",
            json={"verification_status": "approved"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["regulation_id"] == regulation_id
    assert data["updated"] is True
    assert data["verification_status"] == "approved"


def test_explicit_rejection_succeeds(tmp_path: Path) -> None:
    """Explicit rejection should succeed when supported by existing workflow/database behavior."""
    db_path = _create_test_db(tmp_path)
    pdf_path = _create_test_pdf(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with pdf_path.open("rb") as pdf_file:
            ingest_response = client.post(
                "/api/v1/regulations/ingest",
                data=_ingest_form_data(),
                files={"file": ("regulation.pdf", pdf_file, "application/pdf")},
            )
        regulation_id = ingest_response.json()["regulation_id"]

        response = client.patch(
            f"/api/v1/regulations/{regulation_id}/verification",
            json={"verification_status": "rejected"},
        )
        detail_response = client.get(f"/api/v1/regulations/{regulation_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "updated"
    assert response.json()["verification_status"] == "rejected"
    assert detail_response.json()["regulation"]["verification_status"] == "rejected"


def test_invalid_verification_status_rejected(tmp_path: Path) -> None:
    """Blank/empty verification status should be rejected as invalid for explicit updates."""
    db_path = _create_test_db(tmp_path)
    pdf_path = _create_test_pdf(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with pdf_path.open("rb") as pdf_file:
            ingest_response = client.post(
                "/api/v1/regulations/ingest",
                data=_ingest_form_data(),
                files={"file": ("regulation.pdf", pdf_file, "application/pdf")},
            )
        regulation_id = ingest_response.json()["regulation_id"]

        response = client.patch(
            f"/api/v1/regulations/{regulation_id}/verification",
            json={"verification_status": "   "},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "verification_status" in response.json()["detail"]


def test_verification_nonexistent_regulation_returns_404(tmp_path: Path) -> None:
    """Verification updates for missing regulations should return HTTP 404."""
    db_path = _create_test_db(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.patch(
            "/api/v1/regulations/9999/verification",
            json={"verification_status": "approved"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Regulation not found"


def test_existing_read_only_endpoints_still_work(tmp_path: Path) -> None:
    """Adding admin endpoints must not break existing read-only regulation endpoints."""
    db_path = _create_test_db(tmp_path)
    pdf_path = _create_test_pdf(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        with pdf_path.open("rb") as pdf_file:
            ingest_response = client.post(
                "/api/v1/regulations/ingest",
                data=_ingest_form_data(),
                files={"file": ("regulation.pdf", pdf_file, "application/pdf")},
            )
        assert ingest_response.status_code == 200
        regulation_id = ingest_response.json()["regulation_id"]

        list_response = client.get("/api/v1/regulations")
        detail_response = client.get(f"/api/v1/regulations/{regulation_id}")
        pages_response = client.get(f"/api/v1/regulations/{regulation_id}/pages")
        health_response = client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert any(reg["id"] == regulation_id for reg in list_response.json()["regulations"])
    assert detail_response.status_code == 200
    assert detail_response.json()["regulation"]["id"] == regulation_id
    assert pages_response.status_code == 200
    assert pages_response.json()["regulation_id"] == regulation_id
    assert isinstance(pages_response.json()["pages"], list)
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
