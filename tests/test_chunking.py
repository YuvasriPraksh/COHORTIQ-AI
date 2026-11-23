"""Tests for the document chunking engine."""

from __future__ import annotations

from app.chunking import (
    create_chunks,
    fixed_size_chunking,
    recursive_chunking,
    semantic_chunking,
)


def test_fixed_size_splitting() -> None:
    """Splits text into fixed-size character chunks."""
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26 chars

    chunks = fixed_size_chunking(text, chunk_size=10, overlap=0)

    assert chunks == ["ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ"]
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_fixed_size_overlap_behaviour() -> None:
    """Applies configured overlap between consecutive fixed-size chunks."""
    text = "abcdefghij"  # 10 chars

    chunks = fixed_size_chunking(text, chunk_size=6, overlap=2)

    # Step = 4: "abcdef", "efghij"
    assert chunks == ["abcdef", "efghij"]
    assert chunks[0][-2:] == "ef"
    assert chunks[1][:2] == "ef"


def test_recursive_chunking_prefers_paragraph_boundaries() -> None:
    """Prefers paragraph boundaries before falling back to smaller splits."""
    para1 = "Paragraph one keeps its meaning."
    para2 = "Paragraph two stays separate."
    text = f"{para1}\n\n{para2}"
    chunk_size = max(len(para1 + "\n\n"), len(para2))

    chunks = recursive_chunking(text, chunk_size=chunk_size, overlap=0)

    assert len(chunks) == 2
    assert chunks[0].startswith("Paragraph one")
    assert "Paragraph two" not in chunks[0]
    assert "Paragraph two" in chunks[1]
    assert "\n\n" in "".join(chunks) or chunks[0].endswith("\n\n")


def test_semantic_chunking_sentence_grouping() -> None:
    """Groups consecutive sentences using lightweight textual similarity."""
    similar_topic = (
        "Students must submit the exam form before the deadline. "
        "The exam form submission deadline is strict for all students."
    )
    different_topic = "Library opening hours are posted on the notice board."
    text = f"{similar_topic} {different_topic}"

    chunks = semantic_chunking(text, chunk_size=300, overlap=0)

    assert len(chunks) >= 2
    assert "exam form" in chunks[0]
    assert "deadline" in chunks[0]
    assert any("Library opening hours" in chunk for chunk in chunks)
    # Sentence grouping should keep sentence text intact (not character-sliced mid-word by default).
    assert "deadline." in chunks[0] or "students." in chunks[0]


def test_empty_text_handling() -> None:
    """Handles empty or whitespace-only text safely without producing chunks."""
    assert fixed_size_chunking("", chunk_size=50, overlap=10) == []
    assert fixed_size_chunking("   \n\t  ", chunk_size=50, overlap=10) == []
    assert recursive_chunking("", chunk_size=50, overlap=10) == []
    assert recursive_chunking(" \n ", chunk_size=50, overlap=10) == []
    assert semantic_chunking("", chunk_size=50, overlap=0) == []
    assert semantic_chunking("\n\t", chunk_size=50, overlap=0) == []

    chunks = create_chunks(
        [{"page_number": 1, "text": ""}, {"page_number": 2, "text": "   "}],
        regulation_id=1,
        document_name="Doc",
        regulation_version="v1",
        admission_batch_applicability=["2024"],
        programme_applicability=["BSc CS"],
        chunking_strategy="recursive",
        chunk_size=50,
        overlap=10,
    )
    assert chunks == []


def test_page_metadata_preservation_and_required_fields() -> None:
    """Preserves required source/applicability metadata for every chunk."""
    pages = [{"page_number": 7, "text": "Regulation text for metadata preservation."}]
    metadata = {
        "id": 42,
        "document_name": "Academic Regulations",
        "regulation_version": "2026.1",
        "applicable_batches": ["2024", "2025"],
        "applicable_programmes": ["BSc Computer Science"],
    }

    chunks = create_chunks(
        pages,
        regulation_metadata=metadata,
        chunking_strategy="fixed_size",
        chunk_size=100,
        overlap=0,
    )

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["chunk_id"]
    assert chunk["regulation_id"] == 42
    assert chunk["document_name"] == "Academic Regulations"
    assert chunk["regulation_version"] == "2026.1"
    assert chunk["page_number"] == 7
    assert chunk["admission batch applicability"] == ["2024", "2025"]
    assert chunk["programme applicability"] == ["BSc Computer Science"]
    assert chunk["chunking strategy"] == "fixed_size"
    assert "Regulation text for metadata preservation." in chunk["chunk text"]


def test_multiple_page_documents_preserve_page_references() -> None:
    """Creates chunks per source page without losing page references."""
    pages = [
        {"page_number": 1, "text": "Page one regulation content."},
        {"page_number": 2, "text": "Page two regulation content."},
        {"page_number": 3, "text": ""},  # empty page should be skipped safely
    ]

    chunks = create_chunks(
        pages,
        regulation_id=5,
        document_name="Multi-page Doc",
        regulation_version="v2",
        admission_batch_applicability=["2023"],
        programme_applicability=["BEng"],
        chunking_strategy="recursive",
        chunk_size=200,
        overlap=0,
    )

    assert len(chunks) == 2
    assert [chunk["page_number"] for chunk in chunks] == [1, 2]
    assert all(chunk["regulation_id"] == 5 for chunk in chunks)
    assert all(chunk["chunking strategy"] == "recursive" for chunk in chunks)
    assert "Page one regulation content." in chunks[0]["chunk text"]
    assert "Page two regulation content." in chunks[1]["chunk text"]


def test_long_text_chunking_across_strategies() -> None:
    """Handles long text by producing multiple chunks for each strategy."""
    text = ("This regulation clause repeats for testing long documents. " * 80).strip()

    fixed_chunks = fixed_size_chunking(text, chunk_size=120, overlap=20)
    recursive_chunks = recursive_chunking(text, chunk_size=120, overlap=20)
    semantic_chunks = semantic_chunking(text, chunk_size=120, overlap=20)

    assert len(fixed_chunks) > 1
    assert len(recursive_chunks) > 1
    assert len(semantic_chunks) > 1
    assert all(chunk.strip() for chunk in fixed_chunks)
    assert all(chunk.strip() for chunk in recursive_chunks)
    assert all(chunk.strip() for chunk in semantic_chunks)
    # Overlap should cause adjacent fixed-size chunks to share boundary content.
    assert fixed_chunks[0][-20:] in fixed_chunks[1]


def test_create_chunks_accepts_extracted_text_and_avoids_duplicate_text_chunks() -> None:
    """Supports DB-style page fields and avoids duplicate chunk records where possible."""
    pages = [
        {"page_number": 1, "extracted_text": "Same content. Same content."},
        {"page_number": 1, "extracted_text": "Same content. Same content."},
    ]

    chunks = create_chunks(
        pages,
        regulation_id=9,
        document_name="Dedup Doc",
        regulation_version="v1",
        admission_batch_applicability=["2024"],
        programme_applicability=["BSc"],
        chunking_strategy="fixed_size",
        chunk_size=500,
        overlap=0,
    )

    assert len(chunks) == 1
    assert chunks[0]["page_number"] == 1
    assert "Same content." in chunks[0]["chunk text"]
