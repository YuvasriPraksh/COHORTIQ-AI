"""Student question-and-answer API routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import AuthenticatedUser, DenialRecorder, get_current_user, get_denial_recorder
from backend.app.api.permissions import COHORT_SCOPED_RESPONSES, ensure_cohort_access
from backend.app.schemas.query import GroundedAnswerResponse, StudentQuestionRequest
from backend.app.services import query_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])

QUERY_INTERNAL_ERROR_DETAIL = (
    "The question could not be answered due to an internal server error. Please try again later."
)


def get_db_path() -> Optional[str]:
    """Provide an optional database path override for dependency injection.

    Tests can override this dependency to use an isolated temporary SQLite DB.
    Production/runtime usage defaults to the existing application database path.
    """
    return None


@router.post(
    "/query/ask",
    response_model=GroundedAnswerResponse,
    responses={
        200: {
            "description": (
                "Grounded answer with validated citations and retrieval source metadata. "
                "The internal retrieval corpus and raw chunk text are not included."
            )
        },
        400: {"description": "question, admission_batch, or programme is blank."},
        **COHORT_SCOPED_RESPONSES,
        500: {"description": "Unexpected internal server error. Details are logged, never returned."},
    },
)
def ask_student_question(
    request: StudentQuestionRequest,
    db_path: Optional[str] = Depends(get_db_path),
    user: AuthenticatedUser = Depends(get_current_user),
    record_denial: DenialRecorder = Depends(get_denial_recorder),
) -> GroundedAnswerResponse:
    """Answer a cohort-specific student question using approved evidence.

    Requires a signed-in user. A student may only ask about the admission batch
    and programme stored on their account: a request naming any other cohort is
    refused with 403, and retrieval always uses the stored values. Administrators
    may ask about any cohort.

    Delegates to the existing query service/workflow to preserve cohort
    applicability filtering, approved-only retrieval, no-evidence handling,
    Gemini grounded-answer generation, and final citation validation.

    The public response contains only ``status``, ``answer``, ``citations``,
    ``validation_issues`` and ``retrieval`` (status, message and source
    metadata for each retrieved chunk). The internal workflow result is passed
    through ``GroundedAnswerResponse``, which drops the full retrieval corpus,
    raw chunk text and any other undeclared internal field.

    Expected outcomes (answered, insufficient_evidence, conflicting_evidence)
    are returned with HTTP 200. Unexpected server exceptions are logged with
    their traceback and returned as a generic HTTP 500 without internal details.
    """
    question = request.question.strip()
    admission_batch = request.admission_batch.strip()
    programme = request.programme.strip()

    if not question or not admission_batch or not programme:
        raise HTTPException(
            status_code=400,
            detail="question, admission_batch, and programme are required.",
        )

    # Retrieval filters (approved-only, cohort applicability) run on these values.
    admission_batch, programme = ensure_cohort_access(user, admission_batch, programme, record_denial=record_denial)

    try:
        result = query_service.answer_student_regulation_question(
            admission_batch=admission_batch,
            programme=programme,
            question=question,
            db_path=db_path,
            top_k=request.top_k,
            chunking_strategy=request.chunking_strategy,
            chunk_size=request.chunk_size,
            overlap=request.overlap,
        )
        return GroundedAnswerResponse(**result)
    except HTTPException:
        raise
    except Exception:
        # The question text is deliberately not logged; cohort context is enough
        # to investigate and avoids recording student-entered content.
        logger.exception(
            "Unexpected error while answering student question "
            "(admission_batch=%r, programme=%r).",
            admission_batch,
            programme,
        )
        raise HTTPException(status_code=500, detail=QUERY_INTERNAL_ERROR_DETAIL) from None
