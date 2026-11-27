"""Retrieval metrics for the CohortIQ evaluation.

Relevance is judged per page: a retrieved chunk is relevant when it comes from
the expected regulation (document name and version) and from one of the
expected pages. Several chunks can come from the same page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class RetrievedSource:
    """Where one retrieved chunk came from, in rank order."""

    document_name: Optional[str]
    regulation_version: Optional[str]
    page_number: Optional[int]


@dataclass(frozen=True)
class ExpectedSource:
    """The regulation and pages that answer a question."""

    document_name: str
    regulation_version: str
    pages: frozenset[int]


def _check_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer.")


def same_version(item: RetrievedSource, expected: ExpectedSource) -> bool:
    return item.document_name == expected.document_name and item.regulation_version == expected.regulation_version


def is_relevant(item: RetrievedSource, expected: ExpectedSource) -> bool:
    return same_version(item, expected) and item.page_number in expected.pages


def relevance_flags(retrieved: Sequence[RetrievedSource], expected: ExpectedSource) -> list[bool]:
    return [is_relevant(item, expected) for item in retrieved]


def precision_at_k(retrieved: Sequence[RetrievedSource], expected: ExpectedSource, k: int) -> float:
    """Relevant chunks among the top ``k``, divided by ``k`` (missing slots count as not relevant)."""
    _check_k(k)
    return sum(relevance_flags(retrieved[:k], expected)) / k


def recall_at_k(retrieved: Sequence[RetrievedSource], expected: ExpectedSource, k: int) -> float:
    """Share of the expected pages that appear among the top ``k`` chunks."""
    _check_k(k)
    if not expected.pages:
        raise ValueError("expected pages must not be empty.")
    found = {item.page_number for item in retrieved[:k] if is_relevant(item, expected)}
    return len(found) / len(expected.pages)


def reciprocal_rank(retrieved: Sequence[RetrievedSource], expected: ExpectedSource, k: int) -> float:
    """``1 / rank`` of the first relevant chunk in the top ``k``, or 0."""
    _check_k(k)
    for rank, item in enumerate(retrieved[:k], start=1):
        if is_relevant(item, expected):
            return 1.0 / rank
    return 0.0


def first_relevant_rank(retrieved: Sequence[RetrievedSource], expected: ExpectedSource, k: int) -> Optional[int]:
    _check_k(k)
    for rank, item in enumerate(retrieved[:k], start=1):
        if is_relevant(item, expected):
            return rank
    return None


def has_wrong_version(retrieved: Sequence[RetrievedSource], expected: ExpectedSource, k: int) -> bool:
    """True when any of the top ``k`` chunks comes from a different regulation or version."""
    _check_k(k)
    return any(not same_version(item, expected) for item in retrieved[:k])


def wrong_version_share(retrieved: Sequence[RetrievedSource], expected: ExpectedSource, k: int) -> float:
    """Share of the returned top-``k`` chunks from a different regulation or version (0 when none returned)."""
    _check_k(k)
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(not same_version(item, expected) for item in top) / len(top)


def mean(values: Iterable[float]) -> Optional[float]:
    """Arithmetic mean, or ``None`` for no values (reported as "n/a")."""
    collected = list(values)
    if not collected:
        return None
    return sum(collected) / len(collected)
