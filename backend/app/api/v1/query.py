"""Student question-and-answer API routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.app.schemas.query import GroundedAnswerResponse, StudentQuestionRequest
from backend.app.services import query_service

router = APIRouter(tags=["query"])


def get_db_path() -> Optional[str]:
    """Provide an optional database path override for dependency injection.

    Tests can override this dependency to use an isolated temporary SQLite DB.
    Production/runtime usage defaults to the existing application database path.
    """
    return None


@router.post("/query/ask", response_model=GroundedAnswerResponse)
def ask_student_question(
    request: StudentQuestionRequest,
    db_path: Optional[str] = Depends(get_db_path),
) -> GroundedAnswerResponse:
    """Answer a cohort-specific student question using approved evidence.

    Delegates to the existing query service/workflow to preserve cohort
    applicability filtering, approved-only retrieval, no-evidence handling,
    Gemini grounded-answer generation, and final citation validation.
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
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to answer student question: {exc}",
        ) from exc
