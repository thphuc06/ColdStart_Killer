#!/usr/bin/env python
"""Summarize an existing evaluation run.

Usage:
    python scripts/summarize_evaluation.py \\
        --run-dir .runtime/evaluation/eval_seed
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.reporting import generate_metrics_summary_md


def _coerce_csv_value(value: str) -> object:
    if value == "":
        return None
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _read_csv_rows(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [
            {key: _coerce_csv_value(value) for key, value in row.items()}
            for row in csv.DictReader(f)
        ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize an evaluation run")
    parser.add_argument("--run-dir", required=True, help="Path to evaluation run directory")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"ERROR: Run directory not found: {run_dir}", file=sys.stderr)
        return 1

    # Load existing artifacts
    config_path = run_dir / "config.json"
    metrics_path = run_dir / "layer2_metrics_summary.json"
    per_query_path = run_dir / "layer2_metrics_by_query.csv"
    latency_path = run_dir / "latency_by_query.csv"
    raw_results_path = run_dir / "layer2_raw_results.json"
    failures_path = run_dir / "failures.json"

    run_data: dict = {"config": {}, "variant_summaries": [], "failures": [], "latency": []}

    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            run_data["config"] = json.load(f)

    if metrics_path.exists():
        with metrics_path.open("r", encoding="utf-8") as f:
            run_data["variant_summaries"] = json.load(f)

    if failures_path.exists():
        with failures_path.open("r", encoding="utf-8") as f:
            run_data["failures"] = json.load(f)

    if per_query_path.exists():
        run_data["per_query_metrics"] = _read_csv_rows(per_query_path)

    if latency_path.exists():
        run_data["latency"] = _read_csv_rows(latency_path)

    if raw_results_path.exists():
        with raw_results_path.open("r", encoding="utf-8") as f:
            run_data["results"] = json.load(f)

    md = generate_metrics_summary_md(run_data)

    # Write updated summary
    summary_path = run_dir / "metrics_summary.md"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(md)

    print(f"Summary written to {summary_path}")
    print(md[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
