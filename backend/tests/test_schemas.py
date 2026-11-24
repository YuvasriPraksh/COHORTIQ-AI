"""Tests for backend API schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import GroundedAnswer, GroundedCitation
from backend.app.schemas.common import ErrorResponse, StatusMessageResponse
from backend.app.schemas.query import (
    CohortInfo,
    GroundedAnswerResponse,
    InsufficientEvidenceResponse,
    RetrievalResponse,
    RetrievalResultItem,
    StudentQuestionRequest,
)
from backend.app.schemas.regulations import (
    DocumentPage,
    ExtractionSummary,
    ExtractionSummaryPage,
    RegulationDetailResponse,
    RegulationIngestionResult,
    RegulationListResponse,
    RegulationMetadata,
    RegulationRecord,
    VerificationUpdateRequest,
    VerificationUpdateResponse,
)


def test_student_question_request_valid_creation() -> None:
    """Valid student question requests should be created with existing field names."""
    request = StudentQuestionRequest(
        admission_batch="2024",
        programme="BSc Computer Science",
        question="What is the attendance requirement?",
        top_k=3,
        chunking_strategy="recursive",
        chunk_size=800,
        overlap=100,
    )

    assert request.admission_batch == "2024"
    assert request.programme == "BSc Computer Science"
    assert request.question == "What is the attendance requirement?"
    assert request.top_k == 3
    assert request.chunking_strategy == "recursive"


def test_cohort_info_and_request_missing_required_fields() -> None:
    """Missing required request fields should raise validation errors."""
    with pytest.raises(ValidationError):
        CohortInfo(admission_batch="2024")  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        StudentQuestionRequest(
            admission_batch="2024",
            programme="BSc Computer Science",
        )  # type: ignore[call-arg]


def test_regulation_metadata_missing_required_fields() -> None:
    """Regulation metadata should require core admin-provided fields."""
    with pytest.raises(ValidationError):
        RegulationMetadata(
            document_name="Regulation A",
            regulation_version="v1",
            effective_date="2025-01-01",
            applicable_batches=["2024"],
        )  # type: ignore[call-arg]


def test_grounded_citation_serialization() -> None:
    """Grounded citations should serialize with existing field names."""
    citation = GroundedCitation(
        document_name="Academic Regulations",
        regulation_version="2024",
        page_number=12,
        chunk_id="7-p12-c1",
        relevant_supporting_text="Students must maintain 75% attendance.",
    )

    assert citation.model_dump() == {
        "document_name": "Academic Regulations",
        "regulation_version": "2024",
        "page_number": 12,
        "chunk_id": "7-p12-c1",
        "relevant_supporting_text": "Students must maintain 75% attendance.",
    }


def test_grounded_answer_serialization() -> None:
    """Grounded answers should serialize with existing status and citation fields."""
    answer = GroundedAnswer(
        answer="Attendance requirement is 75%.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Academic Regulations",
                regulation_version="2024",
                page_number=12,
                chunk_id="7-p12-c1",
                relevant_supporting_text="Students must maintain 75% attendance.",
            )
        ],
        limitations=None,
    )

    data = answer.model_dump()
    assert data["status"] == "answered"
    assert data["answer"] == "Attendance requirement is 75%."
    assert data["limitations"] is None
    assert data["citations"][0]["chunk_id"] == "7-p12-c1"


def test_grounded_answer_response_and_insufficient_evidence_serialization() -> None:
    """Grounded answer response envelope should serialize insufficient-evidence results."""
    insufficient_answer = GroundedAnswer(
        answer="I cannot provide a grounded answer because no applicable approved regulation evidence was found for this cohort and question.",
        status="insufficient_evidence",
        citations=[],
        limitations="No approved regulations applicable to the supplied admission batch and programme were found.",
    )
    response = InsufficientEvidenceResponse(
        status="insufficient_evidence",
        answer=insufficient_answer,
        citations=[],
        validation_issues=[],
        retrieval=RetrievalResponse(
            status="no_evidence",
            message="No applicable approved regulations were found for the supplied admission batch and programme.",
            results=[],
        ),
        corpus={
            "status": "no_evidence",
            "message": "No approved regulations applicable to the supplied admission batch and programme were found.",
            "regulations": [],
            "chunks": [],
        },
    )

    assert isinstance(response, GroundedAnswerResponse)
    dumped = response.model_dump()
    assert dumped["status"] == "insufficient_evidence"
    assert dumped["answer"]["status"] == "insufficient_evidence"
    assert dumped["citations"] == []
    assert dumped["validation_issues"] == []
    assert dumped["retrieval"]["status"] == "no_evidence"
    assert dumped["retrieval"]["results"] == []
    # The workflow supplies its internal corpus, but the public envelope drops it.
    assert "corpus" not in dumped
    assert set(dumped) == {"status", "answer", "citations", "validation_issues", "retrieval"}


def test_regulation_response_serialization() -> None:
    """Regulation-related schemas should serialize existing database/workflow structures."""
    record = RegulationRecord(
        id=1,
        document_name="Academic Regulations",
        regulation_version="2024",
        effective_date="2024-08-01",
        applicable_batches=["2024"],
        applicable_programmes=["BSc Computer Science"],
        upload_date="2024-08-10",
        total_pages=20,
        processing_status="extracted",
        verification_status="approved",
    )
    page = DocumentPage(
        id=10,
        regulation_id=1,
        page_number=1,
        extracted_text="Sample text",
        extraction_status="success",
    )
    ingestion = RegulationIngestionResult(
        status="ingested",
        regulation_id=1,
        verification_status="pending",
        extraction_summary=ExtractionSummary(
            filename="regulations.pdf",
            total_pages=2,
            successful_pages=2,
            pages_needing_attention=0,
            pages=[
                ExtractionSummaryPage(page_number=1, status="success"),
                ExtractionSummaryPage(page_number=2, status="success"),
            ],
        ),
        message="Regulation ingested and stored as pending administrator verification.",
    )
    verification_request = VerificationUpdateRequest()
    verification_response = VerificationUpdateResponse(
        status="updated",
        regulation_id=1,
        updated=True,
        verification_status="approved",
        message="Regulation 1 verification status updated explicitly.",
    )

    list_response = RegulationListResponse(regulations=[record])
    detail_response = RegulationDetailResponse(regulation=record)

    assert list_response.model_dump()["regulations"][0]["applicable_batches"] == ["2024"]
    assert detail_response.model_dump()["regulation"]["id"] == 1
    assert page.model_dump()["extraction_status"] == "success"
    assert ingestion.model_dump()["status"] == "ingested"
    assert ingestion.model_dump()["extraction_summary"]["successful_pages"] == 2
    assert verification_request.verification_status == "approved"
    assert verification_response.model_dump()["updated"] is True


def test_common_status_and_error_responses() -> None:
    """Common response schemas should represent standard status/error payloads."""
    status_response = StatusMessageResponse(status="ok", message="Ready")
    error_response = ErrorResponse(message="Something went wrong")

    assert status_response.model_dump()["status"] == "ok"
    assert error_response.model_dump() == {
        "status": "error",
        "message": "Something went wrong",
        "details": None,
    }
