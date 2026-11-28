"""Response schema for My Academic Impact Twin."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Classification = Literal["potential_impact", "no_direct_impact", "requires_review"]


class ImpactCohort(BaseModel):
    admission_batch: str
    programme: str


class ImpactRegulation(BaseModel):
    id: int
    document_name: str
    regulation_version: str
    effective_date: Optional[str] = None


class ImpactLatestUpdate(BaseModel):
    review_id: int
    document_name: str
    previous_version: str
    new_version: str
    reviewed_at: Optional[str] = None
    change_count: int


class ImpactSummary(BaseModel):
    potential_impact: int = 0
    requires_review: int = 0
    no_direct_impact: int = 0
    total: int = 0


class ImpactAssessment(BaseModel):
    review_id: int
    change_id: int
    document_name: str
    previous_regulation_id: int
    previous_version: str
    new_regulation_id: int
    new_version: str
    reviewed_at: Optional[str] = None
    change_type: Literal["addition", "removal", "modification"]
    clause: str
    previous_page: Optional[int] = None
    new_page: Optional[int] = None
    previous_text: Optional[str] = None
    new_text: Optional[str] = None
    previous_text_truncated: bool = False
    new_text_truncated: bool = False
    applicability: str
    classification: Classification
    classification_label: str
    classification_reason: str
    previous_values: list[str] = Field(default_factory=list)
    revised_values: list[str] = Field(default_factory=list)
    text_similarity: float
    topics: list[str] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)
    review_points: list[str] = Field(default_factory=list)


class ImpactTwinResponse(BaseModel):
    cohort: Optional[ImpactCohort] = None
    applicable_regulations: list[ImpactRegulation] = Field(default_factory=list)
    latest_update: Optional[ImpactLatestUpdate] = None
    summary: ImpactSummary
    assessments: list[ImpactAssessment] = Field(default_factory=list)
    personal_records_available: bool = False
    personalization_note: str
