"""Offline routing evaluation for the adaptive router (module M6).

Runs ``backend.app.services.adaptive_router.route_question`` on a temporary
copy of a database for each labelled question and reports routing accuracy.
No answer is generated and no model is called.

Run from the project root::

    python -m evaluation.routing --output evaluation/reports/routing_v1_report.md
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, TextIO

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import get_settings
from backend.app.schemas.routing import Route, RouteReason
from backend.app.services import adaptive_router
from evaluation.dataset import DATASETS_DIR
from evaluation.runner import EvaluationError, snapshot_database

DEFAULT_ROUTING_DATASET = DATASETS_DIR / "routing_v1.json"
ROUTES: tuple[str, ...] = ("general", "clause_lookup", "low_evidence", "out_of_scope", "clarify")


class RoutingCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    question: str = Field(min_length=1)
    admission_batch: str
    programme: str
    expected_route: Route
    expected_reason: Optional[RouteReason] = None
    calibration: bool
    note: Optional[str] = None


class RoutingDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    cases: list[RoutingCase] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "RoutingDataset":
        ids = [case.id for case in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("case ids must be unique.")
        return self


def load_routing_dataset(path: str | Path = DEFAULT_ROUTING_DATASET) -> RoutingDataset:
    with open(path, encoding="utf-8") as handle:
        return RoutingDataset.model_validate(json.load(handle))


@dataclass(frozen=True)
class RoutingResult:
    case_id: str
    expected_route: str
    expected_reason: Optional[str]
    predicted_route: str
    predicted_reason: str
    best_score: Optional[float]
    calibration: bool
    note: Optional[str]

    @property
    def correct(self) -> bool:
        return self.predicted_route == self.expected_route and (
            self.expected_reason is None or self.predicted_reason == self.expected_reason
        )


@dataclass
class RoutingReport:
    dataset_name: str
    dataset_description: str
    min_score: float
    min_chunks_for_threshold: int
    results: list[RoutingResult] = field(default_factory=list)

    def accuracy(self, results: Optional[Sequence[RoutingResult]] = None) -> Optional[float]:
        chosen = self.results if results is None else list(results)
        return sum(r.correct for r in chosen) / len(chosen) if chosen else None

    @property
    def held_out(self) -> list[RoutingResult]:
        return [r for r in self.results if not r.calibration]

    def per_route(self) -> dict[str, tuple[int, int, Optional[float], Optional[float]]]:
        """route -> (expected count, predicted count, precision, recall)."""
        stats = {}
        for route in ROUTES:
            expected = [r for r in self.results if r.expected_route == route]
            predicted = [r for r in self.results if r.predicted_route == route]
            hits = sum(1 for r in expected if r.correct)
            precision = sum(1 for r in predicted if r.correct) / len(predicted) if predicted else None
            recall = hits / len(expected) if expected else None
            stats[route] = (len(expected), len(predicted), precision, recall)
        return stats

    def confusion(self) -> Counter[tuple[str, str]]:
        return Counter((r.expected_route, r.predicted_route) for r in self.results)


def run_routing_evaluation(
    dataset: RoutingDataset,
    db_path: str | Path,
    *,
    min_score: Optional[float] = None,
    top_k: int = 5,
) -> RoutingReport:
    """Route every case against a snapshot of ``db_path``. Never calls a model."""
    threshold = adaptive_router.configured_min_score() if min_score is None else float(min_score)
    report = RoutingReport(
        dataset_name=dataset.name,
        dataset_description=dataset.description,
        min_score=threshold,
        min_chunks_for_threshold=adaptive_router.MIN_CHUNKS_FOR_THRESHOLD,
    )
    with tempfile.TemporaryDirectory(prefix="cohortiq-routing-") as workdir:
        snapshot = snapshot_database(db_path, Path(workdir) / "snapshot.db")
        for case in dataset.cases:
            decision = adaptive_router.route_question(
                case.question, case.admission_batch, case.programme, db_path=snapshot, top_k=top_k, min_score=threshold
            ).decision
            report.results.append(
                RoutingResult(
                    case_id=case.id,
                    expected_route=case.expected_route,
                    expected_reason=case.expected_reason,
                    predicted_route=decision.route,
                    predicted_reason=decision.reason,
                    best_score=decision.best_score,
                    calibration=case.calibration,
                    note=case.note,
                )
            )
    return report


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


LIMITATIONS = (
    "The dataset is small (40 questions) and was written and labelled by the person who designed the router; "
    "calibration cases informed the threshold and vocabulary, so only the held-out accuracy approximates unseen questions.",
    "Out-of-scope detection is a fixed vocabulary check: an unrelated question that uses a regulation word "
    "(for example 'result') is not refused, and a regulation question phrased without any listed word is refused.",
    "The score threshold is a conservative floor on raw BM25 scores. It does not detect in-domain questions the "
    "regulations do not answer (for example an exam timetable or a tuition amount), because such questions share "
    "words with the regulations and score as high as answerable ones.",
    "BM25 scores depend on corpus size and question length. The threshold is skipped for corpora smaller than "
    "the minimum chunk count, and must be recalibrated when the regulations change substantially.",
    "Routing accuracy says nothing about answer quality: a correctly routed general question can still retrieve "
    "the wrong pages (see the retrieval report).",
)


def render_markdown(report: RoutingReport, *, generated_at: Optional[datetime] = None) -> str:
    moment = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    held_out = report.held_out
    lines = [
        "# CohortIQ routing evaluation",
        "",
        f"Generated {moment}. Dataset `{report.dataset_name}`.",
        "",
        "## Setup",
        "",
        f"- **Questions:** {len(report.results)} ({len(held_out)} held out, {len(report.results) - len(held_out)} used in calibration).",
        *([f"- **About the dataset:** {report.dataset_description}"] if report.dataset_description else []),
        f"- **Router settings:** minimum best retrieval score {report.min_score:g} "
        f"(applied when the cohort corpus has at least {report.min_chunks_for_threshold} chunks); clause lookups use top 3.",
        "- **Method:** each question runs through `route_question` on a temporary copy of the database. "
        "No answer is generated and no model is called. A prediction is correct when the route matches "
        "(and the reason, where the case specifies one).",
        "",
        "## Results",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Routing accuracy (all questions) | {_pct(report.accuracy())} ({sum(r.correct for r in report.results)}/{len(report.results)}) |",
        f"| Routing accuracy (held-out questions) | {_pct(report.accuracy(held_out))} ({sum(r.correct for r in held_out)}/{len(held_out)}) |",
        "",
        "| Route | Expected | Predicted | Precision | Recall |",
        "|---|---|---|---|---|",
    ]
    for route, (expected, predicted, precision, recall) in report.per_route().items():
        lines.append(f"| {route} | {expected} | {predicted} | {_pct(precision)} | {_pct(recall)} |")
    lines += ["", "Confusion (expected → predicted), misroutes only:", ""]
    misroutes = sorted((pair, count) for pair, count in report.confusion().items() if pair[0] != pair[1])
    lines += [f"- {expected} → {predicted}: {count}" for (expected, predicted), count in misroutes] or ["- none"]
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in LIMITATIONS]
    below = sum(r.predicted_reason == "score_below_threshold" for r in report.results)
    lines.append(
        f"- The score-threshold abstention fired for {below} of {len(report.results)} questions in this dataset"
        + (
            "; its behaviour is covered by unit tests on a synthetic corpus, not measured here."
            if below == 0
            else "."
        )
    )
    lines += [
        "",
        "## Per-question results",
        "",
        "| Case | Expected | Predicted (reason) | Best score | Correct | Calibration | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report.results:
        expected = r.expected_route + (f" ({r.expected_reason})" if r.expected_reason else "")
        score = "-" if r.best_score is None else f"{r.best_score:.2f}"
        lines.append(
            f"| {r.case_id} | {expected} | {r.predicted_route} ({r.predicted_reason}) | {score} | "
            f"{'yes' if r.correct else 'no'} | {'yes' if r.calibration else 'no'} | {r.note or ''} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None, *, out: Optional[TextIO] = None, err: Optional[TextIO] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.routing", description="Evaluate adaptive routing offline.")
    parser.add_argument("--db-path", help="SQLite database (default: DATABASE_PATH). It is only read.")
    parser.add_argument("--dataset", default=str(DEFAULT_ROUTING_DATASET), help="Routing dataset JSON file.")
    parser.add_argument("--min-score", type=float, help="Minimum best retrieval score (default: RETRIEVAL_MIN_SCORE or 3.0).")
    parser.add_argument("--output", help="Write the Markdown report here instead of printing it.")
    args = parser.parse_args(argv)
    out, err = out or sys.stdout, err or sys.stderr

    try:
        dataset = load_routing_dataset(args.dataset)
    except (OSError, ValueError) as error:
        print(f"Error: could not load the dataset: {error}", file=err)
        return 2
    try:
        report = run_routing_evaluation(dataset, args.db_path or get_settings().database_path, min_score=args.min_score)
    except (EvaluationError, ValueError) as error:
        print(f"Error: {error}", file=err)
        return 2
    text = render_markdown(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Report written to {args.output}", file=out)
    else:
        print(text, file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
