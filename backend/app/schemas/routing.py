"""Validated routing decision for the adaptive question router (module M6).

Route labels follow the adaptive routing table in the CohortIQ blueprint
(Section 8.1): out-of-scope refusal, clarification when cohort facts are
missing, clause lookup, low-evidence abstention, and the general path.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

Route = Literal["out_of_scope", "clarify", "clause_lookup", "low_evidence", "general"]
RouteReason = Literal[
    "no_regulation_terms",  # out_of_scope
    "missing_cohort",  # clarify
    "clause_reference",  # clause_lookup
    "evidence_found",  # general
    "no_applicable_regulations",  # low_evidence: the cohort has no approved regulation
    "no_retrieval_results",  # low_evidence: retrieval returned nothing
    "clause_not_found",  # low_evidence: the cited clause number is not in the cohort's regulations
    "score_below_threshold",  # low_evidence: best retrieval score below the configured minimum
]

CLAUSE_LOOKUP_TOP_K = 3
"""Chunks retrieved for a clause lookup (blueprint Section 8.1: "top 3")."""

_REASONS: dict[str, frozenset[str]] = {
    "out_of_scope": frozenset({"no_regulation_terms"}),
    "clarify": frozenset({"missing_cohort"}),
    "clause_lookup": frozenset({"clause_reference"}),
    "general": frozenset({"evidence_found"}),
    "low_evidence": frozenset(
        {"no_applicable_regulations", "no_retrieval_results", "clause_not_found", "score_below_threshold"}
    ),
}


class RouteDecision(BaseModel):
    """How one question is handled, and why.

    ``best_score`` is the top BM25 score from the existing cohort-filtered
    retrieval; ``threshold_applied`` is False when no retrieval ran or the
    corpus was too small for the score threshold to be meaningful.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    route: Route
    reason: RouteReason
    clause_number: Optional[str] = Field(default=None, max_length=40)
    top_k: Optional[int] = Field(default=None, ge=1)
    best_score: Optional[float] = None
    min_score: Optional[float] = Field(default=None, ge=0)
    threshold_applied: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "RouteDecision":
        if self.reason not in _REASONS[self.route]:
            raise ValueError(f"reason {self.reason!r} is not valid for route {self.route!r}.")
        if self.route in ("out_of_scope", "clarify"):
            if self.top_k is not None or self.best_score is not None or self.threshold_applied:
                raise ValueError(f"route {self.route!r} must not carry retrieval details.")
        if self.route == "clause_lookup" and (self.clause_number is None or self.top_k != CLAUSE_LOOKUP_TOP_K):
            raise ValueError(f"clause_lookup needs a clause number and top_k={CLAUSE_LOOKUP_TOP_K}.")
        if self.reason == "clause_not_found" and self.clause_number is None:
            raise ValueError("clause_not_found needs the clause number.")
        if self.route in ("clause_lookup", "general") and self.top_k is None:
            raise ValueError(f"route {self.route!r} needs top_k.")
        if self.threshold_applied:
            if self.best_score is None or self.min_score is None:
                raise ValueError("an applied threshold needs best_score and min_score.")
            below = self.best_score < self.min_score
            if below != (self.reason == "score_below_threshold"):
                raise ValueError("score_below_threshold must match best_score < min_score.")
        elif self.reason == "score_below_threshold":
            raise ValueError("score_below_threshold requires the threshold to be applied.")
        return self

    @property
    def calls_generator(self) -> bool:
        """Whether this route may call the answer-generation model."""
        return self.route in ("clause_lookup", "general")
