"""Tests for the offline routing evaluation (``evaluation/routing.py``, module M6).

Runs on a synthetic database in a temporary directory; no model is called.
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
from evaluation.routing import (
    DEFAULT_ROUTING_DATASET,
    ROUTES,
    RoutingDataset,
    RoutingReport,
    RoutingResult,
    load_routing_dataset,
    main,
    render_markdown,
    run_routing_evaluation,
)

PAGES = [
    "10.1 Attendance: students need seventy five percent attendance to sit the end semester examinations.",
    "11.1 Theory courses are passed with forty percent in the end examination and fifty percent overall.",
    *[f"Campus note {n}: the library opens at {n} and wardens record visitors in register {n}{n}." for n in range(1, 24)],
]


@pytest.fixture(autouse=True)
def _no_model_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "generate_grounded_answer", lambda **_: pytest.fail("no model calls"))


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "routing-source.db"
    init_database(path)
    insert_regulation_with_pages(
        {
            "document_name": "Rulebook", "regulation_version": "2023", "effective_date": "2023-06-01",
            "applicable_batches": ["2023"], "applicable_programmes": ["CSE"], "upload_date": "2023-06-01",
            "total_pages": len(PAGES), "processing_status": "extracted", "verification_status": "approved",
        },
        [{"page_number": n, "extracted_text": text, "extraction_status": "success"} for n, text in enumerate(PAGES, 1)],
        db_path=path,
    )
    return path


def _case(case_id: str, question: str, route: str, *, batch: str = "2023", reason: str | None = None,
          calibration: bool = False) -> dict[str, Any]:
    return {"id": case_id, "question": question, "admission_batch": batch, "programme": "CSE",
            "expected_route": route, "expected_reason": reason, "calibration": calibration}


SYNTHETIC = {
    "name": "synthetic-routing",
    "cases": [
        _case("general", "What attendance is needed to sit the examinations?", "general", calibration=True),
        _case("clause", "What does clause 10.1 say?", "clause_lookup"),
        _case("missing-clause", "What does clause 99.9 say?", "low_evidence", reason="clause_not_found"),
        _case("weak", "Can the honours syllabus change?", "low_evidence", reason="score_below_threshold"),
        _case("cricket", "Who won the cricket world cup in 2011?", "out_of_scope"),
        _case("clarify", "What attendance is needed?", "clarify", batch=""),
        # Deliberately mislabelled, to check that errors are counted.
        _case("mislabelled", "What does clause 10.1 say?", "general"),
    ],
}


def test_packaged_routing_dataset_is_valid() -> None:
    dataset = load_routing_dataset(DEFAULT_ROUTING_DATASET)

    assert dataset.name == "cohortiq-routing-v1"
    assert len(dataset.cases) == 40
    assert {case.expected_route for case in dataset.cases} == set(ROUTES)
    ids = {case.id for case in dataset.cases}
    assert {"oos-cricket", "general-passing-theory-miss"} <= ids
    assert sum(not case.calibration for case in dataset.cases) == 24


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["cases"][1].update(id="general"),
        lambda d: d["cases"][0].update(expected_route="maybe"),
        lambda d: d["cases"][0].update(expected_reason="because"),
        lambda d: d["cases"][0].update(unknown=1),
        lambda d: d.update(cases=[]),
    ],
)
def test_invalid_routing_datasets_are_rejected(mutate: Any) -> None:
    data = json.loads(json.dumps(SYNTHETIC))
    mutate(data)
    with pytest.raises(ValueError):
        RoutingDataset.model_validate(data)


def test_routing_evaluation_scores_each_route(db_path: Path) -> None:
    before = hashlib.sha256(db_path.read_bytes()).hexdigest(), db_path.stat().st_mtime_ns

    report = run_routing_evaluation(RoutingDataset.model_validate(SYNTHETIC), db_path)

    predicted = {r.case_id: (r.predicted_route, r.predicted_reason) for r in report.results}
    assert predicted == {
        "general": ("general", "evidence_found"),
        "clause": ("clause_lookup", "clause_reference"),
        "missing-clause": ("low_evidence", "clause_not_found"),
        "weak": ("low_evidence", "score_below_threshold"),
        "cricket": ("out_of_scope", "no_regulation_terms"),
        "clarify": ("clarify", "missing_cohort"),
        "mislabelled": ("clause_lookup", "clause_reference"),
    }
    assert report.accuracy() == pytest.approx(6 / 7)
    assert report.accuracy(report.held_out) == pytest.approx(5 / 6)
    assert report.confusion()[("general", "clause_lookup")] == 1
    assert (hashlib.sha256(db_path.read_bytes()).hexdigest(), db_path.stat().st_mtime_ns) == before


def _result(expected: str, predicted: str, *, expected_reason: str | None = None,
            predicted_reason: str = "evidence_found", calibration: bool = False) -> RoutingResult:
    return RoutingResult("c", expected, expected_reason, predicted, predicted_reason, None, calibration, None)


def test_accuracy_and_per_route_precision_recall() -> None:
    report = RoutingReport("d", "", 3.0, 20, results=[
        _result("general", "general"),
        _result("general", "general", calibration=True),
        _result("low_evidence", "general"),
        _result("out_of_scope", "out_of_scope", predicted_reason="no_regulation_terms"),
        _result("low_evidence", "low_evidence", expected_reason="clause_not_found", predicted_reason="no_retrieval_results"),
    ])

    assert report.accuracy() == pytest.approx(3 / 5)  # the reason mismatch counts as wrong
    assert report.accuracy(report.held_out) == pytest.approx(2 / 4)
    stats = report.per_route()
    assert stats["general"] == (2, 3, pytest.approx(2 / 3), 1.0)
    assert stats["low_evidence"] == (2, 1, 0.0, 0.0)
    assert stats["clarify"] == (0, 0, None, None)
    assert report.accuracy([]) is None


def test_report_states_accuracy_and_limitations(db_path: Path) -> None:
    report = run_routing_evaluation(RoutingDataset.model_validate(SYNTHETIC), db_path)

    text = render_markdown(report)

    assert "| Routing accuracy (all questions) | 85.7% (6/7) |" in text
    assert "| Routing accuracy (held-out questions) | 83.3% (5/6) |" in text
    assert "general → clause_lookup: 1" in text
    assert "## Limitations" in text and "fixed vocabulary check" in text
    assert "score-threshold abstention fired for 1 of 7" in text


def test_cli_writes_the_report_and_fails_cleanly(db_path: Path, tmp_path: Path) -> None:
    dataset = tmp_path / "routing.json"
    dataset.write_text(json.dumps(SYNTHETIC), encoding="utf-8")
    output = tmp_path / "out" / "routing.md"

    assert main(["--db-path", str(db_path), "--dataset", str(dataset), "--output", str(output)],
                out=io.StringIO(), err=io.StringIO()) == 0
    assert "# CohortIQ routing evaluation" in output.read_text(encoding="utf-8")

    err = io.StringIO()
    assert main(["--db-path", str(tmp_path / "missing.db"), "--dataset", str(dataset)], out=io.StringIO(), err=err) == 2
    assert "Database not found" in err.getvalue() and not (tmp_path / "missing.db").exists()

    err = io.StringIO()
    assert main(["--db-path", str(db_path), "--dataset", str(dataset), "--min-score", "-1"], out=io.StringIO(), err=err) == 2
