"""Tests for the student question-and-answer FastAPI endpoint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import workflow
from app.database import init_database, insert_document_pages, insert_regulation
from app.models import GroundedAnswer, GroundedCitation
from backend.app.api.v1.query import get_db_path
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
    """Create an isolated SQLite database for query API tests."""
    db_path = tmp_path / "test_query_api.db"
    init_database(db_path)
    return db_path


def _seed_regulation(
    db_path: Path,
    *,
    document_name: str,
    regulation_version: str,
    effective_date: str,
    applicable_batches: list[str],
    applicable_programmes: list[str],
    verification_status: str | None,
    page_text: str,
) -> int:
    """Insert a regulation with one extracted page into the isolated test database."""
    regulation_id = insert_regulation(
        {
            "document_name": document_name,
            "regulation_version": regulation_version,
            "effective_date": effective_date,
            "applicable_batches": applicable_batches,
            "applicable_programmes": applicable_programmes,
            "upload_date": "2024-02-01",
            "total_pages": 1,
            "processing_status": "extracted",
            "verification_status": verification_status,
        },
        db_path=db_path,
    )
    insert_document_pages(
        regulation_id,
        [
            {
                "page_number": 1,
                "extracted_text": page_text,
                "extraction_status": "success",
            }
        ],
        db_path=db_path,
    )
    return regulation_id


def _mock_grounded_answer_from_evidence(**kwargs: Any) -> GroundedAnswer:
    """Build a valid grounded answer using the retrieved evidence passed to Gemini."""
    evidence_chunks = kwargs.get("evidence_chunks") or []
    first = dict(evidence_chunks[0])
    chunk_text = str(first.get("chunk_text") or first.get("chunk text") or "")
    supporting_text = chunk_text[:120].strip() or "Attendance requirement"
    return GroundedAnswer(
        answer="According to the approved regulation, students must maintain the required attendance.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name=first.get("document_name"),
                regulation_version=first.get("regulation_version"),
                page_number=first.get("page_number"),
                chunk_id=str(first.get("chunk_id")) if first.get("chunk_id") is not None else None,
                relevant_supporting_text=supporting_text,
            )
        ],
        limitations=None,
    )


def test_successful_question_answer_request(tmp_path: Path, monkeypatch) -> None:
    """POST /api/v1/query/ask returns a grounded answer with preserved citations."""
    db_path = _create_test_db(tmp_path)
    _seed_regulation(
        db_path,
        document_name="Attendance Rules",
        regulation_version="2024",
        effective_date="2024-08-01",
        applicable_batches=["2024"],
        applicable_programmes=["BSc CS"],
        verification_status="approved",
        page_text="Students must maintain at least 75 percent attendance in each course to be eligible.",
    )

    monkeypatch.setattr(
        "app.workflow.generate_grounded_answer",
        _mock_grounded_answer_from_evidence,
    )

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/query/ask",
            json={
                "question": "What is the attendance requirement?",
                "admission_batch": "2024",
                "programme": "BSc CS",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert data["answer"]["status"] == "answered"
    assert "attendance" in data["answer"]["answer"].lower()
    assert len(data["citations"]) == 1
    assert data["citations"][0]["document_name"] == "Attendance Rules"
    assert data["citations"][0]["regulation_version"] == "2024"
    assert data["citations"][0]["page_number"] == 1
    assert data["validation_issues"] == []
    assert data["retrieval"]["status"] == "ok"
    assert len(data["retrieval"]["results"]) >= 1


def test_correct_admission_batch_and_programme_forwarding(tmp_path: Path, monkeypatch) -> None:
    """Endpoint should forward cohort identifiers and question to the query service."""
    db_path = _create_test_db(tmp_path)
    calls: dict[str, Any] = {}

    def fake_answer_student_regulation_question(**kwargs: Any) -> dict[str, Any]:
        calls.update(kwargs)
        return {
            "status": "insufficient_evidence",
            "answer": {
                "answer": "No evidence.",
                "status": "insufficient_evidence",
                "citations": [],
                "limitations": "No evidence.",
            },
            "citations": [],
            "validation_issues": [],
            "retrieval": {"status": "no_evidence", "message": "No evidence.", "results": []},
            "corpus": {"status": "no_evidence", "message": "No evidence.", "regulations": [], "chunks": []},
        }

    monkeypatch.setattr(
        "backend.app.services.query_service.answer_student_regulation_question",
        fake_answer_student_regulation_question,
    )

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/query/ask",
            json={
                "question": "  What is the rule?  ",
                "admission_batch": " 2025 ",
                "programme": " BSc AI ",
                "top_k": 3,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls["question"] == "What is the rule?"
    assert calls["admission_batch"] == "2025"
    assert calls["programme"] == "BSc AI"
    assert calls["db_path"] == str(db_path)
    assert calls["top_k"] == 3


def test_approved_only_evidence_behavior(tmp_path: Path, monkeypatch) -> None:
    """Only approved, cohort-applicable regulations should be used as evidence."""
    db_path = _create_test_db(tmp_path)
    _seed_regulation(
        db_path,
        document_name="Pending Regulation",
        regulation_version="v1",
        effective_date="2024-01-01",
        applicable_batches=["2024"],
        applicable_programmes=["BSc CS"],
        verification_status="pending",
        page_text="Pending rule says attendance is 60 percent.",
    )
    _seed_regulation(
        db_path,
        document_name="Approved Regulation",
        regulation_version="v2",
        effective_date="2024-06-01",
        applicable_batches=["2024"],
        applicable_programmes=["BSc CS"],
        verification_status="approved",
        page_text="Approved rule says attendance is 75 percent for all courses.",
    )
    _seed_regulation(
        db_path,
        document_name="Other Cohort Approved",
        regulation_version="v3",
        effective_date="2024-06-01",
        applicable_batches=["2023"],
        applicable_programmes=["BSc IT"],
        verification_status="approved",
        page_text="Other cohort rule says attendance is 80 percent.",
    )

    captured_evidence: dict[str, Any] = {}

    def capture_and_answer(**kwargs: Any) -> GroundedAnswer:
        captured_evidence["chunks"] = kwargs.get("evidence_chunks") or []
        return _mock_grounded_answer_from_evidence(**kwargs)

    monkeypatch.setattr("app.workflow.generate_grounded_answer", capture_and_answer)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/query/ask",
            json={
                "question": "What is the attendance percentage?",
                "admission_batch": "2024",
                "programme": "BSc CS",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    evidence_chunks = captured_evidence["chunks"]
    assert evidence_chunks
    doc_names = {chunk.get("document_name") for chunk in evidence_chunks}
    assert doc_names == {"Approved Regulation"}
    retrieval_names = {item.get("document_name") for item in data["retrieval"]["results"]}
    assert retrieval_names == {"Approved Regulation"}

    # The internal retrieval corpus is not part of the public API response ...
    assert "corpus" not in data
    # ... and the corpus the pipeline builds internally still contains only the
    # approved, cohort-applicable regulation.
    internal = workflow.answer_student_question(
        admission_batch="2024",
        programme="BSc CS",
        question="What is the attendance percentage?",
        db_path=db_path,
    )
    corpus_regulations = internal["corpus"]["regulations"]
    assert [reg.get("document_name") for reg in corpus_regulations] == ["Approved Regulation"]
    assert all(reg.get("verification_status") == "approved" for reg in corpus_regulations)


def test_insufficient_evidence_response_when_no_approved_evidence(tmp_path: Path, monkeypatch) -> None:
    """Endpoint should return a safe insufficient-evidence response without Gemini generation."""
    db_path = _create_test_db(tmp_path)
    _seed_regulation(
        db_path,
        document_name="Pending Only",
        regulation_version="v1",
        effective_date="2024-01-01",
        applicable_batches=["2024"],
        applicable_programmes=["BSc CS"],
        verification_status="pending",
        page_text="Pending rule text.",
    )

    def fail_if_called(**kwargs: Any) -> GroundedAnswer:  # pragma: no cover - safety assertion
        raise AssertionError("Gemini generation must not be called when no approved evidence exists.")

    monkeypatch.setattr("app.workflow.generate_grounded_answer", fail_if_called)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/query/ask",
            json={
                "question": "What is the attendance rule?",
                "admission_batch": "2024",
                "programme": "BSc CS",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "insufficient_evidence"
    assert data["answer"]["status"] == "insufficient_evidence"
    assert data["citations"] == []
    assert data["retrieval"]["status"] == "no_evidence"
    assert data["retrieval"]["results"] == []


def test_citation_information_preserved(tmp_path: Path, monkeypatch) -> None:
    """Citation fields from validated grounded answers should be preserved in the response."""
    db_path = _create_test_db(tmp_path)
    _seed_regulation(
        db_path,
        document_name="Exam Policy",
        regulation_version="2023-R1",
        effective_date="2023-07-01",
        applicable_batches=["2023"],
        applicable_programmes=["BEng"],
        verification_status="approved",
        page_text="Students must score at least 40 marks in the final examination to pass.",
    )

    monkeypatch.setattr(
        "app.workflow.generate_grounded_answer",
        _mock_grounded_answer_from_evidence,
    )

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/query/ask",
            json={
                "question": "What is the passing mark?",
                "admission_batch": "2023",
                "programme": "BEng",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    citation = response.json()["citations"][0]
    assert citation["document_name"] == "Exam Policy"
    assert citation["regulation_version"] == "2023-R1"
    assert citation["page_number"] == 1
    assert citation["chunk_id"] is not None
    assert "40" in (citation["relevant_supporting_text"] or "")


def test_invalid_or_empty_question_validation(tmp_path: Path) -> None:
    """Empty/invalid questions should be rejected by request validation."""
    db_path = _create_test_db(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        empty_response = client.post(
            "/api/v1/query/ask",
            json={"question": "   ", "admission_batch": "2024", "programme": "BSc CS"},
        )
        missing_response = client.post(
            "/api/v1/query/ask",
            json={"admission_batch": "2024", "programme": "BSc CS"},
        )
    finally:
        app.dependency_overrides.clear()

    assert empty_response.status_code == 400
    assert empty_response.json()["detail"] == "question, admission_batch, and programme are required."
    assert missing_response.status_code == 422


def test_existing_api_endpoints_remain_functional(tmp_path: Path) -> None:
    """Adding the query endpoint must not break existing API endpoints."""
    db_path = _create_test_db(tmp_path)

    app.dependency_overrides[get_db_path] = lambda: str(db_path)
    try:
        client = TestClient(app)
        health_response = client.get("/api/v1/health")
        regulations_response = client.get("/api/v1/regulations")
    finally:
        app.dependency_overrides.clear()

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert regulations_response.status_code == 200
    assert "regulations" in regulations_response.json()
