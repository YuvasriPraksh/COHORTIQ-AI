"""Tests for read-only regulation FastAPI endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.database import (
    init_database,
    insert_document_pages,
    insert_regulation,
    update_regulation_verification_status,
)
from backend.app.api.v1.regulations import get_db_path
from backend.app.main import app


def _create_test_db(tmp_path: Path) -> Path:
    """Create an isolated SQLite database for API tests."""
    db_path = tmp_path / "test_api.db"
    init_database(db_path)
    return db_path


def _seed_regulation(
    db_path: Path,
    *,
    document_name: str = "Academic Regulations",
    regulation_version: str = "v1",
    effective_date: str = "2024-01-01",
    applicable_batches: list[str] | None = None,
    applicable_programmes: list[str] | None = None,
    verification_status: str | None = "pending",
    with_pages: bool = True,
) -> int:
    """Insert a regulation (and optional pages) into the isolated test database."""
    regulation_id = insert_regulation(
        {
            "document_name": document_name,
            "regulation_version": regulation_version,
            "effective_date": effective_date,
            "applicable_batches": applicable_batches or ["2024"],
            "applicable_programmes": applicable_programmes or ["BSc CS"],
            "upload_date": "2024-02-01",
            "total_pages": 2 if with_pages else 0,
            "processing_status": "extracted",
            "verification_status": verification_status,
        },
        db_path=db_path,
    )
    if with_pages:
        insert_document_pages(
            regulation_id,
            [
                {
                    "page_number": 1,
                    "extracted_text": "Page one text",
                    "extraction_status": "success",
                },
                {
                    "page_number": 2,
                    "extracted_text": "Page two text",
                    "extraction_status": "success",
                },
            ],
            db_path=db_path,
        )
    return regulation_id


def test_existing_health_endpoint_remains_functional() -> None:
    """Existing health endpoint behavior should remain unchanged."""
    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "CohortIQ AI API",
        "message": "API is running",
    }


def test_list_regulations_success(tmp_path: Path) -> None:
    """GET /api/v1/regulations returns regulations from the shared service."""
    db_path = _create_test_db(tmp_path)
    reg_id = _seed_regulation(db_path, document_name="Reg A", verification_status="pending")

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.get("/api/v1/regulations")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert "regulations" in data
    assert len(data["regulations"]) == 1
    assert data["regulations"][0]["id"] == reg_id
    assert data["regulations"][0]["document_name"] == "Reg A"
    assert data["regulations"][0]["verification_status"] == "pending"


def test_get_regulation_detail_success(tmp_path: Path) -> None:
    """GET /api/v1/regulations/{id} returns regulation details when found."""
    db_path = _create_test_db(tmp_path)
    reg_id = _seed_regulation(db_path, document_name="Reg Detail", verification_status="approved")

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.get(f"/api/v1/regulations/{reg_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["regulation"]["id"] == reg_id
    assert data["regulation"]["document_name"] == "Reg Detail"


def test_get_regulation_detail_not_found(tmp_path: Path) -> None:
    """GET /api/v1/regulations/{id} returns 404 when regulation does not exist."""
    db_path = _create_test_db(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.get("/api/v1/regulations/9999")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Regulation not found"


def test_get_regulation_pages_success(tmp_path: Path) -> None:
    """GET /api/v1/regulations/{id}/pages returns stored pages for existing regulation."""
    db_path = _create_test_db(tmp_path)
    reg_id = _seed_regulation(db_path, with_pages=True)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.get(f"/api/v1/regulations/{reg_id}/pages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["regulation_id"] == reg_id
    assert len(data["pages"]) == 2
    assert data["pages"][0]["page_number"] == 1
    assert data["pages"][1]["extracted_text"] == "Page two text"


def test_get_regulation_pages_existing_regulation_with_no_pages(tmp_path: Path) -> None:
    """Existing regulation with zero pages should return an empty list, not 404."""
    db_path = _create_test_db(tmp_path)
    reg_id = _seed_regulation(db_path, with_pages=False)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.get(f"/api/v1/regulations/{reg_id}/pages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["regulation_id"] == reg_id
    assert data["pages"] == []


def test_get_regulation_pages_missing_regulation_returns_404(tmp_path: Path) -> None:
    """GET /api/v1/regulations/{id}/pages returns 404 when regulation does not exist."""
    db_path = _create_test_db(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.get("/api/v1/regulations/9999/pages")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Regulation not found"


def test_cohort_applicable_regulations_filters_and_excludes_pending(tmp_path: Path) -> None:
    """Student-facing cohort endpoint returns only approved regulations matching cohort."""
    db_path = _create_test_db(tmp_path)

    approved_match = _seed_regulation(
        db_path,
        document_name="Approved Match",
        regulation_version="v1",
        applicable_batches=["2024"],
        applicable_programmes=["BSc CS"],
        verification_status="approved",
        with_pages=False,
    )
    pending_match = _seed_regulation(
        db_path,
        document_name="Pending Match",
        regulation_version="v2",
        applicable_batches=["2024"],
        applicable_programmes=["BSc CS"],
        verification_status="pending",
        with_pages=False,
    )
    approved_other_batch = _seed_regulation(
        db_path,
        document_name="Approved Other Batch",
        regulation_version="v3",
        applicable_batches=["2023"],
        applicable_programmes=["BSc CS"],
        verification_status="approved",
        with_pages=False,
    )
    approved_other_programme = _seed_regulation(
        db_path,
        document_name="Approved Other Programme",
        regulation_version="v4",
        applicable_batches=["2024"],
        applicable_programmes=["BBA"],
        verification_status="approved",
        with_pages=False,
    )

    # Ensure statuses are as intended (ingest/store may vary; set explicitly for clarity)
    update_regulation_verification_status(approved_match, "approved", db_path=db_path)
    update_regulation_verification_status(pending_match, "pending", db_path=db_path)
    update_regulation_verification_status(approved_other_batch, "approved", db_path=db_path)
    update_regulation_verification_status(approved_other_programme, "approved", db_path=db_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.get("/api/v1/cohorts/2024/BSc%20CS/regulations")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    returned_ids = [reg["id"] for reg in data["regulations"]]
    assert returned_ids == [approved_match]
    assert pending_match not in returned_ids
    assert approved_other_batch not in returned_ids
    assert approved_other_programme not in returned_ids
    assert data["regulations"][0]["verification_status"] == "approved"
