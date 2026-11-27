"""Adaptive question router (module M6: Adaptive RAG).

Decides, before any answer is generated, whether a question should be refused,
clarified, answered by clause lookup or by the general path, or abstained on.
It is deterministic: no model is called. Routes and their order:

1. ``out_of_scope``: the question contains no academic-regulation term, so it
   is refused without retrieval or generation. Checked first, because asking
   for a cohort before refusing an unrelated question is pointless.
2. ``clarify``: admission batch or programme is missing. Applicability (and so
   the right regulation) depends on the cohort, so nothing is retrieved.
3. ``clause_lookup``: the question cites a clause or section number. The
   existing cohort- and approval-filtered BM25 retrieval runs with top 3. If the
   clause number does not occur in the cohort's regulations, it abstains
   (``low_evidence``/``clause_not_found``).
4. ``low_evidence``: no applicable regulation, no retrieval results, or (for
   non-clause questions) a best retrieval score below the minimum. No answer
   is generated.
5. ``general``: everything else uses the existing retrieval-and-answer path.

Why these signals (calibrated on the project database, see
``evaluation/reports/routing_v1_report.md``):

- Raw BM25 scores separate answerable from unanswerable questions poorly here.
  The regulation text rarely contains question words ("what", "who"), so
  unrelated questions still score about 3-7, while short answerable questions
  can score below 5. Out-of-scope detection therefore uses a vocabulary check,
  not the score.
- The score threshold is a conservative floor: ``DEFAULT_MIN_RETRIEVAL_SCORE``
  (3.0) is below the lowest best score of any answerable labelled question
  (3.75), so on current data it never abstains on an answerable question, while
  stopping answers built on chunks that share no or only incidental terms with
  the question (today a top chunk can score 0.0 and still reach the model).
- BM25 term weights depend on corpus size: in a one-chunk corpus a matching
  term scores below zero, in a two-chunk corpus exactly zero. The threshold is
  only applied when the corpus has at least ``MIN_CHUNKS_FOR_THRESHOLD`` (20)
  chunks, about a fifth of the smallest calibration corpus (96 chunks).
- Short clause lookups score low even when the clause exists (3.5-8.1 in
  calibration, close to the floor), so a clause lookup abstains only when the
  exact clause number is absent from the cohort's regulations; the score
  threshold is not applied to a verified clause.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from app import workflow
from app.retrieval import retrieve_relevant_chunks, tokenize_text
from backend.app.schemas.routing import CLAUSE_LOOKUP_TOP_K, RouteDecision

MIN_SCORE_ENV = "RETRIEVAL_MIN_SCORE"
DEFAULT_MIN_RETRIEVAL_SCORE = 3.0
MIN_CHUNKS_FOR_THRESHOLD = 20

# Terms that mark a question as being about academic regulations. Derived from
# the section topics of the regulations (admission, attendance, assessment,
# examinations, grading, credits, progression, degree award, discipline).
# Deliberately excludes generic words such as "student", "college" or "rule
# book" readers might use for any campus topic.
REGULATION_TERMS = frozenset(
    {
        # Admission and programme structure
        "admission", "admitted", "eligibility", "eligible", "lateral", "programme", "program",
        "degree", "semester", "semesters", "course", "courses", "subject", "subjects", "elective",
        "electives", "credit", "credits", "curriculum", "syllabus", "duration", "honours", "honors",
        "internship", "project", "mooc", "nptel", "swayam",
        # Attendance
        "attendance", "condonation", "absence", "absent",
        # Assessment and examinations
        "exam", "exams", "examination", "examinations", "assessment", "internal", "cam", "ese", "esm",
        "marks", "mark", "pass", "passing", "passed", "fail", "failed", "failure", "arrear", "arrears",
        "backlog", "supplementary", "revaluation", "re-valuation", "re-evaluation", "photocopy",
        "grievance", "result", "results",
        # Grading and award
        "grade", "grades", "grading", "gpa", "cgpa", "sgpa", "distinction", "class", "rank", "medal",
        "classification",
        # Progression, breaks and discipline
        "withdraw", "withdrawal", "break", "rejoin", "rejoining", "discontinue", "termination",
        "terminated", "suspension", "suspended", "discipline", "disciplinary", "misconduct",
        "malpractice", "ragging",
        # Referring to the regulations themselves
        "regulation", "regulations", "rule", "rules", "clause", "section", "fee", "fees",
    }
)

_CLAUSE_PATTERN = re.compile(
    r"\b(?:clause|section|sec\.?|cl\.?)\s*(?:no\.?\s*)?(\d+(?:\.\d+)*(?:\([a-z0-9]+\))?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RoutingOutcome:
    """The decision, plus the corpus and retrieval it was based on (for the answer step)."""

    decision: RouteDecision
    corpus: Optional[dict[str, Any]] = None
    retrieval: Optional[dict[str, Any]] = None
    corpus_chunks: list[dict[str, Any]] = field(default_factory=list)


def configured_min_score() -> float:
    """The minimum best retrieval score, from ``RETRIEVAL_MIN_SCORE`` or the default.

    Raises:
        ValueError: the environment value is not a finite number >= 0.
    """
    raw = os.getenv(MIN_SCORE_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_MIN_RETRIEVAL_SCORE
    try:
        value = float(raw.strip())
    except ValueError:
        raise ValueError(f"Invalid configuration: {MIN_SCORE_ENV} must be a number.") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid configuration: {MIN_SCORE_ENV} must be a finite number >= 0.")
    return value


def detect_clause_reference(question: str) -> Optional[str]:
    """Return the clause number a question cites ("clause 10.1", "section 12.2.2"), lowercased."""
    match = _CLAUSE_PATTERN.search(question or "")
    return match.group(1).lower() if match else None


def has_regulation_terms(question: str) -> bool:
    """True when the question uses at least one academic-regulation term (simple plurals included)."""
    for token in tokenize_text(question):
        if token in REGULATION_TERMS or (token.endswith("s") and token[:-1] in REGULATION_TERMS):
            return True
    return False


def _clause_in_corpus(clause: str, chunks: Sequence[dict[str, Any]]) -> bool:
    for chunk in chunks:
        text = chunk.get("chunk_text") or chunk.get("chunk text") or ""
        if clause in tokenize_text(str(text)):
            return True
    return False


def _blank(value: Any) -> bool:
    return value is None or not str(value).strip()


def route_question(
    question: str,
    admission_batch: Optional[str],
    programme: Optional[str],
    *,
    db_path: str | Path | None = None,
    top_k: int = 5,
    chunking_strategy: str = "recursive",
    chunk_size: int = 1000,
    overlap: int = 200,
    min_score: Optional[float] = None,
    min_chunks_for_threshold: int = MIN_CHUNKS_FOR_THRESHOLD,
) -> RoutingOutcome:
    """Decide how to handle a question. Never calls a model.

    Retrieval uses the existing workflow functions, so cohort applicability and
    approved-only filtering are exactly those of the answer path.
    """
    threshold = configured_min_score() if min_score is None else float(min_score)
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("min_score must be a finite number >= 0.")
    text = (question or "").strip()

    if not has_regulation_terms(text):
        return RoutingOutcome(RouteDecision(route="out_of_scope", reason="no_regulation_terms"))
    if _blank(admission_batch) or _blank(programme):
        return RoutingOutcome(RouteDecision(route="clarify", reason="missing_cohort"))

    batch, prog = str(admission_batch).strip(), str(programme).strip()
    clause = detect_clause_reference(text)
    depth = CLAUSE_LOOKUP_TOP_K if clause else top_k

    corpus = workflow.build_retrieval_corpus_for_cohort(
        admission_batch=batch,
        programme=prog,
        db_path=db_path,
        chunking_strategy=chunking_strategy,
        chunk_size=chunk_size,
        overlap=overlap,
    )
    chunks = list(corpus.get("chunks") or [])
    if corpus.get("status") != "ok" or not chunks:
        return RoutingOutcome(
            RouteDecision(route="low_evidence", reason="no_applicable_regulations", clause_number=clause, top_k=depth),
            corpus=corpus,
        )
    if clause and not _clause_in_corpus(clause, chunks):
        return RoutingOutcome(
            RouteDecision(route="low_evidence", reason="clause_not_found", clause_number=clause, top_k=depth),
            corpus=corpus,
            corpus_chunks=chunks,
        )

    retrieval = retrieve_relevant_chunks(
        question=text, admission_batch=batch, programme=prog, chunks=chunks, top_k=depth, approved_only=True
    )
    results = retrieval.get("results") or []
    if retrieval.get("status") != "ok" or not results:
        return RoutingOutcome(
            RouteDecision(route="low_evidence", reason="no_retrieval_results", clause_number=clause, top_k=depth),
            corpus=corpus,
            retrieval=retrieval,
            corpus_chunks=chunks,
        )

    best = float(results[0].get("retrieval_score") or 0.0)
    # A verified clause number is the evidence for a clause lookup; its short
    # question scores close to the floor (3.5-6.6 in calibration), so the
    # score threshold is not applied to it.
    applied = clause is None and len(chunks) >= min_chunks_for_threshold
    details = dict(clause_number=clause, top_k=depth, best_score=best, min_score=threshold, threshold_applied=applied)
    if applied and best < threshold:
        decision = RouteDecision(route="low_evidence", reason="score_below_threshold", **details)
    elif clause:
        decision = RouteDecision(route="clause_lookup", reason="clause_reference", **details)
    else:
        decision = RouteDecision(route="general", reason="evidence_found", **details)
    return RoutingOutcome(decision, corpus=corpus, retrieval=retrieval, corpus_chunks=chunks)
