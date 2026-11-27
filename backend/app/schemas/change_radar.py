"""Request and response models for administrator regulation comparisons."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_regulation_id: int = Field(ge=1)
    new_regulation_id: int = Field(ge=1)
    applicable_batches: list[str] = Field(min_length=1, max_length=50)
    applicable_programmes: list[str] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def distinct_sources_and_applicability(self) -> "ReviewCreateRequest":
        if self.previous_regulation_id == self.new_regulation_id:
            raise ValueError("Choose two different regulation versions.")
        for field_name in ("applicable_batches", "applicable_programmes"):
            values = [value.strip() for value in getattr(self, field_name)]
            if any(not value or len(value) > 100 for value in values):
                raise ValueError(f"{field_name} must contain non-empty values of at most 100 characters.")
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} cannot contain duplicates.")
            setattr(self, field_name, values)
        return self


class ReviewStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["needs_review", "approved"]


class PotentialChange(BaseModel):
    id: int
    change_type: Literal["addition", "removal", "modification"]
    clause: str
    previous_page: int | None
    new_page: int | None
    previous_text: str | None
    new_text: str | None
    previous_text_truncated: bool = False
    new_text_truncated: bool = False


class ChangeReviewResponse(BaseModel):
    id: int
    previous_regulation_id: int
    previous_document_name: str
    previous_version: str
    new_regulation_id: int
    new_document_name: str
    new_version: str
    status: Literal["needs_review", "approved"]
    applicable_batches: list[str]
    applicable_programmes: list[str]
    changes: list[PotentialChange]
    created_by: int
    created_at: str
    reviewed_by: int | None
    reviewed_at: str | None
    warning: str = "Potential changes — review required."


class ChangeReviewListResponse(BaseModel):
    reviews: list[ChangeReviewResponse]


class PublishedUpdatesResponse(BaseModel):
    updates: list[ChangeReviewResponse]
