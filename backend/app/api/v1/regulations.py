"""Regulation and cohort applicability API routes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.database import get_applicable_regulations
from backend.app.schemas.regulations import (
    DocumentPageListResponse,
    RegulationDetailResponse,
    RegulationIngestionResult,
    RegulationListResponse,
    VerificationUpdateRequest,
    VerificationUpdateResponse,
)
from backend.app.services import regulation_service

router = APIRouter(tags=["regulations"])


def get_db_path() -> Optional[str]:
    """Dependency providing an optional database path override.

    Defaults to ``None`` so existing application/database configuration is used.
    Tests can override this dependency to use an isolated temporary database.
    """
    return None


@router.get("/regulations", response_model=RegulationListResponse)
def list_regulations(db_path: Optional[str] = Depends(get_db_path)) -> RegulationListResponse:
    """Return the list of stored regulations."""
    regulations = regulation_service.list_regulations(db_path=db_path)
    return RegulationListResponse(regulations=regulations)


@router.get("/regulations/{regulation_id}", response_model=RegulationDetailResponse)
def get_regulation(
    regulation_id: int, db_path: Optional[str] = Depends(get_db_path)
) -> RegulationDetailResponse:
    """Return regulation details or 404 if the regulation does not exist."""
    regulation = regulation_service.get_regulation_details(
        regulation_id=regulation_id, db_path=db_path
    )
    if regulation is None:
        raise HTTPException(status_code=404, detail="Regulation not found")
    return RegulationDetailResponse(regulation=regulation)


@router.get(
    "/regulations/{regulation_id}/pages",
    response_model=DocumentPageListResponse,
)
def get_regulation_pages(
    regulation_id: int, db_path: Optional[str] = Depends(get_db_path)
) -> DocumentPageListResponse:
    """Return stored document pages for a regulation.

    Returns 404 when the regulation does not exist. An existing regulation with
    zero extracted pages returns an empty list.
    """
    regulation = regulation_service.get_regulation_details(
        regulation_id=regulation_id, db_path=db_path
    )
    if regulation is None:
        raise HTTPException(status_code=404, detail="Regulation not found")

    pages = regulation_service.get_regulation_document_pages(
        regulation_id=regulation_id, db_path=db_path
    )
    return DocumentPageListResponse(regulation_id=regulation_id, pages=pages)


@router.get(
    "/cohorts/{admission_batch}/{programme}/regulations",
    response_model=RegulationListResponse,
)
def list_applicable_regulations_for_cohort(
    admission_batch: str,
    programme: str,
    db_path: Optional[str] = Depends(get_db_path),
) -> RegulationListResponse:
    """Return approved regulations applicable to the specified cohort.

    Uses existing database logic to preserve approved-only and cohort
    applicability filtering (student-facing results exclude pending/unapproved
    regulations).
    """
    regulations = get_applicable_regulations(
        admission_batch=admission_batch,
        programme=programme,
        db_path=db_path,
    )
    return RegulationListResponse(regulations=regulations)


@router.post("/regulations/ingest", response_model=RegulationIngestionResult)
async def ingest_regulation(
    file: UploadFile = File(...),
    document_name: str = Form(...),
    regulation_version: str = Form(...),
    effective_date: str = Form(...),
    applicable_batches: list[str] = Form(...),
    applicable_programmes: list[str] = Form(...),
    upload_date: Optional[str] = Form(None),
    processing_status: Optional[str] = Form(None),
    db_path: Optional[str] = Depends(get_db_path),
) -> RegulationIngestionResult:
    """Ingest a regulation PDF and metadata via the existing workflow service.

    Newly uploaded regulations remain pending and are never automatically
    approved. Temporary upload files are cleaned up after processing.
    """
    filename = file.filename or ""
    content_type = (file.content_type or "").lower()
    if not filename.lower().endswith(".pdf") and content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid file type. A PDF file is required.")

    if not document_name.strip() or not regulation_version.strip() or not effective_date.strip():
        raise HTTPException(status_code=400, detail="Missing required metadata.")

    batches = [value.strip() for value in applicable_batches if value and value.strip()]
    programmes = [value.strip() for value in applicable_programmes if value and value.strip()]
    if not batches or not programmes:
        raise HTTPException(status_code=400, detail="Missing required metadata.")

    metadata: dict[str, object] = {
        "document_name": document_name.strip(),
        "regulation_version": regulation_version.strip(),
        "effective_date": effective_date.strip(),
        "applicable_batches": batches,
        "applicable_programmes": programmes,
    }
    if upload_date is not None and upload_date.strip():
        metadata["upload_date"] = upload_date.strip()
    if processing_status is not None and processing_status.strip():
        metadata["processing_status"] = processing_status.strip()

    temp_path: Optional[Path] = None
    try:
        suffix = Path(filename).suffix or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = Path(temp_file.name)
            contents = await file.read()
            temp_file.write(contents)

        result = regulation_service.ingest_regulation(
            pdf_path=temp_path,
            metadata=metadata,
            db_path=db_path,
        )
        return RegulationIngestionResult(**result)
    finally:
        await file.close()
        if temp_path and temp_path.exists():
            try:
                os.remove(temp_path)
            except OSError:
                pass


@router.patch(
    "/regulations/{regulation_id}/verification",
    response_model=VerificationUpdateResponse,
)
def update_regulation_verification(
    regulation_id: int,
    request: VerificationUpdateRequest,
    db_path: Optional[str] = Depends(get_db_path),
) -> VerificationUpdateResponse:
    """Explicitly update a regulation's verification status.

    Verification changes occur only through explicit requests and never as part
    of ingestion. Returns 404 when the regulation does not exist.
    """
    verification_status = request.verification_status
    if verification_status is None or not str(verification_status).strip():
        raise HTTPException(
            status_code=400,
            detail="An explicit verification_status value is required.",
        )

    result = regulation_service.approve_or_verify_regulation(
        regulation_id=regulation_id,
        db_path=db_path,
        verification_status=str(verification_status),
    )

    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Regulation not found")
    if result.get("status") == "error":
        raise HTTPException(
            status_code=400,
            detail=str(result.get("message", "Failed to update regulation verification status.")),
        )

    return VerificationUpdateResponse(**result)
