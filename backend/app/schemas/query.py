"""Schemas for cohort query and grounded-answer API operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.chunking import _normalize_strategy
from app.models import GroundedAnswer, GroundedCitation
from backend.app.schemas.routing import RouteDecision
from backend.app.core.config import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_OVERLAP,
    DEFAULT_TOP_K,
    get_settings,
)

_LIMITS = get_settings()
MAX_STRATEGY_LENGTH = 50


class CohortInfo(BaseModel):
    """Cohort identifiers used for applicability-filtered retrieval."""

    model_config = ConfigDict(extra="allow")

    admission_batch: str = Field(max_length=_LIMITS.max_identifier_length)
    programme: str = Field(max_length=_LIMITS.max_identifier_length)


class StudentQuestionRequest(CohortInfo):
    """Request payload for answering a cohort-specific student question.

    Integer fields are strict: booleans, numeric strings and decimals are
    rejected. Blank text fields are still rejected by the route with HTTP 400.
    """

    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=_LIMITS.max_top_k, strict=True)
    chunking_strategy: str = Field(default="recursive", max_length=MAX_STRATEGY_LENGTH)
    chunk_size: int = Field(
        default=DEFAULT_CHUNK_SIZE,
        ge=_LIMITS.min_chunk_size,
        le=_LIMITS.max_chunk_size,
        strict=True,
    )
    overlap: int = Field(default=DEFAULT_OVERLAP, ge=0, le=_LIMITS.max_overlap, strict=True)
    question: str = Field(max_length=_LIMITS.max_question_length)

    @field_validator("chunking_strategy")
    @classmethod
    def _validate_chunking_strategy(cls, value: str) -> str:
        """Accept the strategies and aliases supported by ``app.chunking``."""
        try:
            _normalize_strategy(value)
        except ValueError:
            raise ValueError(
                "Unsupported chunking strategy. Use 'fixed_size', 'recursive', or 'semantic'."
            ) from None
        return value

    @model_validator(mode="after")
    def _validate_overlap_below_chunk_size(self) -> "StudentQuestionRequest":
        if self.overlap >= self.chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        return self


class RetrievalResultItem(BaseModel):
    """Public metadata for a retrieved evidence chunk.

    Only the fields declared here are returned to API clients; anything else on
    the internal retrieval result (including the chunk text) is dropped. The
    evidence text that supports an answer is available through
    ``citations[].relevant_supporting_text``.
    """

    model_config = ConfigDict(extra="ignore")

    chunk_id: Optional[Any] = None
    regulation_id: Optional[Any] = None
    document_name: Optional[str] = None
    regulation_version: Optional[str] = None
    page_number: Optional[int] = None
    admission_batch: Optional[str] = None
    programme: Optional[str] = None
    retrieval_score: Optional[float] = None


class RetrievalResponse(BaseModel):
    """Public retrieval summary: status, message and evidence source metadata."""

    model_config = ConfigDict(extra="ignore")

    results: List[RetrievalResultItem] = Field(default_factory=list)
    status: str
    message: Optional[str] = None


class GroundedAnswerResponse(BaseModel):
    """Public response for a student question.

    Contains only the declared fields: ``status``, ``answer``, ``citations``,
    ``validation_issues``, ``retrieval`` and ``route``. The internal workflow
    result also carries the full retrieval ``corpus`` (used by the pipeline and
    Streamlit); it is intentionally not part of the API response and is dropped
    here.
    """

    model_config = ConfigDict(extra="ignore")

    status: str
    answer: GroundedAnswer
    citations: List[GroundedCitation] = Field(default_factory=list)
    validation_issues: List[str] = Field(default_factory=list)
    retrieval: RetrievalResponse
    route: Optional[RouteDecision] = Field(
        default=None,
        description="How the question was routed: out_of_scope, clarify, clause_lookup, low_evidence or general.",
    )


class InsufficientEvidenceResponse(GroundedAnswerResponse):
    """Grounded response representing insufficient evidence (same envelope)."""

    pass


class CohortCorpusResponse(BaseModel):
    """Response envelope for cohort retrieval corpus construction."""

    model_config = ConfigDict(extra="allow")

    status: str
    message: Optional[str] = None
    regulations: List[Dict[str, Any]] = Field(default_factory=list)
    chunks: List[Dict[str, Any]] = Field(default_factory=list)
