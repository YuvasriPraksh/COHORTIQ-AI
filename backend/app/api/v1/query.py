"""Student question-and-answer API routes."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import (
    AuthenticatedUser,
    DenialRecorder,
    get_auth_db_path,
    get_current_user,
    get_denial_recorder,
)
from backend.app.api.permissions import COHORT_SCOPED_RESPONSES, ensure_cohort_access
from backend.app.audit.repository import append_audit_event
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


def _record_question(
    user: AuthenticatedUser,
    response: GroundedAnswerResponse,
    admission_batch: str,
    programme: str,
    audit_db_path: Optional[str],
) -> None:
    """Record that a question was handled, never its text or the answer.

    Best-effort: a failed audit write is logged and the answer is still returned,
    because nothing was changed that would need to be undone.
    """
    details = {
        "answer_status": response.status,
        "admission_batch": admission_batch,
        "programme": programme,
    }
    if response.route is not None:
        details["route"] = response.route.route
    try:
        append_audit_event(
            "query.answered",
            outcome="success",
            actor_type="user",
            actor_user_id=int(user.id),
            actor_role=user.role,
            details=details,
            db_path=audit_db_path,
        )
    except Exception:
        logger.exception("Could not record an answered question in the audit log.")


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
    audit_db_path: Optional[str] = Depends(get_auth_db_path),
) -> GroundedAnswerResponse:
    """Answer a cohort-specific student question using approved evidence.

    Requires a signed-in user. A student or staff member may only ask about the admission batch
    and programme stored on their account: a request naming any other cohort is
    refused with 403, and retrieval always uses the stored values. Administrators
    may ask about any cohort.

    The question is first routed (``backend.app.services.adaptive_router``):
    questions with no academic-regulation term are refused, clause references
    are answered from the top 3 chunks, and weak evidence (no applicable
    regulation, a missing clause, or a best retrieval score below
    ``RETRIEVAL_MIN_SCORE``) is abstained on without calling Gemini. Other
    questions use the existing workflow, which preserves cohort applicability
    filtering, approved-only retrieval, no-evidence handling, Gemini
    grounded-answer generation, and final citation validation.

    The public response contains only ``status``, ``answer``, ``citations``,
    ``validation_issues``, ``retrieval`` (status, message and source metadata
    for each retrieved chunk) and ``route`` (the routing decision). The internal workflow result is passed
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
        result = query_service.answer_with_adaptive_routing(
            admission_batch=admission_batch,
            programme=programme,
            question=question,
            db_path=db_path,
            top_k=request.top_k,
            chunking_strategy=request.chunking_strategy,
            chunk_size=request.chunk_size,
            overlap=request.overlap,
        )
        response = GroundedAnswerResponse(**result)
        _record_question(user, response, admission_batch, programme, audit_db_path)
        return response
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
