"""Readable (Markdown) and machine-readable (JSON) evaluation reports."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Optional

from evaluation.runner import (
    ADAPTIVE_ROUTER,
    COHORT_FILTERED,
    END_TO_END_CONFIGURATIONS,
    NO_COHORT_FILTER,
    RETRIEVAL_ONLY_CONFIGURATIONS,
    CaseResult,
    EvaluationResult,
)

CONFIGURATION_LABELS = {
    COHORT_FILTERED: "Retrieval-only workflow, cohort-filtered (no router)",
    NO_COHORT_FILTER: "Retrieval-only baseline: no cohort filter (all approved regulations)",
    ADAPTIVE_ROUTER: "End-to-end with the Adaptive RAG router (API path)",
}

NOT_MEASURED = (
    "Answer faithfulness and answer relevancy are **not evaluated**: no answers are generated.",
    "Citation validity is **not evaluated**: it needs generated answers with citations, and this run calls no model.",
    "Reference answers are stored in the dataset for later answer-quality evaluation but are **not scored**.",
)

STATIC_LIMITATIONS = (
    "The dataset is small (about 20 cases) and was labelled by one person by reading the extracted page text, so results indicate behaviour but are not statistically strong.",
    "Relevance is judged per page, not per clause or chunk. A chunk from a relevant page counts as relevant even if it holds only part of the answer.",
    "The two regulations have near-identical wording for many rules, which makes wrong-version retrieval a realistic risk but also means a 'wrong-version' chunk may still state the same rule.",
    "Retrieval-only abstention happens only when retrieval returns no evidence. BM25 always returns its top results when the cohort has any regulation (there is no score threshold on that path), so out-of-scope questions cannot abstain there.",
    "End-to-end abstention is measured on this dataset's three abstention cases only; routing accuracy across all routes is measured separately on the routing dataset (see `evaluation/reports/routing_v1_report.md`).",
    "Only the current retrieval method is measured (BM25 with recursive chunking). There is no vector, hybrid or reranked retrieval to compare yet.",
    "The project database and PDFs are not in the repository, so these results can only be reproduced with the same database. Tests use a separate synthetic database.",
)

METRIC_PATHS = (
    ("Precision@K, Recall@K, MRR",
     "The workflow's top-K retrieved chunks.",
     "The evidence passed to the answer generator (top 3 for clause lookups). When the router abstains on an answerable case, the case scores 0."),
    ("Wrong-version rate and chunks",
     "Chunks from another regulation or version in the top K.",
     "Same, on the evidence passed to the generator (empty when the router abstains)."),
    ("Abstention",
     "Retrieval returned no evidence, so the model would not be called.",
     "The answer generator was not called: any route other than `clause_lookup` or `general`."),
    ("Routing outcome",
     "Not applicable (no router).",
     "The validated route and reason returned with every answer."),
)


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _cohort(result: CaseResult) -> str:
    return f"{result.admission_batch} / {result.programme}"


def _expected(result: CaseResult) -> str:
    if result.expected is None:
        return "abstain"
    pages = ", ".join(str(page) for page in sorted(result.expected.pages))
    return f"{result.expected.document_name} {result.expected.regulation_version} p. {pages}"


def _retrieved(result: CaseResult) -> str:
    if not result.retrieved:
        return "none"
    return "; ".join(f"{item.document_name} {item.regulation_version} p.{item.page_number}" for item in result.retrieved)


def _metrics_table(result: EvaluationResult, configurations: tuple[str, ...]) -> list[str]:
    k = result.top_k
    lines = [
        f"| Configuration | Precision@{k} | Recall@{k} | MRR | Wrong-version rate | Wrong-version chunks | Abstention accuracy |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in configurations:
        s = result.summaries[name]
        lines.append(
            f"| {CONFIGURATION_LABELS[name]} | {_num(s.precision_at_k)} | {_num(s.recall_at_k)} | {_num(s.mrr)} | "
            f"{_pct(s.wrong_version_rate)} | {_pct(s.wrong_version_chunk_share)} | {_pct(s.abstention_accuracy)} |"
        )
    lines += ["", "Abstention detail:", ""]
    for name in configurations:
        s = result.summaries[name]
        lines.append(
            f"- {CONFIGURATION_LABELS[name]}: {s.correct_abstentions} of {s.abstention_cases} expected abstentions made; "
            f"{s.false_abstentions} answerable case(s) wrongly abstained."
        )
    return lines


def _case_table(result: EvaluationResult, name: str) -> list[str]:
    k = result.top_k
    routed = name in END_TO_END_CONFIGURATIONS
    header = f"| Case | Cohort | Expected |{' Route (reason) |' if routed else ''} First relevant rank | P@{k} | R@{k} | Wrong version | Abstained | Retrieved (rank order) |"
    lines = [f"### {CONFIGURATION_LABELS[name]}", "", header, "|" + "---|" * (header.count("|") - 1)]
    for r in (item for item in result.results if item.configuration == name):
        wrong = "n/a" if r.wrong_version is None else ("yes" if r.wrong_version else "no")
        abstained = ("yes" if r.abstained else "no") + ("" if r.abstention_correct else " (wrong)")
        route = f" {r.route} ({r.route_reason}) |" if routed else ""
        lines.append(
            f"| {r.case_id} | {_cohort(r)} | {_expected(r)} |{route} {r.first_relevant_rank or '-'} | "
            f"{_num(r.precision)} | {_num(r.recall)} | {wrong} | {abstained} | {_retrieved(r)} |"
        )
    lines.append("")
    return lines


def render_markdown(result: EvaluationResult, *, generated_at: Optional[datetime] = None) -> str:
    moment = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    k = result.top_k
    categories = Counter(r.category for r in result.results if r.configuration == result.configurations[0])
    first = result.summaries[result.configurations[0]]
    retrieval_only = tuple(name for name in result.configurations if name in RETRIEVAL_ONLY_CONFIGURATIONS)
    end_to_end = tuple(name for name in result.configurations if name in END_TO_END_CONFIGURATIONS)

    lines = [
        "# CohortIQ retrieval and end-to-end evaluation",
        "",
        f"Generated {moment}. Dataset `{result.dataset_name}`.",
        "",
        "## Setup",
        "",
        f"- **Cases:** {result.dataset_size} ({first.answerable_cases} answerable, {first.abstention_cases} expecting abstention).",
        *([f"- **About the dataset:** {result.dataset_description}"] if result.dataset_description else []),
        "- **Categories:** " + ", ".join(f"{name} ({count})" for name, count in sorted(categories.items())) + ".",
        f"- **Retrieval:** top {k} chunks, {result.chunking['chunking_strategy']} chunking, "
        f"size {result.chunking['chunk_size']}, overlap {result.chunking['overlap']} (the API defaults).",
    ]
    if result.router_min_score is not None:
        lines.append(f"- **Router:** minimum best retrieval score {result.router_min_score:g}; clause lookups use top 3.")
    lines.append("- **Regulations in the database:**")
    for reg in result.regulations:
        lines.append(
            f"  - {reg.document_name} version {reg.regulation_version}: batches {', '.join(reg.applicable_batches)}; "
            f"programmes {', '.join(reg.applicable_programmes)}; {reg.verification_status}."
        )
    lines += [
        "- **Method:** every case runs on a temporary copy of the database with answer generation replaced by a "
        "stand-in, so no model or external service is called.",
        "",
        "## Two paths are evaluated",
        "",
        "1. **Retrieval-only workflow:** `app.workflow.answer_student_question`, which the Streamlit app uses. "
        "It has no router. This is the original baseline, kept unchanged.",
        "2. **End-to-end with the Adaptive RAG router:** `query_service.answer_with_adaptive_routing`, which "
        "`POST /api/v1/query/ask` uses. Questions can be refused, clarified or abstained on before generation.",
        "",
        "### Which metrics apply to which path",
        "",
        "| Metric | Retrieval-only workflow | End-to-end with the router |",
        "|---|---|---|",
    ]
    lines += [f"| {metric} | {retrieval} | {routed} |" for metric, retrieval, routed in METRIC_PATHS]
    lines += [
        "",
        "A retrieved chunk is **relevant** when it comes from the expected regulation (document name and version) "
        "and one of the expected pages. Retrieval metrics average over answerable cases only.",
        "",
        f"- **Precision@{k}:** relevant chunks among the top {k}, divided by {k}.",
        f"- **Recall@{k}:** share of the expected pages that appear in the top {k}.",
        f"- **MRR:** mean of 1 / rank of the first relevant chunk (0 when none is in the top {k}).",
        f"- **Wrong-version rate:** share of answerable cases with at least one top-{k} chunk from a different regulation or version.",
        f"- **Wrong-version chunks:** share of returned top-{k} chunks from a different regulation or version.",
        "- **Abstention accuracy:** share of all cases where the path abstained exactly when it should.",
        "",
    ]
    if retrieval_only:
        lines += ["## A. Retrieval-only workflow (baseline)", ""] + _metrics_table(result, retrieval_only) + [""]
    if end_to_end:
        lines += ["## B. End-to-end with the Adaptive RAG router", ""] + _metrics_table(result, end_to_end) + [""]
        for name in end_to_end:
            counts = result.summaries[name].route_counts or {}
            lines += ["Routing outcomes (route / reason → cases):", ""]
            lines += [f"- {key}: {count}" for key, count in counts.items()]
            lines.append("")
    lines += ["## Limitations", ""]
    lines += [f"- {item}" for item in NOT_MEASURED]
    lines += [f"- {item}" for item in STATIC_LIMITATIONS]
    if not result.cohorts_with_multiple_regulations:
        lines.append(
            "- Every evaluated cohort has exactly one applicable regulation, so in the cohort-filtered and router "
            "paths a wrong-version chunk can only come from an applicability error, not from ranking. The "
            "no-cohort-filter baseline shows the ranking risk the filter removes."
        )
    lines += ["", "## Per-case results", ""]
    for name in result.configurations:
        lines += _case_table(result, name)
    return "\n".join(lines)


def to_json(result: EvaluationResult) -> str:
    def convert(value: Any) -> Any:
        if isinstance(value, frozenset):
            return sorted(value)
        if isinstance(value, (list, tuple)):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value

    payload = {
        "dataset": result.dataset_name,
        "dataset_size": result.dataset_size,
        "top_k": result.top_k,
        "chunking": result.chunking,
        "router_min_score": result.router_min_score,
        "configurations": list(result.configurations),
        "paths": {
            "retrieval_only": [name for name in result.configurations if name in RETRIEVAL_ONLY_CONFIGURATIONS],
            "end_to_end": [name for name in result.configurations if name in END_TO_END_CONFIGURATIONS],
        },
        "regulations": [asdict(reg) for reg in result.regulations],
        "summaries": {name: asdict(summary) for name, summary in result.summaries.items()},
        "cases": [
            {**asdict(item), "abstention_correct": item.abstention_correct} for item in result.results
        ],
        "not_measured": ["answer faithfulness", "answer relevancy", "citation validity"],
    }
    return json.dumps(convert(payload), indent=2, sort_keys=True)
