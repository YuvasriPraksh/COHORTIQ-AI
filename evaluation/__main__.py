"""Command line: ``python -m evaluation [options]`` (run from the project root)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, TextIO

from app.config import get_settings
from evaluation.dataset import DEFAULT_DATASET, load_dataset
from evaluation.report import render_markdown, to_json
from evaluation.runner import CONFIGURATIONS, DEFAULT_TOP_K, EvaluationError, run_evaluation

EXIT_OK = 0
EXIT_FAILED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation",
        description=(
            "Evaluate CohortIQ offline against a labelled dataset: the retrieval-only workflow and the end-to-end "
            "path with the Adaptive RAG router. Calls no model."
        ),
    )
    parser.add_argument("--db-path", help="SQLite database to evaluate (default: DATABASE_PATH). It is only read.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Dataset JSON file.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help=f"Chunks retrieved per question (default {DEFAULT_TOP_K}).")
    parser.add_argument(
        "--configuration",
        action="append",
        choices=CONFIGURATIONS,
        help="Configuration to run; repeat for several (default: all).",
    )
    parser.add_argument("--output", help="Write the Markdown report here instead of printing it.")
    parser.add_argument("--json", dest="json_path", help="Also write the results as JSON here.")
    return parser


def main(argv: Optional[list[str]] = None, *, out: Optional[TextIO] = None, err: Optional[TextIO] = None) -> int:
    args = build_parser().parse_args(argv)
    out = out or sys.stdout
    err = err or sys.stderr
    if args.top_k < 1:
        print("Error: --top-k must be at least 1.", file=err)
        return EXIT_FAILED

    db_path = Path(args.db_path) if args.db_path else get_settings().database_path
    try:
        dataset = load_dataset(args.dataset)
    except (OSError, ValueError) as error:
        print(f"Error: could not load the dataset: {error}", file=err)
        return EXIT_FAILED
    try:
        result = run_evaluation(dataset, db_path, top_k=args.top_k, configurations=args.configuration or CONFIGURATIONS)
    except EvaluationError as error:
        print(f"Error: {error}", file=err)
        return EXIT_FAILED

    report = render_markdown(result)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(report + "\n", encoding="utf-8")
        print(f"Report written to {args.output}", file=out)
    else:
        print(report, file=out)
    if args.json_path:
        Path(args.json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_path).write_text(to_json(result) + "\n", encoding="utf-8")
        print(f"JSON results written to {args.json_path}", file=out)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
