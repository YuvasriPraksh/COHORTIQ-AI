"""Tests for the citation validation module."""

from __future__ import annotations

from app.citation_validator import validate_grounded_answer
from app.models import GroundedAnswer, GroundedCitation


def _evidence() -> list[dict]:
    return [
        {
            "chunk_id": "chunk-1",
            "chunk_text": "Clause 4.2.1: Minimum attendance requirement is 75 percent for examinations.",
            "document_name": "Academic Regulations 2024",
            "regulation_version": "v1",
            "page_number": 12,
        },
        {
            "chunk_id": "chunk-2",
            "chunk_text": "Clause 4.2.2: Condonation may be granted in approved cases.",
            "document_name": "Academic Regulations 2024",
            "regulation_version": "v1",
            "page_number": 13,
        },
    ]


def test_valid_citations_are_preserved_and_restored_from_evidence() -> None:
    """Keeps valid citations and restores metadata from original evidence."""
    answer = GroundedAnswer(
        answer="Minimum attendance is 75 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name=None,  # missing metadata should be restored
                regulation_version=None,
                page_number=None,
                chunk_id="chunk-1",
                relevant_supporting_text="Minimum attendance requirement is 75 percent",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "answered"
    assert issues == []
    assert len(validated.citations) == 1
    citation = validated.citations[0]
    assert citation.chunk_id == "chunk-1"
    assert citation.document_name == "Academic Regulations 2024"
    assert citation.regulation_version == "v1"
    assert citation.page_number == 12
    assert "75 percent" in (citation.relevant_supporting_text or "")


def test_unknown_chunk_id_is_rejected_and_answer_downgraded() -> None:
    """Rejects citations referencing unknown chunk IDs."""
    answer = GroundedAnswer(
        answer="Attendance is 75 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Academic Regulations 2024",
                regulation_version="v1",
                page_number=12,
                chunk_id="unknown-chunk",
                relevant_supporting_text="Minimum attendance requirement is 75 percent",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "insufficient_evidence"
    assert validated.citations == []
    assert any("unknown chunk_id" in issue for issue in issues)
    assert validated.limitations


def test_incorrect_page_number_is_restored_from_evidence() -> None:
    """Restores correct page metadata from evidence instead of trusting the model."""
    answer = GroundedAnswer(
        answer="Attendance is 75 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Academic Regulations 2024",
                regulation_version="v1",
                page_number=99,  # untrusted model metadata
                chunk_id="chunk-1",
                relevant_supporting_text="Minimum attendance requirement is 75 percent",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "answered"
    assert issues == []
    assert len(validated.citations) == 1
    assert validated.citations[0].page_number == 12
    assert validated.citations[0].chunk_id == "chunk-1"


def test_incorrect_document_name_is_restored_from_evidence() -> None:
    """Restores correct document metadata from evidence instead of trusting the model."""
    answer = GroundedAnswer(
        answer="Attendance is 75 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Wrong Regulations",
                regulation_version="wrong-version",
                page_number=12,
                chunk_id="chunk-1",
                relevant_supporting_text="Minimum attendance requirement is 75 percent",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "answered"
    assert issues == []
    assert len(validated.citations) == 1
    citation = validated.citations[0]
    assert citation.document_name == "Academic Regulations 2024"
    assert citation.regulation_version == "v1"
    assert citation.page_number == 12


def test_fabricated_supporting_text_is_rejected() -> None:
    """Rejects citations whose supporting text cannot be matched to evidence."""
    answer = GroundedAnswer(
        answer="Attendance is 80 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Academic Regulations 2024",
                regulation_version="v1",
                page_number=12,
                chunk_id="chunk-1",
                relevant_supporting_text="Minimum attendance requirement is 80 percent for all courses.",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "insufficient_evidence"
    assert validated.citations == []
    assert any("supporting text could not be matched" in issue for issue in issues)


def test_duplicate_citations_are_removed() -> None:
    """Removes duplicate citations referencing the same evidence chunk."""
    citation = GroundedCitation(
        document_name="Academic Regulations 2024",
        regulation_version="v1",
        page_number=12,
        chunk_id="chunk-1",
        relevant_supporting_text="Minimum attendance requirement is 75 percent",
    )
    answer = GroundedAnswer(
        answer="Minimum attendance is 75 percent.",
        status="answered",
        citations=[citation, citation.model_copy(deep=True)],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "answered"
    assert len(validated.citations) == 1
    assert validated.citations[0].chunk_id == "chunk-1"
    assert any("duplicate citation" in issue.lower() for issue in issues)


def test_empty_evidence_downgrades_grounded_answer() -> None:
    """Rejects citations and downgrades when no original evidence is provided."""
    answer = GroundedAnswer(
        answer="Minimum attendance is 75 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Academic Regulations 2024",
                regulation_version="v1",
                page_number=12,
                chunk_id="chunk-1",
                relevant_supporting_text="Minimum attendance requirement is 75 percent",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, [])

    assert validated.status == "insufficient_evidence"
    assert validated.citations == []
    assert issues
    assert validated.limitations


def test_empty_citations_for_answered_response_are_downgraded() -> None:
    """Downgrades answered responses that have no supporting citations."""
    answer = GroundedAnswer(
        answer="Minimum attendance is 75 percent.",
        status="answered",
        citations=[],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "insufficient_evidence"
    assert validated.citations == []
    assert issues
    assert validated.limitations


def test_conflicting_evidence_with_valid_citations_is_preserved() -> None:
    """Preserves conflicting-evidence responses when citations are valid."""
    evidence = [
        {
            "chunk_id": "v1-c1",
            "chunk_text": "Clause 7: Leave requires departmental approval.",
            "document_name": "Regs 2023",
            "regulation_version": "v1",
            "page_number": 7,
        },
        {
            "chunk_id": "v2-c1",
            "chunk_text": "Clause 7: Leave requires departmental and dean approval.",
            "document_name": "Regs 2024",
            "regulation_version": "v2",
            "page_number": 9,
        },
    ]
    answer = GroundedAnswer(
        answer="The retrieved regulations conflict on approval requirements.",
        status="conflicting_evidence",
        citations=[
            GroundedCitation(chunk_id="v1-c1", relevant_supporting_text="requires departmental approval"),
            GroundedCitation(chunk_id="v2-c1", relevant_supporting_text="requires departmental and dean approval"),
        ],
        limitations="Conflicting versions were retrieved.",
    )

    validated, issues = validate_grounded_answer(answer, evidence)

    assert validated.status == "conflicting_evidence"
    assert [c.chunk_id for c in validated.citations] == ["v1-c1", "v2-c1"]
    assert validated.citations[0].document_name == "Regs 2023"
    assert validated.citations[1].regulation_version == "v2"
    assert issues == []


def test_insufficient_evidence_response_is_preserved() -> None:
    """Preserves insufficient-evidence responses without inventing citations."""
    answer = GroundedAnswer(
        answer="The retrieved evidence does not specify the maximum course load.",
        status="insufficient_evidence",
        citations=[],
        limitations="No relevant clause found in retrieved evidence.",
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "insufficient_evidence"
    assert validated.answer == answer.answer
    assert validated.citations == []
    assert issues == []
    assert validated.limitations == answer.limitations


def test_metadata_restoration_from_original_evidence() -> None:
    """Restores citation metadata from original evidence, not model output."""
    answer = GroundedAnswer(
        answer="Condonation may be granted in approved cases.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name=None,
                regulation_version=None,
                page_number=None,
                chunk_id="chunk-2",
                relevant_supporting_text="Condonation may be granted in approved cases",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, _evidence())

    assert validated.status == "answered"
    assert issues == []
    assert len(validated.citations) == 1
    citation = validated.citations[0]
    assert citation.document_name == "Academic Regulations 2024"
    assert citation.regulation_version == "v1"
    assert citation.page_number == 13
    assert citation.chunk_id == "chunk-2"
    assert citation.relevant_supporting_text


def test_malformed_citations_are_handled() -> None:
    """Rejects malformed citation entries and downgrades if none remain valid."""
    evidence = _evidence()[:1]
    # Build answer with a valid Pydantic citation list shape issue simulated via raw mapping handling
    # by using GroundedAnswer.model_construct-like scenario is unnecessary; include a citation object
    # missing chunk_id effectively (None) to represent malformed/incomplete citation.
    answer = GroundedAnswer(
        answer="Attendance is 75 percent.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name="Academic Regulations 2024",
                regulation_version="v1",
                page_number=12,
                chunk_id=None,
                relevant_supporting_text="Minimum attendance requirement is 75 percent",
            )
        ],
        limitations=None,
    )

    validated, issues = validate_grounded_answer(answer, evidence)

    assert validated.status == "insufficient_evidence"
    assert validated.citations == []
    assert any("missing chunk_id" in issue for issue in issues)
    assert validated.limitations
