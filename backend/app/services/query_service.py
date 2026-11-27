"""Query-related backend services.

This module provides a thin service layer for cohort retrieval and grounded
question answering by delegating to existing CohortIQ workflow functions without
duplicating business logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from app import workflow
from app.gemini_service import GeminiAnswerService
from app.models import GroundedAnswer
from backend.app.schemas.routing import RouteDecision
from backend.app.services import adaptive_router

# Fixed, student-facing explanations for routes that do not generate an answer.
_ROUTE_MESSAGES = {
    "out_of_scope": (
        "I can only answer questions about the academic regulations that apply to your cohort.",
        "The question does not appear to be about academic regulations, so no regulation was searched.",
    ),
    "clarify": (
        "Please tell me your admission batch and programme so I can find the regulations that apply to you.",
        "Cohort details are missing, so the applicable regulations cannot be determined.",
    ),
    "clause_not_found": (
        "I could not find that clause in the approved regulations that apply to your cohort.",
        "The cited clause number does not appear in the applicable approved regulations.",
    ),
    "score_below_threshold": (
        "I cannot provide a grounded answer because the approved regulations for your cohort do not appear to cover this question.",
        "The best matching regulation text was too weak to support an answer.",
    ),
}


def build_cohort_retrieval_corpus(
    admission_batch: str,
    programme: str,
    db_path: str | Path | None = None,
    *,
    chunking_strategy: str = "recursive",
    chunk_size: int = 1000,
    overlap: int = 200,
) -> dict[str, Any]:
    """Build the retrieval corpus for a cohort via the existing workflow.

    Preserves existing behavior: only approved regulations applicable to the
    supplied admission batch and programme are included.
    """
    return workflow.build_retrieval_corpus_for_cohort(
        admission_batch=admission_batch,
        programme=programme,
        db_path=db_path,
        chunking_strategy=chunking_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
    )


def answer_student_regulation_question(
    admission_batch: str,
    programme: str,
    question: str,
    *,
    db_path: str | Path | None = None,
    top_k: int = 5,
    chunking_strategy: str = "recursive",
    chunk_size: int = 1000,
    overlap: int = 200,
    evidence_chunks: Sequence[Any] | None = None,
    gemini_service: GeminiAnswerService | Any | None = None,
    gemini_client: Any | None = None,
    gemini_settings: Any | None = None,
    gemini_model_name: str | None = None,
) -> dict[str, Any]:
    """Answer a student regulation question via the existing workflow.

    Preserves the existing retrieval and AI answer pipeline, including cohort
    applicability filtering, approved-only evidence, no-evidence short-circuit
    (no Gemini generation when retrieval has no evidence), and final citation
    validation.
    """
    return workflow.answer_student_question(
        admission_batch=admission_batch,
        programme=programme,
        question=question,
        db_path=db_path,
        top_k=top_k,
        chunking_strategy=chunking_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
        evidence_chunks=evidence_chunks,
        gemini_service=gemini_service,
        gemini_client=gemini_client,
        gemini_settings=gemini_settings,
        gemini_model_name=gemini_model_name,
    )


def _unanswered(decision: RouteDecision, key: str, retrieval_status: str) -> dict[str, Any]:
    """Response for a route that deliberately does not generate an answer (no model call)."""
    answer_text, limitation = _ROUTE_MESSAGES[key]
    answer = GroundedAnswer(answer=answer_text, status="insufficient_evidence", citations=[], limitations=limitation)
    return {
        "status": answer.status,
        "answer": answer.model_dump(),
        "citations": [],
        "validation_issues": [],
        "retrieval": {"status": retrieval_status, "message": limitation, "results": []},
        "route": decision.model_dump(mode="json"),
    }


def answer_with_adaptive_routing(
    admission_batch: str,
    programme: str,
    question: str,
    *,
    db_path: str | Path | None = None,
    top_k: int = 5,
    chunking_strategy: str = "recursive",
    chunk_size: int = 1000,
    overlap: int = 200,
    min_score: Optional[float] = None,
    gemini_service: GeminiAnswerService | Any | None = None,
    gemini_client: Any | None = None,
    gemini_settings: Any | None = None,
    gemini_model_name: str | None = None,
) -> dict[str, Any]:
    """Route a question (``adaptive_router``), then answer, abstain, clarify or refuse.

    - ``clause_lookup`` and ``general``: the existing answer path, given the
      cohort corpus the router already built (top 3 for clause lookups), so
      retrieval, citation validation and the no-evidence short-circuit are
      unchanged.
    - ``low_evidence`` with no applicable regulation or no retrieval results:
      the existing workflow, which returns its standard no-evidence answer
      without calling the model.
    - ``out_of_scope``, ``clarify``, ``clause_not_found`` and
      ``score_below_threshold``: a fixed answer; nothing is generated.

    The result carries the validated decision under ``route``.
    """
    common = dict(
        db_path=db_path,
        chunking_strategy=chunking_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
    )
    outcome = adaptive_router.route_question(question, admission_batch, programme, top_k=top_k, min_score=min_score, **common)
    decision = outcome.decision
    generation = dict(
        gemini_service=gemini_service,
        gemini_client=gemini_client,
        gemini_settings=gemini_settings,
        gemini_model_name=gemini_model_name,
    )

    cohort_question = dict(admission_batch=admission_batch, programme=programme, question=question)
    if decision.calls_generator:
        result = answer_student_regulation_question(
            **cohort_question, top_k=decision.top_k, evidence_chunks=outcome.corpus_chunks, **common, **generation,
        )
    elif decision.reason in ("no_applicable_regulations", "no_retrieval_results"):
        result = answer_student_regulation_question(
            **cohort_question, top_k=decision.top_k or top_k, **common, **generation,
        )
    elif decision.route in ("out_of_scope", "clarify"):
        result = _unanswered(decision, decision.route, "skipped")
    else:
        result = _unanswered(decision, decision.reason, "no_evidence")
    result = dict(result)
    result["route"] = decision.model_dump(mode="json")
    return result
