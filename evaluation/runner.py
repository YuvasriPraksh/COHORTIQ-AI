"""Run the retrieval and end-to-end evaluation against a database snapshot.

Answer generation is always replaced by a stand-in that never calls a model.

Retrieval-only workflow (``app.workflow.answer_student_question``, which the
Streamlit app uses; no router):

    ``cohort_filtered``
        Only approved regulations that apply to the case's cohort are
        retrieved from. Abstention means retrieval returned no evidence.
    ``no_cohort_filter``
        A baseline that ranks chunks from *every* approved regulation, as a
        generic RAG system without the applicability rules would. It shows what
        the cohort filter prevents (wrong-version retrieval, answers for
        cohorts with no regulation).

End-to-end with the Adaptive RAG router
(``backend.app.services.query_service.answer_with_adaptive_routing``, which
``POST /api/v1/query/ask`` uses):

    ``adaptive_router``
        Each case is routed first. Abstention means the answer generator was
        not called (any non-answering route); retrieval metrics are computed on
        the evidence the generator received (top 3 for clause lookups).

The source database is never opened for writing: it is copied with SQLite's
backup API from a read-only connection, and the copy is deleted afterwards.
"""

from __future__ import annotations

import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from app.database import get_all_regulations, get_applicable_regulations
from app.models import GroundedAnswer
from app.workflow import answer_student_question, build_retrieval_corpus_for_cohort
from backend.app.services import adaptive_router, query_service
from evaluation import metrics
from evaluation.dataset import EvaluationCase, EvaluationDataset
from evaluation.metrics import RetrievedSource

COHORT_FILTERED = "cohort_filtered"
NO_COHORT_FILTER = "no_cohort_filter"
ADAPTIVE_ROUTER = "adaptive_router"
RETRIEVAL_ONLY_CONFIGURATIONS = (COHORT_FILTERED, NO_COHORT_FILTER)
END_TO_END_CONFIGURATIONS = (ADAPTIVE_ROUTER,)
CONFIGURATIONS = RETRIEVAL_ONLY_CONFIGURATIONS + END_TO_END_CONFIGURATIONS

# The defaults of answer_student_question and POST /api/v1/query/ask.
DEFAULT_TOP_K = 5
DEFAULT_CHUNKING = {"chunking_strategy": "recursive", "chunk_size": 1000, "overlap": 200}

_APPROVED = {"approved", "verified"}


class EvaluationError(Exception):
    """The evaluation cannot run (missing database, dataset/database mismatch)."""


class _NoAnswerGeneration:
    """Stands in for the Gemini service: records calls, never contacts a model."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_grounded_answer(self, **_: Any) -> GroundedAnswer:
        self.calls += 1
        return GroundedAnswer(
            answer="Answer generation is disabled during evaluation.",
            status="insufficient_evidence",
            citations=[],
            limitations="Evaluation run.",
        )


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    configuration: str
    admission_batch: str
    programme: str
    expect_abstain: bool
    abstained: bool
    retrieved: tuple[RetrievedSource, ...]
    expected: Optional[metrics.ExpectedSource]
    precision: Optional[float]
    recall: Optional[float]
    reciprocal_rank: Optional[float]
    first_relevant_rank: Optional[int]
    wrong_version: Optional[bool]
    wrong_version_share: Optional[float]
    # Set only for the end-to-end router configuration.
    route: Optional[str] = None
    route_reason: Optional[str] = None

    @property
    def abstention_correct(self) -> bool:
        return self.abstained == self.expect_abstain


@dataclass(frozen=True)
class ConfigurationSummary:
    configuration: str
    answerable_cases: int
    abstention_cases: int
    precision_at_k: Optional[float]
    recall_at_k: Optional[float]
    mrr: Optional[float]
    wrong_version_rate: Optional[float]
    wrong_version_chunk_share: Optional[float]
    abstention_accuracy: Optional[float]
    correct_abstentions: int
    missed_abstentions: int
    false_abstentions: int
    # (route, reason) -> number of cases; end-to-end router configuration only.
    route_counts: Optional[dict[str, int]] = None


@dataclass(frozen=True)
class RegulationInfo:
    document_name: str
    regulation_version: str
    applicable_batches: tuple[str, ...]
    applicable_programmes: tuple[str, ...]
    verification_status: Optional[str]


@dataclass
class EvaluationResult:
    dataset_name: str
    dataset_description: str
    dataset_size: int
    top_k: int
    chunking: dict[str, Any]
    configurations: tuple[str, ...]
    regulations: tuple[RegulationInfo, ...]
    cohorts_with_multiple_regulations: tuple[tuple[str, str], ...]
    router_min_score: Optional[float] = None
    results: list[CaseResult] = field(default_factory=list)
    summaries: dict[str, ConfigurationSummary] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Database snapshot
# --------------------------------------------------------------------------- #


def snapshot_database(source: str | Path, destination: Path) -> Path:
    """Copy ``source`` to ``destination`` without ever opening ``source`` for writing."""
    source_path = Path(source)
    if not source_path.is_file():
        raise EvaluationError(f"Database not found: {source_path}")
    source_uri = source_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True)) as reader, closing(sqlite3.connect(destination)) as writer:
        reader.backup(writer)
    return destination


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _approved(regulation: dict[str, Any]) -> bool:
    return str(regulation.get("verification_status") or "").strip().lower() in _APPROVED


def _sources(results: Sequence[dict[str, Any]]) -> tuple[RetrievedSource, ...]:
    sources = []
    for item in results:
        page = item.get("page_number")
        sources.append(
            RetrievedSource(
                document_name=None if item.get("document_name") is None else str(item["document_name"]),
                regulation_version=None if item.get("regulation_version") is None else str(item["regulation_version"]),
                page_number=int(page) if page is not None else None,
            )
        )
    return tuple(sources)


def check_dataset_against_database(dataset: EvaluationDataset, db_path: str | Path) -> list[str]:
    """Return problems that make the dataset unusable with this database (empty when it matches)."""
    approved = {
        (str(reg["document_name"]), str(reg["regulation_version"]))
        for reg in get_all_regulations(db_path=db_path)
        if _approved(reg)
    }
    return [
        f"Expected regulation {name!r} version {version!r} is not an approved regulation in the database."
        for name, version in sorted(dataset.expected_versions() - approved)
    ]


def _all_approved_chunks(db_path: Path, chunking: dict[str, Any]) -> list[dict[str, Any]]:
    """Chunks of every approved regulation, built exactly as the cohort corpus builds them."""
    chunks: dict[tuple[Any, Any], dict[str, Any]] = {}
    for regulation in get_all_regulations(db_path=db_path):
        if not _approved(regulation) or not regulation["applicable_batches"] or not regulation["applicable_programmes"]:
            continue
        corpus = build_retrieval_corpus_for_cohort(
            regulation["applicable_batches"][0], regulation["applicable_programmes"][0], db_path=db_path, **chunking
        )
        for chunk in corpus.get("chunks", []):
            chunks.setdefault((chunk.get("regulation_id"), chunk.get("chunk_id")), chunk)
    return list(chunks.values())


def _cohorts_with_multiple_regulations(dataset: EvaluationDataset, db_path: Path) -> tuple[tuple[str, str], ...]:
    cohorts = sorted({(case.admission_batch, case.programme) for case in dataset.cases if not case.expect_abstain})
    return tuple(
        cohort for cohort in cohorts if len(get_applicable_regulations(cohort[0], cohort[1], db_path=db_path)) > 1
    )


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #


def _run_case(
    case: EvaluationCase,
    configuration: str,
    db_path: Path,
    top_k: int,
    chunking: dict[str, Any],
    baseline_chunks: Optional[list[dict[str, Any]]],
) -> CaseResult:
    generator = _NoAnswerGeneration()
    evidence = None
    if configuration == NO_COHORT_FILTER:
        # Every approved regulation, made "applicable" to this cohort, so the filter removes nothing.
        evidence = [
            {**chunk, "applicable_batches": [case.admission_batch], "applicable_programmes": [case.programme]}
            for chunk in baseline_chunks or []
        ]
    outcome = answer_student_question(
        case.admission_batch,
        case.programme,
        case.question,
        db_path=db_path,
        top_k=top_k,
        evidence_chunks=evidence,
        gemini_service=generator,
        **chunking,
    )
    retrieval = outcome.get("retrieval") or {}
    retrieved = _sources(retrieval.get("results") or [])
    # Retrieval-stage abstention: no evidence, so the workflow answers without calling the model.
    abstained = retrieval.get("status") != "ok" or not retrieved
    if abstained != (generator.calls == 0):
        raise EvaluationError(f"Case {case.id!r}: retrieval outcome and generator calls disagree.")
    return _score(case, configuration, retrieved, abstained, top_k)


def _run_routed_case(
    case: EvaluationCase,
    db_path: Path,
    top_k: int,
    chunking: dict[str, Any],
    min_score: float,
) -> CaseResult:
    """End-to-end: the API's routed service, with the stand-in generator."""
    generator = _NoAnswerGeneration()
    outcome = query_service.answer_with_adaptive_routing(
        case.admission_batch,
        case.programme,
        case.question,
        db_path=db_path,
        top_k=top_k,
        min_score=min_score,
        gemini_service=generator,
        **chunking,
    )
    route = outcome.get("route") or {}
    if route.get("route") is None:
        raise EvaluationError(f"Case {case.id!r}: the routed service returned no routing decision.")
    # End-to-end abstention: the answer generator was not called.
    abstained = generator.calls == 0
    answering_route = route["route"] in ("clause_lookup", "general")
    if abstained == answering_route:
        raise EvaluationError(f"Case {case.id!r}: route {route['route']!r} and generator calls disagree.")
    retrieved = () if abstained else _sources((outcome.get("retrieval") or {}).get("results") or [])
    return _score(case, ADAPTIVE_ROUTER, retrieved, abstained, top_k, route["route"], route.get("reason"))


def _score(
    case: EvaluationCase,
    configuration: str,
    retrieved: tuple[RetrievedSource, ...],
    abstained: bool,
    top_k: int,
    route: Optional[str] = None,
    route_reason: Optional[str] = None,
) -> CaseResult:
    expected = case.expected.as_source() if case.expected is not None else None
    scores: dict[str, Any] = {
        "precision": None, "recall": None, "reciprocal_rank": None, "first_relevant_rank": None,
        "wrong_version": None, "wrong_version_share": None,
    }
    if expected is not None:
        scores = {
            "precision": metrics.precision_at_k(retrieved, expected, top_k),
            "recall": metrics.recall_at_k(retrieved, expected, top_k),
            "reciprocal_rank": metrics.reciprocal_rank(retrieved, expected, top_k),
            "first_relevant_rank": metrics.first_relevant_rank(retrieved, expected, top_k),
            "wrong_version": metrics.has_wrong_version(retrieved, expected, top_k),
            "wrong_version_share": metrics.wrong_version_share(retrieved, expected, top_k),
        }
    return CaseResult(
        case_id=case.id,
        category=case.category,
        configuration=configuration,
        admission_batch=case.admission_batch,
        programme=case.programme,
        expect_abstain=case.expect_abstain,
        abstained=abstained,
        retrieved=retrieved,
        expected=expected,
        route=route,
        route_reason=route_reason,
        **scores,
    )


def summarize(configuration: str, results: Sequence[CaseResult]) -> ConfigurationSummary:
    answerable = [r for r in results if not r.expect_abstain]
    abstention = [r for r in results if r.expect_abstain]
    return ConfigurationSummary(
        configuration=configuration,
        answerable_cases=len(answerable),
        abstention_cases=len(abstention),
        precision_at_k=metrics.mean(r.precision for r in answerable),
        recall_at_k=metrics.mean(r.recall for r in answerable),
        mrr=metrics.mean(r.reciprocal_rank for r in answerable),
        wrong_version_rate=metrics.mean(float(r.wrong_version) for r in answerable),
        wrong_version_chunk_share=metrics.mean(r.wrong_version_share for r in answerable),
        abstention_accuracy=metrics.mean(float(r.abstention_correct) for r in results),
        correct_abstentions=sum(r.abstained for r in abstention),
        missed_abstentions=sum(not r.abstained for r in abstention),
        false_abstentions=sum(r.abstained for r in answerable),
        route_counts=(
            dict(sorted(Counter(f"{r.route}/{r.route_reason}" for r in results).items()))
            if any(r.route is not None for r in results)
            else None
        ),
    )


def run_evaluation(
    dataset: EvaluationDataset,
    db_path: str | Path,
    *,
    top_k: int = DEFAULT_TOP_K,
    configurations: Sequence[str] = CONFIGURATIONS,
    chunking: Optional[dict[str, Any]] = None,
) -> EvaluationResult:
    """Evaluate ``dataset`` against a snapshot of ``db_path``.

    Raises:
        EvaluationError: the database is missing or lacks a regulation the dataset expects.
        ValueError: ``top_k`` or a configuration name is invalid.
    """
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer.")
    unknown = [name for name in configurations if name not in CONFIGURATIONS]
    if unknown or not configurations:
        raise ValueError(f"configurations must be chosen from {', '.join(CONFIGURATIONS)}.")
    settings = {**DEFAULT_CHUNKING, **(chunking or {})}
    router_min_score = adaptive_router.configured_min_score() if ADAPTIVE_ROUTER in configurations else None

    with tempfile.TemporaryDirectory(prefix="cohortiq-eval-") as workdir:
        snapshot = snapshot_database(db_path, Path(workdir) / "snapshot.db")
        problems = check_dataset_against_database(dataset, snapshot)
        if problems:
            raise EvaluationError(" ".join(problems))

        regulations = tuple(
            RegulationInfo(
                document_name=str(reg["document_name"]),
                regulation_version=str(reg["regulation_version"]),
                applicable_batches=tuple(reg["applicable_batches"]),
                applicable_programmes=tuple(reg["applicable_programmes"]),
                verification_status=reg.get("verification_status"),
            )
            for reg in get_all_regulations(db_path=snapshot)
        )
        result = EvaluationResult(
            dataset_name=dataset.name,
            dataset_description=dataset.description,
            dataset_size=len(dataset.cases),
            top_k=top_k,
            chunking=settings,
            configurations=tuple(configurations),
            regulations=regulations,
            cohorts_with_multiple_regulations=_cohorts_with_multiple_regulations(dataset, snapshot),
            router_min_score=router_min_score,
        )
        baseline_chunks = _all_approved_chunks(snapshot, settings) if NO_COHORT_FILTER in configurations else None
        for configuration in configurations:
            if configuration == ADAPTIVE_ROUTER:
                config_results = [
                    _run_routed_case(case, snapshot, top_k, settings, router_min_score) for case in dataset.cases
                ]
            else:
                config_results = [
                    _run_case(case, configuration, snapshot, top_k, settings, baseline_chunks) for case in dataset.cases
                ]
            result.results.extend(config_results)
            result.summaries[configuration] = summarize(configuration, config_results)
    return result
