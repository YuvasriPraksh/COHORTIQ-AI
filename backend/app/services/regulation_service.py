"""Regulation-related backend services.

This module provides a thin service layer for the FastAPI backend by delegating
to existing CohortIQ regulation workflow and database functions without
duplicating business logic.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from app import database, workflow

# Message prefixes produced by ``app.workflow.ingest_uploaded_regulation`` and
# ``app.pdf_processor.extract_text_from_pdf``. The workflow reports every
# failure as ``status == "error"``; these prefixes identify the failure stage.
_INVALID_METADATA_PREFIX = "Invalid regulation metadata:"
_PDF_EXTRACTION_PREFIX = "PDF extraction failed:"
_INVALID_PDF_MARKER = "Invalid or corrupted PDF file"


ALLOWED_VERIFICATION_STATUSES: tuple[str, ...] = ("approved", "pending", "rejected")
"""Verification statuses an administrator may set through the API.

These are the three states the application recognizes for review workflows:
``approved`` makes a regulation eligible as student evidence, ``rejected``
excludes it, and ``pending`` returns it to the review queue.
"""


def normalize_verification_status(value: Any) -> str | None:
    """Return the canonical (trimmed, lower-case) status, or ``None`` if not allowed."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized if normalized in ALLOWED_VERIFICATION_STATUSES else None


class IngestionFailureKind(str, Enum):
    """Category of a failed ingestion result."""

    INVALID_METADATA = "invalid_metadata"
    """The client supplied missing or invalid regulation metadata."""

    INVALID_PDF = "invalid_pdf"
    """The uploaded file could not be opened as a PDF (corrupted, empty, not a PDF)."""

    INTERNAL_ERROR = "internal_error"
    """A server-side failure (storage, temporary file handling, unexpected errors)."""


def classify_ingestion_failure(result: Mapping[str, Any]) -> IngestionFailureKind | None:
    """Classify an ingestion workflow result.

    Returns ``None`` for a successful ingestion. Only failures positively
    identified as caused by the client's input are classified as client errors;
    every other failure, including unrecognized statuses or messages, is treated
    as an internal error so server faults are never reported as client mistakes.
    """
    status = result.get("status")
    if status == "ingested":
        return None

    message = str(result.get("message") or "")
    if status == "error":
        if message.startswith(_INVALID_METADATA_PREFIX):
            return IngestionFailureKind.INVALID_METADATA
        if message.startswith(_PDF_EXTRACTION_PREFIX) and _INVALID_PDF_MARKER in message:
            return IngestionFailureKind.INVALID_PDF
    return IngestionFailureKind.INTERNAL_ERROR


def ingest_regulation(
    pdf_path: str | Path,
    metadata: Mapping[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Ingest an uploaded regulation by delegating to the existing workflow.

    Preserves existing behavior: metadata validation, PDF extraction, storage,
    and pending verification status (never auto-approved).
    """
    return workflow.ingest_uploaded_regulation(
        pdf_path=pdf_path,
        metadata=metadata,
        db_path=db_path,
    )


def approve_or_verify_regulation(
    regulation_id: int,
    db_path: str | Path | None = None,
    verification_status: str = "approved",
) -> dict[str, Any]:
    """Explicitly approve or update verification status via the existing workflow.

    Preserves existing behavior: verification status changes only through
    explicit service/workflow invocation and never during ingestion.
    """
    return workflow.approve_regulation(
        regulation_id=regulation_id,
        db_path=db_path,
        verification_status=verification_status,
    )


def list_regulations(db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return all stored regulations by delegating to the existing database layer."""
    return database.get_all_regulations(db_path=db_path)


def get_regulation_details(
    regulation_id: int, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """Return regulation details by delegating to the existing database layer."""
    return database.get_regulation_by_id(regulation_id=regulation_id, db_path=db_path)


def get_regulation_document_pages(
    regulation_id: int, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """Return stored document pages for a regulation via the existing database layer."""
    return database.get_document_pages(regulation_id=regulation_id, db_path=db_path)
