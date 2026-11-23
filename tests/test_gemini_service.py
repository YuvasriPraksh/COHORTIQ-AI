"""Tests for the Gemini-powered grounded answer service."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from app.config import Settings
from app.gemini_service import GeminiAnswerService, generate_grounded_answer


def _settings(api_key: str | None = "test-api-key", model: str = "gemini-2.5-flash") -> Settings:
    return Settings(
        gemini_api_key=api_key,
        gemini_model=model,
        database_path=Settings().database_path,
        upload_dir=Settings().upload_dir,
        extracted_dir=Settings().extracted_dir,
    )


def _evidence() -> list[dict]:
    return [
        {
            "chunk_id": "chunk-1",
            "chunk_text": "Clause 4.2.1: Minimum attendance requirement is 75 percent for examinations.",
            "regulation_id": 10,
            "document_name": "Academic Regulations 2024",
            "regulation_version": "v1",
            "page_number": 12,
            "applicable_batches": ["2024"],
            "applicable_programmes": ["BSc CS"],
            "verification_status": "approved",
        }
    ]


def _mock_response(text: str):
    return SimpleNamespace(text=text)


def test_client_initialization_uses_configured_api_key() -> None:
    """Initializes Gemini client securely using environment-backed settings."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_response(
        json.dumps(
            {
                "answer": "Minimum attendance is 75 percent.",
                "status": "answered",
                "citations": [
                    {
                        "document_name": "Academic Regulations 2024",
                        "regulation_version": "v1",
                        "page_number": 12,
                        "chunk_id": "chunk-1",
                        "relevant_supporting_text": "Minimum attendance requirement is 75 percent",
                    }
                ],
                "limitations": None,
            }
        )
    )

    with patch("app.gemini_service.genai.Client", return_value=mock_client) as client_ctor:
        service = GeminiAnswerService(settings=_settings(api_key="test-key-123"))
        result = service.generate_grounded_answer(
            question="What is the minimum attendance?",
            admission_batch="2024",
            programme="BSc CS",
            evidence_chunks=_evidence(),
        )

    client_ctor.assert_called_once_with(api_key="test-key-123")
    assert result.status == "answered"
    mock_client.models.generate_content.assert_called_once()


def test_missing_api_key_raises_clear_error() -> None:
    """Raises a clear configuration error when GEMINI_API_KEY is missing."""
    service = GeminiAnswerService(settings=_settings(api_key=None))

    with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
        service.generate_grounded_answer(
            question="What is the attendance requirement?",
            admission_batch="2024",
            programme="BSc CS",
            evidence_chunks=_evidence(),
        )


def test_successful_grounded_response_with_citations() -> None:
    """Returns a structured grounded answer with citations from evidence."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_response(
        json.dumps(
            {
                "answer": "According to the provided regulation, minimum attendance is 75 percent for examinations.",
                "status": "answered",
                "citations": [
                    {
                        "document_name": "Academic Regulations 2024",
                        "regulation_version": "v1",
                        "page_number": 12,
                        "chunk_id": "chunk-1",
                        "relevant_supporting_text": "Minimum attendance requirement is 75 percent for examinations.",
                    }
                ],
                "limitations": None,
            }
        )
    )

    result = generate_grounded_answer(
        question="What is the minimum attendance?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=_evidence(),
        settings=_settings(),
        client=mock_client,
    )

    assert result.answer
    assert result.status == "answered"
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == "chunk-1"
    assert result.citations[0].document_name == "Academic Regulations 2024"
    assert result.citations[0].regulation_version == "v1"
    assert result.citations[0].page_number == 12
    assert "75 percent" in (result.citations[0].relevant_supporting_text or "")


def test_empty_question_returns_insufficient_evidence_without_api_call() -> None:
    """Handles empty questions safely without calling Gemini."""
    mock_client = MagicMock()

    result = generate_grounded_answer(
        question="   ",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=_evidence(),
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert "question" in result.answer.lower() or "empty" in result.answer.lower()
    mock_client.models.generate_content.assert_not_called()


def test_empty_evidence_returns_insufficient_evidence_without_api_call() -> None:
    """Handles empty retrieved evidence without inventing an answer."""
    mock_client = MagicMock()

    result = generate_grounded_answer(
        question="What is the attendance policy?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=[],
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert "evidence" in result.answer.lower() or "cannot" in result.answer.lower()
    mock_client.models.generate_content.assert_not_called()


def test_insufficient_evidence_status_from_model() -> None:
    """Preserves model-indicated insufficient evidence when grounded in provided evidence."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_response(
        json.dumps(
            {
                "answer": "The provided evidence does not specify the maximum course load.",
                "status": "insufficient_evidence",
                "citations": [],
                "limitations": "No clause about maximum course load was found in the retrieved evidence.",
            }
        )
    )

    result = generate_grounded_answer(
        question="What is the maximum course load?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=_evidence(),
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "insufficient_evidence"
    assert "insufficient" in result.answer.lower() or "does not specify" in result.answer.lower()
    assert result.limitations


def test_conflicting_evidence_status_and_citations_preserved() -> None:
    """Returns conflicting evidence when the model identifies source conflicts."""
    evidence = [
        {
            "chunk_id": "v1-c1",
            "chunk_text": "Clause 7: Leave of absence requires departmental approval.",
            "document_name": "Regs 2023",
            "regulation_version": "v1",
            "page_number": 7,
        },
        {
            "chunk_id": "v2-c1",
            "chunk_text": "Clause 7: Leave of absence requires departmental and dean approval.",
            "document_name": "Regs 2024",
            "regulation_version": "v2",
            "page_number": 9,
        },
    ]
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_response(
        json.dumps(
            {
                "answer": "The retrieved evidence conflicts: Regs 2023 v1 (p.7) requires departmental approval, while Regs 2024 v2 (p.9) requires departmental and dean approval.",
                "status": "conflicting_evidence",
                "citations": [
                    {"document_name": "Regs 2023", "regulation_version": "v1", "page_number": 7, "chunk_id": "v1-c1", "relevant_supporting_text": "requires departmental approval"},
                    {"document_name": "Regs 2024", "regulation_version": "v2", "page_number": 9, "chunk_id": "v2-c1", "relevant_supporting_text": "requires departmental and dean approval"},
                ],
                "limitations": "Conflicting versions were retrieved; applicability must not be decided automatically.",
            }
        )
    )

    result = generate_grounded_answer(
        question="Who must approve leave of absence?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=evidence,
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "conflicting_evidence"
    assert len(result.citations) == 2
    assert {c.chunk_id for c in result.citations} == {"v1-c1", "v2-c1"}
    assert "conflict" in result.answer.lower() or "conflict" in (result.limitations or "").lower()


def test_citation_preservation_uses_evidence_metadata() -> None:
    """Normalizes citations to preserve source metadata from supplied evidence."""
    mock_client = MagicMock()
    # Model returns correct chunk_id but incorrect metadata/supporting text.
    mock_client.models.generate_content.return_value = _mock_response(
        json.dumps(
            {
                "answer": "Minimum attendance is 75 percent.",
                "status": "answered",
                "citations": [
                    {
                        "document_name": "Wrong Name",
                        "regulation_version": "wrong",
                        "page_number": 999,
                        "chunk_id": "chunk-1",
                        "relevant_supporting_text": "fabricated text not in evidence",
                    }
                ],
                "limitations": None,
            }
        )
    )

    result = generate_grounded_answer(
        question="What is the minimum attendance?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=_evidence(),
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "answered"
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.chunk_id == "chunk-1"
    assert citation.document_name == "Academic Regulations 2024"
    assert citation.regulation_version == "v1"
    assert citation.page_number == 12
    assert citation.relevant_supporting_text
    # Supporting text must come from evidence, not fabricated model text.
    assert "fabricated text not in evidence" not in (citation.relevant_supporting_text or "")
    assert "attendance" in (citation.relevant_supporting_text or "").lower()


def test_invalid_model_response_handled_safely() -> None:
    """Does not invent answers when model output is invalid or malformed."""
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_response("not-json-at-all")

    result = generate_grounded_answer(
        question="What is the attendance requirement?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=_evidence(),
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert "cannot provide a grounded answer" in result.answer.lower() or "invalid" in (result.limitations or "").lower()
    assert result.limitations


def test_gemini_api_error_handling_rate_limit() -> None:
    """Handles Gemini API/rate-limit errors without inventing answers."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = genai_errors.APIError(
        429, {"error": {"message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}}
    )

    result = generate_grounded_answer(
        question="What is the attendance requirement?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=_evidence(),
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert "cannot provide a grounded answer" in result.answer.lower()
    assert result.limitations
    assert "rate" in result.limitations.lower() or "quota" in result.limitations.lower() or "temporar" in result.limitations.lower()


def test_gemini_temporary_service_error_handling() -> None:
    """Handles temporary/unexpected Gemini service failures safely."""
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("service unavailable")

    result = generate_grounded_answer(
        question="What is the attendance requirement?",
        admission_batch="2024",
        programme="BSc CS",
        evidence_chunks=_evidence(),
        settings=_settings(),
        client=mock_client,
    )

    assert result.status == "insufficient_evidence"
    assert result.citations == []
    assert "cannot provide a grounded answer" in result.answer.lower()
    assert result.limitations
