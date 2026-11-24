"""Regulation-related backend services.

This module provides a thin service layer for the FastAPI backend by delegating
to existing CohortIQ regulation workflow and database functions without
duplicating business logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app import database, workflow


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
