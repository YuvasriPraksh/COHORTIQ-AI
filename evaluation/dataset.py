"""Evaluation dataset format and loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation.metrics import ExpectedSource

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
DEFAULT_DATASET = DATASETS_DIR / "retrieval_v1.json"


class ExpectedPages(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_name: str = Field(min_length=1)
    regulation_version: str = Field(min_length=1)
    pages: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_pages(self) -> "ExpectedPages":
        if any(page < 1 for page in self.pages) or len(set(self.pages)) != len(self.pages):
            raise ValueError("pages must be distinct positive page numbers.")
        return self

    def as_source(self) -> ExpectedSource:
        return ExpectedSource(self.document_name, self.regulation_version, frozenset(self.pages))


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    category: str = Field(min_length=1, max_length=50)
    question: str = Field(min_length=1)
    admission_batch: str = Field(min_length=1)
    programme: str = Field(min_length=1)
    expected: Optional[ExpectedPages]
    expect_abstain: bool
    reference_answer: Optional[str] = None
    source_note: Optional[str] = None

    @model_validator(mode="after")
    def _expected_matches_abstention(self) -> "EvaluationCase":
        if self.expect_abstain and self.expected is not None:
            raise ValueError("a case expecting abstention must not list expected pages.")
        if not self.expect_abstain and self.expected is None:
            raise ValueError("an answerable case must list expected pages.")
        return self


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    relevance_unit: Literal["page"]
    cases: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "EvaluationDataset":
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("case ids must be unique.")
        return self

    def expected_versions(self) -> set[tuple[str, str]]:
        return {
            (case.expected.document_name, case.expected.regulation_version)
            for case in self.cases
            if case.expected is not None
        }


def load_dataset(path: str | Path = DEFAULT_DATASET) -> EvaluationDataset:
    """Load and validate a dataset file. Raises ``ValueError`` if it is invalid."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return EvaluationDataset.model_validate(data)
