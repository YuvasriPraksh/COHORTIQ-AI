"""Student question-and-answer API routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

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
        400: {"description": "question, admission_batch, or programme is blank."},
        500: {"description": "Unexpected internal server error. Details are logged, never returned."},
    },
)
def ask_student_question(
    request: StudentQuestionRequest,
    db_path: Optional[str] = Depends(get_db_path),
) -> GroundedAnswerResponse:
    """Answer a cohort-specific student question using approved evidence.

    Delegates to the existing query service/workflow to preserve cohort
    applicability filtering, approved-only retrieval, no-evidence handling,
    Gemini grounded-answer generation, and final citation validation.

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
