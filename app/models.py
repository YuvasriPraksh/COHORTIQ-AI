"""Data models for CohortIQ AI.

This module defines structured representations for documents, text chunks,
citations, and grounded Gemini responses used across the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


@dataclass
class Document:
    """Represents an uploaded academic regulation document."""

    source_path: Path
    title: str | None = None


@dataclass
class Chunk:
    """Represents a chunk of extracted document text."""

    document_id: str
    text: str
    chunk_index: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Citation:
    """Represents a reference to supporting source material."""

    document_id: str
    chunk_index: int
    reference_text: str


class GroundedCitation(BaseModel):
    """Citation grounded in retrieved regulation evidence."""

    model_config = ConfigDict(extra="ignore")

    document_name: str | None = None
    regulation_version: str | None = None
    page_number: int | None = None
    chunk_id: str | None = None
    relevant_supporting_text: str | None = Field(
        default=None,
        description="Supporting text excerpt taken from the retrieved evidence chunk.",
    )


class GroundedAnswer(BaseModel):
    """Structured, grounded answer returned by the Gemini service."""

    model_config = ConfigDict(extra="ignore")

    answer: str
    status: Literal["answered", "insufficient_evidence", "conflicting_evidence"]
    citations: list[GroundedCitation] = Field(default_factory=list)
    limitations: str | None = Field(
        default=None,
        description="Explanation of evidence gaps, conflicts, or processing limitations.",
    )

