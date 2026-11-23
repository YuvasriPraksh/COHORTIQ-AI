"""Tests for the BM25 retrieval engine."""

from __future__ import annotations

from rank_bm25 import BM25Okapi

from app.retrieval import build_bm25_index, retrieve_relevant_chunks, tokenize_text


def _chunk(
    *,
    chunk_id: str,
    text: str,
    regulation_id: int,
    document_name: str,
    regulation_version: str,
    page_number: int,
    applicable_batches: list[str],
    applicable_programmes: list[str],
    verification_status: str = "approved",
    chunking_strategy: str = "recursive",
) -> dict:
    """Create a normalized chunk record for retrieval tests."""
    return {
        "chunk_id": chunk_id,
        "chunk_text": text,
        "regulation_id": regulation_id,
        "document_name": document_name,
        "regulation_version": regulation_version,
        "page_number": page_number,
        "applicable_batches": applicable_batches,
        "applicable_programmes": applicable_programmes,
        "chunking_strategy": chunking_strategy,
        "verification_status": verification_status,
    }


def test_tokenization_preserves_academic_terms_numbers_and_clause_refs() -> None:
    """Tokenizes text while preserving clause references and meaningful terms."""
    text = "Refer to Clause 4.2.1 and regulation 10(a) for 2024/25 CS-101 eligibility."

    tokens = tokenize_text(text)

    assert "clause" in tokens
    assert "4.2.1" in tokens
    assert "10(a)" in tokens or "10" in tokens  # clause-like references preserved
    assert "2024/25" in tokens
    assert "cs-101" in tokens
    assert "eligibility" in tokens
    # Punctuation normalized/split (no standalone punctuation tokens)
    assert "." not in tokens
    assert "," not in tokens


def test_build_bm25_index_creates_rank_bm25_index() -> None:
    """Builds an actual rank_bm25 index over normalized chunks."""
    chunks = [
        _chunk(
            chunk_id="1",
            text="Attendance requirement is seventy five percent.",
            regulation_id=1,
            document_name="Regs",
            regulation_version="v1",
            page_number=1,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        ),
        _chunk(
            chunk_id="2",
            text="Examination grading follows the university scale.",
            regulation_id=1,
            document_name="Regs",
            regulation_version="v1",
            page_number=2,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        ),
    ]

    index = build_bm25_index(chunks)

    assert index is not None
    assert isinstance(index["bm25"], BM25Okapi)
    assert len(index["chunks"]) == 2
    assert index["chunks"][0]["chunk_text"] == chunks[0]["chunk_text"]
    assert index["tokenized_corpus"][0] == tokenize_text(chunks[0]["chunk_text"])


def test_correct_ranking_of_relevant_chunks() -> None:
    """Ranks chunks most relevant to the question highest."""
    chunks = [
        _chunk(
            chunk_id="attendance",
            text="Minimum attendance requirement is 75 percent for examinations.",
            regulation_id=1,
            document_name="Attendance Policy",
            regulation_version="v1",
            page_number=3,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        ),
        _chunk(
            chunk_id="grading",
            text="Grading scale defines A, B, C, D and F grades.",
            regulation_id=1,
            document_name="Attendance Policy",
            regulation_version="v1",
            page_number=8,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        ),
        _chunk(
            chunk_id="library",
            text="Library borrowing limits and overdue fine rules are listed here.",
            regulation_id=1,
            document_name="Attendance Policy",
            regulation_version="v1",
            page_number=12,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        ),
    ]

    response = retrieve_relevant_chunks(
        question="What is the minimum attendance requirement for examinations?",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=3,
    )

    assert response["status"] == "ok"
    assert len(response["results"]) == 3
    assert response["results"][0]["chunk_id"] == "attendance"
    assert response["results"][0]["retrieval_score"] > response["results"][1]["retrieval_score"]
    assert "75 percent" in response["results"][0]["chunk_text"]


def test_admission_batch_filtering() -> None:
    """Considers only chunks whose applicability includes the admission batch."""
    chunks = [
        _chunk(
            chunk_id="batch-2024",
            text="Clause 2.1 attendance requirement for cohort.",
            regulation_id=1,
            document_name="Regs A",
            regulation_version="v1",
            page_number=2,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        ),
        _chunk(
            chunk_id="batch-2023",
            text="Clause 2.1 attendance requirement for cohort.",
            regulation_id=2,
            document_name="Regs B",
            regulation_version="v1",
            page_number=2,
            applicable_batches=["2023"],
            applicable_programmes=["BSc CS"],
        ),
    ]

    response = retrieve_relevant_chunks(
        question="Clause 2.1 attendance requirement",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=5,
    )

    assert response["status"] == "ok"
    assert [r["chunk_id"] for r in response["results"]] == ["batch-2024"]
    assert all(r["admission_batch"] == "2024" for r in response["results"])


def test_programme_filtering() -> None:
    """Considers only chunks whose applicability includes the programme."""
    chunks = [
        _chunk(
            chunk_id="cs",
            text="Internship credits required for completion.",
            regulation_id=1,
            document_name="CS Regs",
            regulation_version="v1",
            page_number=5,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        ),
        _chunk(
            chunk_id="ai",
            text="Internship credits required for completion.",
            regulation_id=2,
            document_name="AI Regs",
            regulation_version="v1",
            page_number=5,
            applicable_batches=["2024"],
            applicable_programmes=["BSc AI"],
        ),
    ]

    response = retrieve_relevant_chunks(
        question="How many internship credits are required?",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=5,
    )

    assert response["status"] == "ok"
    assert [r["chunk_id"] for r in response["results"]] == ["cs"]
    assert all(r["programme"] == "BSc CS" for r in response["results"])


def test_exclusion_of_unverified_documents() -> None:
    """Excludes chunks from unverified or non-approved regulations."""
    chunks = [
        _chunk(
            chunk_id="approved",
            text="Clause 5 attendance appeal process is defined here.",
            regulation_id=1,
            document_name="Approved Regs",
            regulation_version="v1",
            page_number=4,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
            verification_status="approved",
        ),
        _chunk(
            chunk_id="unverified",
            text="Clause 5 attendance appeal process is defined here.",
            regulation_id=2,
            document_name="Draft Regs",
            regulation_version="v1",
            page_number=4,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
            verification_status="pending",
        ),
        _chunk(
            chunk_id="none-status",
            text="Clause 5 attendance appeal process is defined here.",
            regulation_id=3,
            document_name="Unknown Regs",
            regulation_version="v1",
            page_number=4,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
            verification_status="unverified",
        ),
    ]

    response = retrieve_relevant_chunks(
        question="Clause 5 attendance appeal process",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=5,
    )

    assert response["status"] == "ok"
    assert [r["chunk_id"] for r in response["results"]] == ["approved"]


def test_page_number_preservation_in_results() -> None:
    """Preserves source document, regulation version, and page number in results."""
    chunk = _chunk(
        chunk_id="p12",
        text="Clause 9.3: Maximum course load is 24 credits per semester.",
        regulation_id=10,
        document_name="Academic Regulations 2024",
        regulation_version="2024.1",
        page_number=12,
        applicable_batches=["2024"],
        applicable_programmes=["BSc CS"],
        verification_status="verified",
    )

    response = retrieve_relevant_chunks(
        question="What is the maximum course load in clause 9.3?",
        admission_batch="2024",
        programme="BSc CS",
        chunks=[chunk],
        top_k=3,
    )

    assert response["status"] == "ok"
    result = response["results"][0]
    assert result["page_number"] == 12
    assert result["document_name"] == "Academic Regulations 2024"
    assert result["regulation_version"] == "2024.1"
    assert result["regulation_id"] == 10
    assert result["chunk_id"] == "p12"
    assert result["chunk_text"] == chunk["chunk_text"]
    assert "retrieval_score" in result
    assert isinstance(result["retrieval_score"], float)


def test_empty_query_handling_returns_no_evidence() -> None:
    """Returns a clear no-evidence result for empty questions."""
    chunks = [
        _chunk(
            chunk_id="c1",
            text="Some regulation text.",
            regulation_id=1,
            document_name="Regs",
            regulation_version="v1",
            page_number=1,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        )
    ]

    response = retrieve_relevant_chunks(
        question="   ",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=5,
    )

    assert response["status"] == "no_evidence"
    assert response["results"] == []
    assert "empty" in response["message"].lower() or "no evidence" in response["message"].lower()


def test_no_applicable_regulation_handling() -> None:
    """Returns a clear no-evidence result when no approved cohort match exists."""
    chunks = [
        _chunk(
            chunk_id="wrong-cohort",
            text="Attendance policy text.",
            regulation_id=1,
            document_name="Regs",
            regulation_version="v1",
            page_number=1,
            applicable_batches=["2023"],
            applicable_programmes=["BSc AI"],
            verification_status="approved",
        )
    ]

    response = retrieve_relevant_chunks(
        question="attendance policy",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=5,
    )

    assert response["status"] == "no_evidence"
    assert response["results"] == []
    assert "no applicable approved" in response["message"].lower()


def test_multiple_matching_regulation_versions_return_all_candidates() -> None:
    """Returns relevant candidates from multiple approved matching versions."""
    chunks = [
        _chunk(
            chunk_id="v1-c1",
            text="Clause 7 leave of absence requires departmental approval.",
            regulation_id=1,
            document_name="Regs 2023",
            regulation_version="v1",
            page_number=7,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
            verification_status="approved",
        ),
        _chunk(
            chunk_id="v2-c1",
            text="Clause 7 leave of absence requires departmental and dean approval.",
            regulation_id=2,
            document_name="Regs 2024",
            regulation_version="v2",
            page_number=9,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
            verification_status="verified",
        ),
        _chunk(
            chunk_id="v2-other",
            text="Library fines policy.",
            regulation_id=2,
            document_name="Regs 2024",
            regulation_version="v2",
            page_number=20,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
            verification_status="verified",
        ),
    ]

    response = retrieve_relevant_chunks(
        question="What does clause 7 say about leave of absence approval?",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=5,
    )

    assert response["status"] == "ok"
    result_ids = [r["chunk_id"] for r in response["results"]]
    versions = {r["regulation_version"] for r in response["results"]}
    # Relevant chunks from both approved matching versions are returned (no latest-only selection).
    assert "v1-c1" in result_ids
    assert "v2-c1" in result_ids
    assert versions == {"v1", "v2"} or {"v1", "v2"}.issubset(versions)
    assert all(r["page_number"] in {7, 9} for r in response["results"] if r["chunk_id"] in {"v1-c1", "v2-c1"})


def test_empty_chunk_collection_returns_no_evidence() -> None:
    """Returns a clear no-evidence result when no chunks are available."""
    response = retrieve_relevant_chunks(
        question="attendance policy",
        admission_batch="2024",
        programme="BSc CS",
        chunks=[],
        top_k=5,
    )

    assert response["status"] == "no_evidence"
    assert response["results"] == []
    assert "no document chunks" in response["message"].lower()


def test_documents_with_empty_text_are_ignored() -> None:
    """Ignores chunks/pages with empty text during indexing and retrieval."""
    chunks = [
        _chunk(
            chunk_id="empty",
            text="   ",
            regulation_id=1,
            document_name="Regs",
            regulation_version="v1",
            page_number=1,
            applicable_batches=["2024"],
            applicable_programmes=["BSc CS"],
        )
    ]

    response = retrieve_relevant_chunks(
        question="attendance policy",
        admission_batch="2024",
        programme="BSc CS",
        chunks=chunks,
        top_k=5,
    )

    assert response["status"] == "no_evidence"
    assert response["results"] == []
