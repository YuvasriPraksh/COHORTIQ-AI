"""Schemas for cohort query and grounded-answer API operations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import GroundedAnswer, GroundedCitation


class CohortInfo(BaseModel):
    """Cohort identifiers used for applicability-filtered retrieval."""

    model_config = ConfigDict(extra="allow")

    admission_batch: str
    programme: str


class StudentQuestionRequest(CohortInfo):
    """Request payload for answering a cohort-specific student question."""

    top_k: int = 5
    chunking_strategy: str = "recursive"
    chunk_size: int = 1000
    overlap: int = 200
    question: str


class RetrievalResultItem(BaseModel):
    """Retrieved evidence chunk/result item as returned by retrieval."""

    model_config = ConfigDict(extra="allow")

    chunk_id: Optional[Any] = None
    chunk_text: Optional[str] = None
    regulation_id: Optional[Any] = None
    document_name: Optional[str] = None
    regulation_version: Optional[str] = None
    page_number: Optional[int] = None
    admission_batch: Optional[str] = None
    programme: Optional[str] = None
    retrieval_score: Optional[float] = None


class RetrievalResponse(BaseModel):
    """Retrieval response envelope."""

    model_config = ConfigDict(extra="allow")

    results: List[RetrievalResultItem] = Field(default_factory=list)
    status: str
    message: Optional[str] = None


class GroundedAnswerResponse(BaseModel):
    """Response envelope returned by the student question workflow/service."""

    model_config = ConfigDict(extra="allow")

    status: str
    answer: GroundedAnswer
    citations: List[GroundedCitation] = Field(default_factory=list)
    validation_issues: List[str] = Field(default_factory=list)
    retrieval: RetrievalResponse
    corpus: Optional[Dict[str, Any]] = None


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
