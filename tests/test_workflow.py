"""Integration workflow tests for CohortIQ AI.

These tests exercise end-to-end workflow orchestration across extraction,
database storage, chunking, retrieval, Gemini answer generation (mocked), and
citation validation using temporary files/databases. No real Gemini API calls
are made.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import fitz  # PyMuPDF
import pytest

from app.database import get_applicable_regulations, get_regulation_by_id, init_database
from app.models import GroundedAnswer, GroundedCitation
from app.workflow import (
    answer_student_question,
    approve_regulation,
    build_retrieval_corpus_for_cohort,
    ingest_uploaded_regulation,
)


def _create_pdf(pdf_path: Path, page_texts: list[str]) -> Path:
    """Create a temporary PDF with one page per text entry."""
    document = fitz.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(pdf_path)
    finally:
        document.close()
    return pdf_path


def _metadata(**overrides: Any) -> dict[str, Any]:
    """Return valid administrator-provided regulation metadata."""
    metadata = {
        "document_name": "Academic Regulations 2024",
        "regulation_version": "v1",
        "effective_date": "2024-08-01",
        "applicable_batches": ["2024", "2025"],
        "applicable_programmes": ["BSc Computer Science", "BSc AI"],
        "upload_date": "2024-07-15",
    }
    metadata.update(overrides)
    return metadata


def _ingest_approved_regulation(
    tmp_path: Path,
    db_path: Path,
    *,
    pdf_name: str,
    page_texts: list[str],
    metadata_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper to ingest and explicitly approve a regulation for student-flow tests."""
    pdf_path = _create_pdf(tmp_path / pdf_name, page_texts)
    metadata = _metadata(**(metadata_overrides or {}))
    ingest_result = ingest_uploaded_regulation(pdf_path, metadata, db_path=db_path)
    assert ingest_result["status"] == "ingested"
    approval = approve_regulation(ingest_result["regulation_id"], db_path=db_path)
    assert approval["status"] == "updated"
    ingest_result["approval"] = approval
    return ingest_result


def test_successful_pdf_ingestion(tmp_path: Path) -> None:
    """Ingests a valid PDF and stores metadata/pages with structured result."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    pdf_path = _create_pdf(
        tmp_path / "regulation.pdf",
        ["Attendance requirement is 75 percent.", "Condonation requires approval."],
    )

    result = ingest_uploaded_regulation(pdf_path, _metadata(), db_path=db_path)

    assert result["status"] == "ingested"
    assert isinstance(result["regulation_id"], int)
    assert result["verification_status"] == "pending"
    assert result["extraction_summary"]["filename"] == "regulation.pdf"
    assert result["extraction_summary"]["total_pages"] == 2
    assert result["extraction_summary"]["successful_pages"] == 2

    regulation = get_regulation_by_id(result["regulation_id"], db_path=db_path)
    assert regulation is not None
    assert regulation["document_name"] == "Academic Regulations 2024"
    assert regulation["total_pages"] == 2


def test_ingested_regulation_starts_unverified(tmp_path: Path) -> None:
    """Stores newly ingested regulations as pending/unverified, never approved."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    pdf_path = _create_pdf(tmp_path / "regulation.pdf", ["Clause 1"])

    result = ingest_uploaded_regulation(
        pdf_path,
        _metadata(verification_status="approved"),  # caller cannot force approval
        db_path=db_path,
    )

    assert result["status"] == "ingested"
    regulation = get_regulation_by_id(result["regulation_id"], db_path=db_path)
    assert regulation is not None
    assert regulation["verification_status"] == "pending"
    assert get_applicable_regulations("2024", "BSc Computer Science", db_path=db_path) == []


def test_explicit_approval(tmp_path: Path) -> None:
    """Approves a regulation only through explicit approval workflow."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    pdf_path = _create_pdf(tmp_path / "regulation.pdf", ["Clause 1"])
    ingest_result = ingest_uploaded_regulation(pdf_path, _metadata(), db_path=db_path)

    approval = approve_regulation(ingest_result["regulation_id"], db_path=db_path)

    assert approval["status"] == "updated"
    assert approval["updated"] is True
    assert approval["verification_status"] == "approved"
    regulation = get_regulation_by_id(ingest_result["regulation_id"], db_path=db_path)
    assert regulation["verification_status"] == "approved"

    missing = approve_regulation(99999, db_path=db_path)
    assert missing["status"] == "not_found"
    assert missing["updated"] is False


def test_unapproved_documents_excluded_from_student_corpus(tmp_path: Path) -> None:
    """Excludes unapproved regulations from cohort retrieval corpus."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    pdf_path = _create_pdf(tmp_path / "regulation.pdf", ["Attendance is 75 percent."])
    ingest_uploaded_regulation(pdf_path, _metadata(), db_path=db_path)

    corpus = build_retrieval_corpus_for_cohort(
        "2024", "BSc Computer Science", db_path=db_path
    )

    assert corpus["status"] == "no_evidence"
    assert corpus["chunks"] == []


def test_correct_batch_and_programme_filtering(tmp_path: Path) -> None:
    """Builds corpus only for approved regulations matching batch and programme."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="match.pdf",
        page_texts=["Attendance requirement is 75 percent for eligible students."],
        metadata_overrides={
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc Computer Science"],
            "regulation_version": "v1",
        },
    )
    _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="other_batch.pdf",
        page_texts=["Attendance requirement is 60 percent for other cohort."],
        metadata_overrides={
            "applicable_batches": ["2023"],
            "applicable_programmes": ["BSc Computer Science"],
            "regulation_version": "v2",
        },
    )
    _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="other_programme.pdf",
        page_texts=["Attendance requirement is 80 percent for another programme."],
        metadata_overrides={
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc AI"],
            "regulation_version": "v3",
        },
    )

    corpus = build_retrieval_corpus_for_cohort(
        "2024", "BSc Computer Science", db_path=db_path
    )

    assert corpus["status"] == "ok"
    versions = {chunk.get("regulation_version") for chunk in corpus["chunks"]}
    assert versions == {"v1"}


def test_successful_student_question_workflow_and_page_citation_preservation(
    tmp_path: Path,
) -> None:
    """Runs end-to-end student QA and preserves page-level citation metadata."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    ingest_result = _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="attendance.pdf",
        page_texts=[
            "General policies.",
            "Clause 4.2.1: Minimum attendance requirement is 75 percent for examinations.",
        ],
        metadata_overrides={
            "document_name": "Attendance Regulations",
            "regulation_version": "2024.1",
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc Computer Science"],
        },
    )

    corpus = build_retrieval_corpus_for_cohort("2024", "BSc Computer Science", db_path=db_path)
    evidence_chunk = next(
        chunk
        for chunk in corpus["chunks"]
        if "75 percent" in str(chunk.get("chunk text") or chunk.get("chunk_text"))
    )

    mock_service = MagicMock()
    mock_service.generate_grounded_answer.return_value = GroundedAnswer(
        answer="Minimum attendance requirement is 75 percent for examinations.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="wrong",
                regulation_version="wrong",
                page_number=999,
                chunk_id=evidence_chunk["chunk_id"],
                relevant_supporting_text="Minimum attendance requirement is 75 percent",
            )
        ],
        limitations=None,
    )

    result = answer_student_question(
        admission_batch="2024",
        programme="BSc Computer Science",
        question="What is the minimum attendance requirement?",
        db_path=db_path,
        gemini_service=mock_service,
        top_k=3,
    )

    assert result["status"] == "answered"
    assert result["answer"]["answer"]
    assert len(result["citations"]) == 1
    citation = result["citations"][0]
    assert citation["document_name"] == "Attendance Regulations"
    assert citation["regulation_version"] == "2024.1"
    assert citation["page_number"] == 2
    assert citation["chunk_id"] == evidence_chunk["chunk_id"]
    assert "75 percent" in (citation["relevant_supporting_text"] or "")
    assert result["validation_issues"] == []
    mock_service.generate_grounded_answer.assert_called_once()
    assert result["retrieval"]["status"] == "ok"


def test_no_applicable_regulations_returns_clear_no_evidence(tmp_path: Path) -> None:
    """Returns a clear no-evidence result when no approved cohort regulations exist."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    mock_service = MagicMock()

    result = answer_student_question(
        admission_batch="2024",
        programme="BSc Computer Science",
        question="What is the attendance requirement?",
        db_path=db_path,
        gemini_service=mock_service,
    )

    assert result["status"] == "insufficient_evidence"
    assert result["retrieval"]["status"] == "no_evidence"
    assert "no approved regulations applicable" in result["retrieval"]["message"].lower()
    assert "no approved regulations applicable" in (result["answer"]["limitations"] or "").lower()
    assert result["citations"] == []
    mock_service.generate_grounded_answer.assert_not_called()


def test_gemini_not_called_when_retrieval_returns_no_evidence(tmp_path: Path) -> None:
    """Skips Gemini generation when retrieval cannot provide evidence."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    # Approved and cohort-matching, but empty extracted text means no retrievable chunks.
    _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="empty.pdf",
        page_texts=[""],
        metadata_overrides={
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc Computer Science"],
        },
    )
    mock_service = MagicMock()

    result = answer_student_question(
        admission_batch="2024",
        programme="BSc Computer Science",
        question="What is the attendance requirement?",
        db_path=db_path,
        gemini_service=mock_service,
    )

    assert result["retrieval"]["status"] == "no_evidence"
    assert result["status"] == "insufficient_evidence"
    mock_service.generate_grounded_answer.assert_not_called()


def test_multiple_approved_versions_are_preserved(tmp_path: Path) -> None:
    """Includes all relevant approved applicable versions without selecting newest."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="v1.pdf",
        page_texts=["Clause 7: Leave requires departmental approval."],
        metadata_overrides={
            "document_name": "Leave Regulations",
            "regulation_version": "2023",
            "effective_date": "2023-01-01",
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc Computer Science"],
        },
    )
    _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="v2.pdf",
        page_texts=["Clause 7: Leave requires departmental and dean approval."],
        metadata_overrides={
            "document_name": "Leave Regulations",
            "regulation_version": "2024",
            "effective_date": "2024-01-01",
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc Computer Science"],
        },
    )

    corpus = build_retrieval_corpus_for_cohort(
        "2024", "BSc Computer Science", db_path=db_path
    )

    assert corpus["status"] == "ok"
    versions = sorted({chunk.get("regulation_version") for chunk in corpus["chunks"]})
    assert versions == ["2023", "2024"]

    mock_service = MagicMock()
    mock_service.generate_grounded_answer.side_effect = AssertionError(
        "Gemini should not be called when retrieval result is forced to no_evidence in this setup"
    )
    # Direct retrieval over the built corpus preserves both versions as candidates.
    from app.retrieval import retrieve_relevant_chunks

    retrieval = retrieve_relevant_chunks(
        question="What approval is required for leave clause 7?",
        admission_batch="2024",
        programme="BSc Computer Science",
        chunks=corpus["chunks"],
        top_k=10,
    )
    assert retrieval["status"] == "ok"
    retrieved_versions = {item.get("regulation_version") for item in retrieval["results"]}
    assert retrieved_versions == {"2023", "2024"}


def test_invalid_citation_is_rejected_by_final_validation(tmp_path: Path) -> None:
    """Downgrades answers whose citations cannot be validated against evidence."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    _ingest_approved_regulation(
        tmp_path,
        db_path,
        pdf_name="attendance.pdf",
        page_texts=["Minimum attendance requirement is 75 percent."],
        metadata_overrides={
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc Computer Science"],
        },
    )
    mock_service = MagicMock()
    mock_service.generate_grounded_answer.return_value = GroundedAnswer(
        answer="Minimum attendance requirement is 75 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Academic Regulations 2024",
                regulation_version="v1",
                page_number=1,
                chunk_id="nonexistent-chunk",
                relevant_supporting_text="Minimum attendance requirement is 75 percent.",
            )
        ],
        limitations=None,
    )

    result = answer_student_question(
        admission_batch="2024",
        programme="BSc Computer Science",
        question="What is the attendance requirement?",
        db_path=db_path,
        gemini_service=mock_service,
    )

    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == []
    assert result["validation_issues"]
    assert any("unknown" in issue.lower() or "chunk_id" in issue.lower() for issue in result["validation_issues"])
    mock_service.generate_grounded_answer.assert_called_once()


def test_missing_or_invalid_metadata_handling(tmp_path: Path) -> None:
    """Rejects ingestion when required administrator metadata is missing/invalid."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)
    pdf_path = _create_pdf(tmp_path / "regulation.pdf", ["Clause 1"])

    missing_version = ingest_uploaded_regulation(
        pdf_path,
        _metadata(regulation_version=""),
        db_path=db_path,
    )
    assert missing_version["status"] == "error"
    assert "metadata" in missing_version["message"].lower()

    missing_batches = ingest_uploaded_regulation(
        pdf_path,
        _metadata(applicable_batches=[]),
        db_path=db_path,
    )
    assert missing_batches["status"] == "error"
    assert "metadata" in missing_batches["message"].lower()

    # Ensure no regulation records were stored for failed metadata validation.
    from app.database import get_all_regulations

    assert get_all_regulations(db_path=db_path) == []


def test_database_and_pdf_processing_errors_are_handled(tmp_path: Path) -> None:
    """Returns structured errors for PDF extraction and database failures."""
    db_path = tmp_path / "workflow.db"
    init_database(db_path)

    pdf_error = ingest_uploaded_regulation(
        tmp_path / "missing.pdf",
        _metadata(),
        db_path=db_path,
    )
    assert pdf_error["status"] == "error"
    assert pdf_error["regulation_id"] is None
    assert "pdf extraction failed" in pdf_error["message"].lower()

    # Corrupted PDF should be handled safely.
    corrupted_path = tmp_path / "corrupt.pdf"
    corrupted_path.write_bytes(b"not a real pdf")
    corrupted_result = ingest_uploaded_regulation(corrupted_path, _metadata(), db_path=db_path)
    assert corrupted_result["status"] == "error"
    assert "pdf extraction failed" in corrupted_result["message"].lower()

    # Database error (invalid path / directory as file on many systems) handled safely.
    invalid_db_path = tmp_path / "dbdir"
    invalid_db_path.mkdir()
    valid_pdf = _create_pdf(tmp_path / "valid.pdf", ["Clause 1"])
    db_error = ingest_uploaded_regulation(
        valid_pdf,
        _metadata(),
        db_path=invalid_db_path,  # directory path causes sqlite open/connect failure
    )
    assert db_error["status"] == "error"
    assert "failed to store regulation data" in db_error["message"].lower() or "database" in db_error["message"].lower() or db_error["regulation_id"] is None
