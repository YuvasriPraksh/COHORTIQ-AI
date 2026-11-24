"""Regulation and cohort applicability API routes."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional

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
from backend.app.services.regulation_service import IngestionFailureKind

logger = logging.getLogger(__name__)

router = APIRouter(tags=["regulations"])

INVALID_PDF_DETAIL = (
    "The uploaded file could not be read as a valid PDF document. "
    "It may be corrupted, empty or not actually a PDF."
)
INGESTION_INTERNAL_ERROR_DETAIL = (
    "Regulation ingestion failed due to an internal server error. Please try again later."
)
INVALID_VERIFICATION_STATUS_DETAIL = (
    "Invalid verification_status. Allowed values: "
    + ", ".join(regulation_service.ALLOWED_VERIFICATION_STATUSES)
    + "."
)
VERIFICATION_INTERNAL_ERROR_DETAIL = (
    "The verification status could not be updated due to an internal server error. "
    "Please try again later."
)

_INGESTION_FAILURE_STATUS_CODES = {
    IngestionFailureKind.INVALID_METADATA: 400,
    IngestionFailureKind.INVALID_PDF: 422,
    IngestionFailureKind.INTERNAL_ERROR: 500,
}


def _ingestion_failure_detail(kind: IngestionFailureKind, result: Mapping[str, Any]) -> str:
    """Return a client-safe error message for a failed ingestion.

    Workflow messages can contain server file paths or low-level error text, so
    they are only passed through for metadata errors, whose messages are built
    solely from the submitted field names.
    """
    if kind is IngestionFailureKind.INVALID_METADATA:
        return str(result.get("message") or "Invalid regulation metadata.")
    if kind is IngestionFailureKind.INVALID_PDF:
        return INVALID_PDF_DETAIL
    return INGESTION_INTERNAL_ERROR_DETAIL


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


@router.post(
    "/regulations/ingest",
    response_model=RegulationIngestionResult,
    responses={
        400: {"description": "Unsupported file type or missing/invalid regulation metadata."},
        422: {
            "description": (
                "Request validation failed (missing form fields), or the uploaded file "
                "could not be read as a valid PDF document."
            )
        },
        500: {"description": "Internal server error while processing or storing the regulation."},
    },
)
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
    approved. Temporary upload files are cleaned up after processing, whether
    ingestion succeeds or fails.

    Status codes: 200 on success; 400 for an unsupported file type or invalid
    metadata; 422 for missing form fields or an unreadable/corrupted PDF; 500
    for server-side failures (details are logged, never returned).
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

        failure = regulation_service.classify_ingestion_failure(result)
        if failure is not None:
            status_code = _INGESTION_FAILURE_STATUS_CODES[failure]
            log = logger.error if status_code >= 500 else logger.warning
            log(
                "Regulation ingestion failed (%s, HTTP %s, regulation_id=%s): %s",
                failure.value,
                status_code,
                result.get("regulation_id"),
                result.get("message"),
            )
            raise HTTPException(
                status_code=status_code,
                detail=_ingestion_failure_detail(failure, result),
            )

        return RegulationIngestionResult(**result)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during regulation ingestion.")
        raise HTTPException(status_code=500, detail=INGESTION_INTERNAL_ERROR_DETAIL) from None
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
    responses={
        400: {"description": "verification_status is blank or not one of: approved, pending, rejected."},
        404: {"description": "Regulation not found."},
        500: {"description": "Internal server error. Details are logged, never returned."},
    },
)
def update_regulation_verification(
    regulation_id: int,
    request: VerificationUpdateRequest,
    db_path: Optional[str] = Depends(get_db_path),
) -> VerificationUpdateResponse:
    """Explicitly update a regulation's verification status.

    Verification changes occur only through explicit requests and never as part
    of ingestion. Status codes: 200 when updated; 400 for a blank or
    unsupported status; 404 when the regulation does not exist; 500 for
    unexpected server failures (details are logged, never returned).
    """
    raw_status = request.verification_status
    if raw_status is None or not str(raw_status).strip():
        raise HTTPException(
            status_code=400,
            detail="An explicit verification_status value is required.",
        )

    verification_status = regulation_service.normalize_verification_status(raw_status)
    if verification_status is None:
        raise HTTPException(status_code=400, detail=INVALID_VERIFICATION_STATUS_DETAIL)

    # Input is fully validated above, so the workflow's only remaining failure
    # outcome ("error") can only come from a server-side fault. Outcomes are
    # classified by the structured ``status`` field, never by message text.
    try:
        result = regulation_service.approve_or_verify_regulation(
            regulation_id=regulation_id,
            db_path=db_path,
            verification_status=verification_status,
        )
        outcome = result.get("status")
        if outcome == "updated":
            return VerificationUpdateResponse(**result)
        if outcome == "not_found":
            raise HTTPException(status_code=404, detail="Regulation not found")
        logger.error(
            "Verification update failed (regulation_id=%s, requested_status=%r, outcome=%r): %s",
            regulation_id,
            verification_status,
            outcome,
            result.get("message"),
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Unexpected error while updating verification status (regulation_id=%s, requested_status=%r).",
            regulation_id,
            verification_status,
        )
    raise HTTPException(status_code=500, detail=VERIFICATION_INTERNAL_ERROR_DETAIL)
