"""Schemas for regulation-related API requests and responses."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class RegulationMetadata(BaseModel):
    """Administrator-provided regulation metadata for ingestion workflows."""

    model_config = ConfigDict(extra="allow")

    document_name: str
    regulation_version: str
    effective_date: Any
    applicable_batches: List[str]
    applicable_programmes: List[str]
    upload_date: Optional[Any] = None
    total_pages: Optional[int] = None
    processing_status: Optional[str] = None


class RegulationRecord(BaseModel):
    """Stored regulation record as returned by the database layer."""

    model_config = ConfigDict(extra="allow")

    id: int
    document_name: str
    regulation_version: str
    effective_date: Optional[str] = None
    applicable_batches: List[str] = Field(default_factory=list)
    applicable_programmes: List[str] = Field(default_factory=list)
    upload_date: Optional[str] = None
    total_pages: Optional[int] = None
    processing_status: Optional[str] = None
    verification_status: Optional[str] = None


class RegulationListResponse(BaseModel):
    """Response containing a list of stored regulations."""

    model_config = ConfigDict(extra="allow")

    regulations: List[RegulationRecord] = Field(default_factory=list)


class CohortOption(BaseModel):
    """An admission batch and programme covered by an approved regulation."""

    admission_batch: str
    programme: str


class CohortListResponse(BaseModel):
    cohorts: List[CohortOption] = Field(default_factory=list)


class RegulationDetailResponse(BaseModel):
    """Response containing a single regulation record, if found."""

    model_config = ConfigDict(extra="allow")

    regulation: Optional[RegulationRecord] = None


class DocumentPage(BaseModel):
    """Stored document page record as returned by the database layer."""

    model_config = ConfigDict(extra="allow")

    id: Optional[int] = None
    regulation_id: Optional[int] = None
    page_number: int
    extracted_text: Optional[str] = None
    extraction_status: Optional[str] = None


class DocumentPageListResponse(BaseModel):
    """Response containing stored document pages for a regulation."""

    model_config = ConfigDict(extra="allow")

    regulation_id: int
    pages: List[DocumentPage] = Field(default_factory=list)


class ExtractionSummaryPage(BaseModel):
    """Per-page extraction summary entry."""

    model_config = ConfigDict(extra="allow")

    page_number: Optional[int] = None
    status: Optional[str] = None


class ExtractionSummary(BaseModel):
    """PDF extraction summary returned by ingestion workflows."""

    model_config = ConfigDict(extra="allow")

    filename: Optional[str] = None
    total_pages: Optional[int] = None
    successful_pages: Optional[int] = None
    pages_needing_attention: Optional[int] = None
    pages: List[ExtractionSummaryPage] = Field(default_factory=list)


class RegulationIngestionResult(BaseModel):
    """Result returned by regulation ingestion workflow/service calls."""

    model_config = ConfigDict(extra="allow")

    status: str
    regulation_id: Optional[int] = None
    verification_status: Optional[str] = None
    extraction_summary: Optional[ExtractionSummary] = None
    message: str


class VerificationUpdateRequest(BaseModel):
    """Request to explicitly set a regulation verification status."""

    model_config = ConfigDict(extra="allow")

    verification_status: str = Field(
        default="approved",
        description=(
            "Verification status to set. Allowed values: approved, pending, rejected "
            "(case-insensitive). Other values are rejected with HTTP 400."
        ),
    )


class VerificationUpdateResponse(BaseModel):
    """Result returned by explicit regulation verification/approval updates."""

    model_config = ConfigDict(extra="allow")

    status: str
    regulation_id: int
    updated: Optional[bool] = None
    verification_status: Optional[str] = None
    message: str
