"""PDF processing utilities for CohortIQ AI.

This module is responsible for extracting text and relevant metadata from
uploaded academic regulation documents using PyMuPDF (fitz).
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import fitz  # PyMuPDF


class PageExtractionResult(TypedDict):
    """Structured extraction result for a single PDF page."""

    page_number: int
    text: str
    status: str


class PDFExtractionResult(TypedDict):
    """Structured extraction result for a PDF document."""

    filename: str
    total_pages: int
    pages: list[PageExtractionResult]


def extract_text_from_pdf(pdf_path: str | Path) -> PDFExtractionResult:
    """Extract text from each page of a PDF file.

    Args:
        pdf_path: Path to the PDF file to process.

    Returns:
        A dictionary containing:
            - filename: The document filename.
            - total_pages: Total number of pages in the PDF.
            - pages: A list of per-page results with:
                - page_number: 1-based page number.
                - text: Extracted page text (preserved as extracted).
                - status: "success" when text is found, or
                  "needs_ocr_or_manual_inspection" when no extractable text
                  is detected.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        ValueError: If the path is not a file, or the file is not a valid or
            readable PDF document (including corrupted PDFs).
        RuntimeError: If an unexpected error occurs during page extraction.
    """
    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")
    if not path.is_file():
        raise ValueError(f"PDF path is not a file: {path}")

    try:
        document = fitz.open(path)
    except Exception as exc:
        raise ValueError(f"Invalid or corrupted PDF file: {path}") from exc

    try:
        total_pages = document.page_count
        pages: list[PageExtractionResult] = []

        for index in range(total_pages):
            page = document.load_page(index)
            text = page.get_text("text")
            has_extractable_text = bool(text and text.strip())
            status = "success" if has_extractable_text else "needs_ocr_or_manual_inspection"
            pages.append(
                {
                    "page_number": index + 1,  # 1-based numbering for citations
                    "text": text,
                    "status": status,
                }
            )

        return {
            "filename": path.name,
            "total_pages": total_pages,
            "pages": pages,
        }
    except Exception as exc:
        raise RuntimeError(f"Unexpected error while extracting PDF '{path}': {exc}") from exc
    finally:
        document.close()
