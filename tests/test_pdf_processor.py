"""Tests for the PDF processing engine."""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pytest

from app.pdf_processor import extract_text_from_pdf


def _create_pdf(path: Path, page_texts: list[str | None]) -> Path:
    """Create a test PDF with one page per item in ``page_texts``.

    Args:
        path: Destination PDF path.
        page_texts: Text to insert on each page. Use ``None`` to create a
            blank/textless page.

    Returns:
        The path to the created PDF file.
    """
    document = fitz.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()
    return path


def test_successful_single_page_extraction(tmp_path: Path) -> None:
    """Extracts text from a valid single-page PDF."""
    pdf_path = _create_pdf(tmp_path / "single.pdf", ["Regulation clause 1.1"])

    result = extract_text_from_pdf(pdf_path)

    assert result["filename"] == "single.pdf"
    assert result["total_pages"] == 1
    assert len(result["pages"]) == 1
    assert result["pages"][0]["page_number"] == 1
    assert "Regulation clause 1.1" in result["pages"][0]["text"]
    assert result["pages"][0]["status"] == "success"


def test_multiple_page_extraction_and_numbering(tmp_path: Path) -> None:
    """Extracts each page separately and preserves 1-based page numbering."""
    pdf_path = _create_pdf(
        tmp_path / "multi.pdf",
        ["Page one content", "Page two content", "Page three content"],
    )

    result = extract_text_from_pdf(pdf_path)

    assert result["filename"] == "multi.pdf"
    assert result["total_pages"] == 3
    assert [page["page_number"] for page in result["pages"]] == [1, 2, 3]
    assert "Page one content" in result["pages"][0]["text"]
    assert "Page two content" in result["pages"][1]["text"]
    assert "Page three content" in result["pages"][2]["text"]
    assert all(page["status"] == "success" for page in result["pages"])


def test_textless_page_is_flagged_for_ocr_or_manual_inspection(tmp_path: Path) -> None:
    """Marks pages with no extractable text for OCR/manual inspection."""
    pdf_path = _create_pdf(tmp_path / "blank.pdf", [None, "Has text"])

    result = extract_text_from_pdf(pdf_path)

    assert result["total_pages"] == 2
    assert result["pages"][0]["page_number"] == 1
    assert result["pages"][0]["text"].strip() == ""
    assert result["pages"][0]["status"] == "needs_ocr_or_manual_inspection"
    assert result["pages"][1]["page_number"] == 2
    assert result["pages"][1]["status"] == "success"


def test_empty_pdf_returns_no_pages(tmp_path: Path) -> None:
    """Handles an empty PDF (zero pages) without crashing."""
    pdf_path = tmp_path / "empty.pdf"
    # Some PyMuPDF versions cannot save a document with zero pages, so we write
    # a minimal valid PDF structure directly to exercise empty-PDF handling.
    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
        b"xref\n"
        b"0 3\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"trailer<</Size 3/Root 1 0 R>>\n"
        b"startxref\n"
        b"110\n"
        b"%%EOF"
    )

    result = extract_text_from_pdf(pdf_path)

    assert result["filename"] == "empty.pdf"
    assert result["total_pages"] == 0
    assert result["pages"] == []


def test_invalid_pdf_input_raises_value_error(tmp_path: Path) -> None:
    """Raises a clear error for invalid/corrupted PDF content."""
    invalid_pdf = tmp_path / "invalid.pdf"
    invalid_pdf.write_bytes(b"This is not a valid PDF file")

    with pytest.raises(ValueError, match="Invalid or corrupted PDF file"):
        extract_text_from_pdf(invalid_pdf)


def test_missing_file_raises_file_not_found_error(tmp_path: Path) -> None:
    """Raises a clear error when the PDF file does not exist."""
    missing_pdf = tmp_path / "does_not_exist.pdf"

    with pytest.raises(FileNotFoundError, match="PDF file not found"):
        extract_text_from_pdf(missing_pdf)
