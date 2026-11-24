"""Query-related backend services.

This module provides a thin service layer for cohort retrieval and grounded
question answering by delegating to existing CohortIQ workflow functions without
duplicating business logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from app import workflow
from app.gemini_service import GeminiAnswerService


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
