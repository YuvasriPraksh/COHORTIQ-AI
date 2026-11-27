"""Tests for the offline retrieval evaluation package (``evaluation/``, module M7).

Runner and CLI tests use a synthetic database in a temporary directory; the
project database is never used. No model is called.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from app import workflow
from app.database import init_database, insert_regulation_with_pages
from evaluation import metrics
from evaluation.__main__ import EXIT_FAILED, EXIT_OK, main
from evaluation.dataset import DEFAULT_DATASET, EvaluationDataset, load_dataset
from evaluation.metrics import ExpectedSource, RetrievedSource
from evaluation.report import render_markdown, to_json
from evaluation.runner import (
    ADAPTIVE_ROUTER,
    COHORT_FILTERED,
    NO_COHORT_FILTER,
    CaseResult,
    EvaluationError,
    run_evaluation,
    summarize,
)

EXPECTED = ExpectedSource("Rulebook", "2023", frozenset({3, 4}))


def src(page: int | None, name: str = "Rulebook", version: str = "2023") -> RetrievedSource:
    return RetrievedSource(name, version, page)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def test_precision_counts_relevant_chunks_over_k() -> None:
    retrieved = [src(3), src(9), src(4), src(3), src(1)]
    assert metrics.precision_at_k(retrieved, EXPECTED, 5) == pytest.approx(3 / 5)
    assert metrics.precision_at_k(retrieved, EXPECTED, 1) == 1.0
    assert metrics.precision_at_k(retrieved, EXPECTED, 2) == 0.5


def test_precision_treats_missing_slots_as_not_relevant() -> None:
    assert metrics.precision_at_k([src(3)], EXPECTED, 5) == pytest.approx(1 / 5)
    assert metrics.precision_at_k([], EXPECTED, 5) == 0.0


def test_recall_counts_each_expected_page_once() -> None:
    assert metrics.recall_at_k([src(3), src(3), src(3)], EXPECTED, 5) == 0.5
    assert metrics.recall_at_k([src(3), src(1), src(4)], EXPECTED, 3) == 1.0
    assert metrics.recall_at_k([src(3), src(1), src(4)], EXPECTED, 2) == 0.5


def test_reciprocal_rank_uses_the_first_relevant_chunk() -> None:
    assert metrics.reciprocal_rank([src(1), src(9), src(4)], EXPECTED, 5) == pytest.approx(1 / 3)
    assert metrics.first_relevant_rank([src(1), src(9), src(4)], EXPECTED, 5) == 3
    assert metrics.reciprocal_rank([src(1), src(9), src(4)], EXPECTED, 2) == 0.0
    assert metrics.first_relevant_rank([], EXPECTED, 5) is None


def test_relevance_requires_the_expected_document_and_version() -> None:
    other_version = src(3, version="2020")
    other_document = src(3, name="Other")

    assert not metrics.is_relevant(other_version, EXPECTED)
    assert not metrics.is_relevant(other_document, EXPECTED)
    assert metrics.precision_at_k([other_version, other_document], EXPECTED, 2) == 0.0
    assert metrics.recall_at_k([other_version], EXPECTED, 1) == 0.0


def test_wrong_version_detection_and_share() -> None:
    retrieved = [src(3), src(3, version="2020"), src(8), src(2, name="Other")]

    assert metrics.has_wrong_version(retrieved, EXPECTED, 4)
    assert not metrics.has_wrong_version(retrieved, EXPECTED, 1)
    assert metrics.wrong_version_share(retrieved, EXPECTED, 4) == 0.5
    assert metrics.wrong_version_share(retrieved, EXPECTED, 3) == pytest.approx(1 / 3)
    assert metrics.wrong_version_share([], EXPECTED, 3) == 0.0
    assert not metrics.has_wrong_version([], EXPECTED, 3)


@pytest.mark.parametrize("k", [0, -1, True, 1.5])
def test_k_must_be_a_positive_integer(k: Any) -> None:
    for function in (metrics.precision_at_k, metrics.recall_at_k, metrics.reciprocal_rank, metrics.has_wrong_version):
        with pytest.raises(ValueError):
            function([src(3)], EXPECTED, k)


def test_mean_of_nothing_is_none() -> None:
    assert metrics.mean([]) is None
    assert metrics.mean([1.0, 0.0, 0.5]) == 0.5


def _case(case_id: str, *, expect_abstain: bool, abstained: bool, **scores: Any) -> CaseResult:
    defaults = dict(precision=None, recall=None, reciprocal_rank=None, first_relevant_rank=None,
                    wrong_version=None, wrong_version_share=None)
    defaults.update(scores)
    return CaseResult(
        case_id=case_id, category="c", configuration=COHORT_FILTERED, admission_batch="2023", programme="CSE",
        expect_abstain=expect_abstain, abstained=abstained, retrieved=(),
        expected=None if expect_abstain else EXPECTED, **defaults,
    )


def test_summary_averages_answerable_cases_and_counts_abstentions() -> None:
    results = [
        _case("a", expect_abstain=False, abstained=False, precision=0.4, recall=1.0, reciprocal_rank=1.0,
              wrong_version=False, wrong_version_share=0.0),
        _case("b", expect_abstain=False, abstained=True, precision=0.0, recall=0.0, reciprocal_rank=0.0,
              wrong_version=False, wrong_version_share=0.0),
        _case("c", expect_abstain=False, abstained=False, precision=0.2, recall=0.5, reciprocal_rank=0.5,
              wrong_version=True, wrong_version_share=0.4),
        _case("d", expect_abstain=True, abstained=True),
        _case("e", expect_abstain=True, abstained=False),
    ]

    summary = summarize(COHORT_FILTERED, results)

    assert (summary.answerable_cases, summary.abstention_cases) == (3, 2)
    assert summary.precision_at_k == pytest.approx(0.2)
    assert summary.recall_at_k == pytest.approx(0.5)
    assert summary.mrr == pytest.approx(0.5)
    assert summary.wrong_version_rate == pytest.approx(1 / 3)
    assert summary.wrong_version_chunk_share == pytest.approx(0.4 / 3)
    assert summary.abstention_accuracy == pytest.approx(3 / 5)  # a, c, d correct
    assert (summary.correct_abstentions, summary.missed_abstentions, summary.false_abstentions) == (1, 1, 1)


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #


def _dataset_dict(**overrides: Any) -> dict[str, Any]:
    data = {
        "name": "synthetic",
        "relevance_unit": "page",
        "cases": [
            {
                "id": "attendance-a", "category": "attendance",
                "question": "How much attendance is needed to sit examinations?",
                "admission_batch": "2021", "programme": "CSE",
                "expected": {"document_name": "Rulebook A", "regulation_version": "2021", "pages": [1]},
                "expect_abstain": False,
            },
            {
                "id": "attendance-b", "category": "attendance",
                "question": "How much attendance is needed to sit examinations?",
                "admission_batch": "2023", "programme": "CSE",
                "expected": {"document_name": "Rulebook B", "regulation_version": "2023", "pages": [2]},
                "expect_abstain": False,
            },
            {
                "id": "abstain-no-regulation", "category": "abstention",
                "question": "How much attendance is needed to sit examinations?",
                "admission_batch": "2019", "programme": "CSE", "expected": None, "expect_abstain": True,
            },
        ],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["cases"][0].update(expect_abstain=True),  # abstaining case with expected pages
        lambda d: d["cases"][2].update(expect_abstain=False),  # answerable case without expected pages
        lambda d: d["cases"][1].update(id="attendance-a"),  # duplicate id
        lambda d: d["cases"][0]["expected"].update(pages=[]),
        lambda d: d["cases"][0]["expected"].update(pages=[0]),
        lambda d: d["cases"][0]["expected"].update(pages=[1, 1]),
        lambda d: d["cases"][0].update(unknown_field="x"),
        lambda d: d.update(relevance_unit="chunk"),
        lambda d: d.update(cases=[]),
    ],
)
def test_invalid_datasets_are_rejected(mutate: Any) -> None:
    data = _dataset_dict()
    mutate(data)
    with pytest.raises(ValueError):
        EvaluationDataset.model_validate(data)


def test_packaged_dataset_is_valid_and_labelled() -> None:
    dataset = load_dataset(DEFAULT_DATASET)

    assert dataset.name == "cohortiq-retrieval-v1"
    assert len(dataset.cases) == 20
    answerable = [case for case in dataset.cases if not case.expect_abstain]
    assert len(answerable) == 17
    assert all(case.expected and case.expected.pages and case.reference_answer for case in answerable)
    assert dataset.expected_versions() == {("SMVEC", "2023"), ("regulation 2", "2024")}
    assert {case.category for case in dataset.cases} >= {"attendance", "abstention", "passing"}


# --------------------------------------------------------------------------- #
# Runner and CLI (synthetic database)
# --------------------------------------------------------------------------- #

FILLER = [
    "Library rules: books may be borrowed for fourteen days from the central library.",
    "Hostel accommodation is allotted by the warden based on distance from home.",
    "Sports facilities include a cricket ground, a gymnasium and indoor courts.",
]


def _seed(db_path: Path) -> None:
    init_database(db_path)

    def add(name: str, version: str, batches: list[str], status: str, pages: list[str]) -> None:
        insert_regulation_with_pages(
            {
                "document_name": name, "regulation_version": version, "effective_date": "2024-01-01",
                "applicable_batches": batches, "applicable_programmes": ["CSE"], "upload_date": "2024-01-01",
                "total_pages": len(pages), "processing_status": "extracted", "verification_status": status,
            },
            [{"page_number": n, "extracted_text": text, "extraction_status": "success"} for n, text in enumerate(pages, 1)],
            db_path=db_path,
        )

    add("Rulebook A", "2021", ["2021"], "approved", [
        "Attendance: students need seventy percent attendance to sit examinations.",
        "Grading: an S grade carries ten grade points.",
        *FILLER,
    ])
    add("Rulebook B", "2023", ["2023"], "approved", [
        "Grading table: an S grade carries ten grade points.",
        "Attendance: students need eighty percent attendance to sit end semester examinations.",
        *FILLER,
    ])
    # Pending: must never be retrieved, in any configuration.
    add("Draft Rulebook", "2024", ["2021", "2023"], "pending", [
        "Attendance: draft rule says students need fifty percent attendance to sit examinations.",
    ])


@pytest.fixture
def synthetic(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "eval-source.db"
    _seed(db_path)
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(_dataset_dict()), encoding="utf-8")
    return db_path, dataset_path


@pytest.fixture(autouse=True)
def _no_model_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_: Any) -> Any:
        raise AssertionError("The evaluation must never call the answer-generation model.")

    monkeypatch.setattr(workflow, "generate_grounded_answer", forbidden)


def _fingerprint(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def test_cohort_filtered_run_scores_the_production_path(synthetic: tuple[Path, Path]) -> None:
    db_path, dataset_path = synthetic

    result = run_evaluation(load_dataset(dataset_path), db_path, top_k=2, configurations=[COHORT_FILTERED])
    by_id = {r.case_id: r for r in result.results}

    a, b = by_id["attendance-a"], by_id["attendance-b"]
    assert a.retrieved[0] == RetrievedSource("Rulebook A", "2021", 1)
    assert b.retrieved[0] == RetrievedSource("Rulebook B", "2023", 2)
    for case in (a, b):
        assert (case.reciprocal_rank, case.recall, case.precision) == (1.0, 1.0, 0.5)
        assert case.wrong_version is False and not case.abstained
    assert by_id["abstain-no-regulation"].abstained and by_id["abstain-no-regulation"].abstention_correct

    summary = result.summaries[COHORT_FILTERED]
    assert (summary.mrr, summary.recall_at_k, summary.wrong_version_rate, summary.abstention_accuracy) == (1.0, 1.0, 0.0, 1.0)
    assert all(item.document_name != "Draft Rulebook" for r in result.results for item in r.retrieved)


def test_baseline_without_cohort_filter_exposes_wrong_versions(synthetic: tuple[Path, Path]) -> None:
    db_path, dataset_path = synthetic

    result = run_evaluation(load_dataset(dataset_path), db_path, top_k=2, configurations=[NO_COHORT_FILTER])
    by_id = {r.case_id: r for r in result.results}

    # Both attendance pages are retrieved for both cohorts, so each case gets the other version too.
    for case_id in ("attendance-a", "attendance-b"):
        assert by_id[case_id].wrong_version is True
        assert {item.document_name for item in by_id[case_id].retrieved} == {"Rulebook A", "Rulebook B"}
    # Without the filter, a cohort with no regulation still gets evidence.
    assert not by_id["abstain-no-regulation"].abstained
    summary = result.summaries[NO_COHORT_FILTER]
    assert summary.wrong_version_rate == 1.0
    assert summary.missed_abstentions == 1
    assert all(item.document_name != "Draft Rulebook" for r in result.results for item in r.retrieved)


def test_source_database_is_never_modified(synthetic: tuple[Path, Path]) -> None:
    db_path, dataset_path = synthetic
    before = _fingerprint(db_path)

    run_evaluation(load_dataset(dataset_path), db_path, top_k=2)

    assert _fingerprint(db_path) == before


def test_dataset_must_match_the_database(synthetic: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, _ = synthetic
    data = _dataset_dict()
    data["cases"][0]["expected"]["regulation_version"] = "1999"

    with pytest.raises(EvaluationError, match="1999"):
        run_evaluation(EvaluationDataset.model_validate(data), db_path)


def test_pending_regulations_do_not_count_as_available(synthetic: tuple[Path, Path]) -> None:
    db_path, _ = synthetic
    data = _dataset_dict()
    data["cases"][0]["expected"].update(document_name="Draft Rulebook", regulation_version="2024")

    with pytest.raises(EvaluationError, match="Draft Rulebook"):
        run_evaluation(EvaluationDataset.model_validate(data), db_path)


@pytest.mark.parametrize("top_k", [0, -2, True])
def test_invalid_top_k_is_rejected(synthetic: tuple[Path, Path], top_k: Any) -> None:
    db_path, dataset_path = synthetic
    with pytest.raises(ValueError):
        run_evaluation(load_dataset(dataset_path), db_path, top_k=top_k)


def test_unknown_configuration_is_rejected(synthetic: tuple[Path, Path]) -> None:
    db_path, dataset_path = synthetic
    with pytest.raises(ValueError):
        run_evaluation(load_dataset(dataset_path), db_path, configurations=["reranked"])


def test_report_states_metrics_and_what_is_not_measured(synthetic: tuple[Path, Path]) -> None:
    db_path, dataset_path = synthetic
    result = run_evaluation(load_dataset(dataset_path), db_path, top_k=2)

    report = render_markdown(result)
    payload = json.loads(to_json(result))

    assert "| Configuration | Precision@2 | Recall@2 | MRR |" in report
    assert "Cases:** 3 (2 answerable, 1 expecting abstention)" in report
    assert "faithfulness and answer relevancy are **not evaluated**" in report
    assert "Citation validity is **not evaluated**" in report
    assert "## Limitations" in report and "## Per-case results" in report
    assert set(payload["summaries"]) == {COHORT_FILTERED, NO_COHORT_FILTER, ADAPTIVE_ROUTER}
    assert payload["paths"] == {"retrieval_only": [COHORT_FILTERED, NO_COHORT_FILTER], "end_to_end": [ADAPTIVE_ROUTER]}
    assert len(payload["cases"]) == 9
    assert payload["not_measured"] == ["answer faithfulness", "answer relevancy", "citation validity"]


def test_cli_writes_markdown_and_json(synthetic: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, dataset_path = synthetic
    report_path, json_path = tmp_path / "out" / "report.md", tmp_path / "out" / "results.json"
    out = io.StringIO()

    code = main(
        ["--db-path", str(db_path), "--dataset", str(dataset_path), "--top-k", "2",
         "--output", str(report_path), "--json", str(json_path)],
        out=out, err=io.StringIO(),
    )

    assert code == EXIT_OK
    assert "# CohortIQ retrieval and end-to-end evaluation" in report_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["top_k"] == 2
    assert "Report written" in out.getvalue()


def test_cli_prints_the_report_by_default(synthetic: tuple[Path, Path]) -> None:
    db_path, dataset_path = synthetic
    out = io.StringIO()

    code = main(["--db-path", str(db_path), "--dataset", str(dataset_path), "--configuration", COHORT_FILTERED],
                out=out, err=io.StringIO())

    assert code == EXIT_OK
    text = out.getvalue()
    assert "## A. Retrieval-only workflow (baseline)" in text
    assert "| Retrieval-only workflow, cohort-filtered (no router) |" in text
    assert "no cohort filter (all approved" not in text
    assert "## B. End-to-end" not in text  # only the requested configuration runs


def test_cli_fails_cleanly_for_a_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    err = io.StringIO()

    code = main(["--db-path", str(missing)], out=io.StringIO(), err=err)

    assert code == EXIT_FAILED
    assert "Database not found" in err.getvalue()
    assert not missing.exists()  # never created


def test_cli_fails_cleanly_for_a_mismatched_or_invalid_dataset(synthetic: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, _ = synthetic
    err = io.StringIO()
    assert main(["--db-path", str(db_path)], out=io.StringIO(), err=err) == EXIT_FAILED  # packaged dataset vs synthetic DB
    assert "not an approved regulation" in err.getvalue()

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    err = io.StringIO()
    assert main(["--db-path", str(db_path), "--dataset", str(broken)], out=io.StringIO(), err=err) == EXIT_FAILED
    assert "could not load the dataset" in err.getvalue()

    err = io.StringIO()
    assert main(["--db-path", str(db_path), "--top-k", "0"], out=io.StringIO(), err=err) == EXIT_FAILED


# --------------------------------------------------------------------------- #
# End-to-end path with the Adaptive RAG router
# --------------------------------------------------------------------------- #


def _with_cases(*extra: dict[str, Any]) -> EvaluationDataset:
    data = _dataset_dict()
    data["cases"].extend(extra)
    return EvaluationDataset.model_validate(data)


CRICKET_CASE = {
    "id": "abstain-out-of-scope", "category": "abstention", "question": "Who won the cricket world cup in 2011?",
    "admission_batch": "2023", "programme": "CSE", "expected": None, "expect_abstain": True,
}


def test_end_to_end_router_reports_routes_and_abstains_where_retrieval_cannot(synthetic: tuple[Path, Path]) -> None:
    db_path, _ = synthetic

    result = run_evaluation(_with_cases(CRICKET_CASE), db_path, top_k=2, configurations=[COHORT_FILTERED, ADAPTIVE_ROUTER])
    routed = {r.case_id: r for r in result.results if r.configuration == ADAPTIVE_ROUTER}
    plain = {r.case_id: r for r in result.results if r.configuration == COHORT_FILTERED}

    assert (routed["attendance-a"].route, routed["attendance-a"].route_reason) == ("general", "evidence_found")
    assert (routed["abstain-no-regulation"].route, routed["abstain-no-regulation"].route_reason) == (
        "low_evidence", "no_applicable_regulations")
    cricket = routed["abstain-out-of-scope"]
    assert (cricket.route, cricket.abstained, cricket.abstention_correct) == ("out_of_scope", True, True)
    # The retrieval-only workflow has no router: it retrieves for the cricket question.
    assert plain["abstain-out-of-scope"].abstained is False and plain["abstain-out-of-scope"].route is None
    # On answerable cases the router passes the same evidence as the retrieval-only workflow.
    for case_id in ("attendance-a", "attendance-b"):
        assert routed[case_id].retrieved == plain[case_id].retrieved
        assert routed[case_id].reciprocal_rank == plain[case_id].reciprocal_rank == 1.0

    router_summary, plain_summary = result.summaries[ADAPTIVE_ROUTER], result.summaries[COHORT_FILTERED]
    assert router_summary.abstention_accuracy == 1.0
    assert plain_summary.abstention_accuracy == pytest.approx(3 / 4)
    assert router_summary.route_counts == {
        "general/evidence_found": 2,
        "low_evidence/no_applicable_regulations": 1,
        "out_of_scope/no_regulation_terms": 1,
    }
    assert plain_summary.route_counts is None


def test_router_abstaining_on_an_answerable_case_scores_zero(synthetic: tuple[Path, Path]) -> None:
    db_path, _ = synthetic
    no_regulation_words = {
        "id": "phrased-without-terms", "category": "attendance", "question": "Seventy percent of what is required?",
        "admission_batch": "2021", "programme": "CSE",
        "expected": {"document_name": "Rulebook A", "regulation_version": "2021", "pages": [1]}, "expect_abstain": False,
    }

    result = run_evaluation(_with_cases(no_regulation_words), db_path, top_k=2, configurations=[ADAPTIVE_ROUTER])
    case = next(r for r in result.results if r.case_id == "phrased-without-terms")

    assert (case.route, case.abstained, case.abstention_correct) == ("out_of_scope", True, False)
    assert (case.precision, case.recall, case.reciprocal_rank, case.wrong_version) == (0.0, 0.0, 0.0, False)
    assert case.retrieved == ()
    assert result.summaries[ADAPTIVE_ROUTER].false_abstentions == 1


def test_router_threshold_is_recorded(synthetic: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, dataset_path = synthetic
    dataset = load_dataset(dataset_path)
    monkeypatch.delenv("RETRIEVAL_MIN_SCORE", raising=False)

    assert run_evaluation(dataset, db_path, configurations=[ADAPTIVE_ROUTER]).router_min_score == 3.0
    assert run_evaluation(dataset, db_path, configurations=[COHORT_FILTERED]).router_min_score is None
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "4.5")
    assert run_evaluation(dataset, db_path, configurations=[ADAPTIVE_ROUTER]).router_min_score == 4.5


def test_report_separates_the_two_paths(synthetic: tuple[Path, Path]) -> None:
    db_path, _ = synthetic
    result = run_evaluation(_with_cases(CRICKET_CASE), db_path, top_k=2)

    report = render_markdown(result)
    section_a = report.split("## A. Retrieval-only workflow (baseline)")[1].split("## B.")[0]
    section_b = report.split("## B. End-to-end with the Adaptive RAG router")[1].split("## Limitations")[0]

    assert "### Which metrics apply to which path" in report
    assert "| Abstention | Retrieval returned no evidence" in report
    assert "The answer generator was not called" in report
    assert "Retrieval-only workflow, cohort-filtered (no router)" in section_a
    assert "no cohort filter" in section_a and "Adaptive RAG router (API path)" not in section_a
    assert "| End-to-end with the Adaptive RAG router (API path) |" in section_b
    assert "- out_of_scope/no_regulation_terms: 1" in section_b
    assert "Router:** minimum best retrieval score 3" in report
    routed_cases = report.split("### End-to-end with the Adaptive RAG router (API path)")[1]
    assert "| abstain-out-of-scope | 2023 / CSE | abstain | out_of_scope (no_regulation_terms) |" in routed_cases
    plain_cases = report.split("### Retrieval-only workflow, cohort-filtered (no router)")[1].split("###")[0]
    assert "Route (reason)" not in plain_cases


def test_routed_case_consistency_checks(synthetic: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    db_path, dataset_path = synthetic
    dataset = load_dataset(dataset_path)
    from backend.app.services import query_service

    def answers_without_generating(*_: Any, **__: Any) -> dict[str, Any]:
        return {"route": {"route": "general", "reason": "evidence_found"}, "retrieval": {"results": []}}

    monkeypatch.setattr(query_service, "answer_with_adaptive_routing", answers_without_generating)
    with pytest.raises(EvaluationError, match="generator calls disagree"):
        run_evaluation(dataset, db_path, configurations=[ADAPTIVE_ROUTER])

    monkeypatch.setattr(query_service, "answer_with_adaptive_routing", lambda *a, **k: {"retrieval": {}})
    with pytest.raises(EvaluationError, match="no routing decision"):
        run_evaluation(dataset, db_path, configurations=[ADAPTIVE_ROUTER])
