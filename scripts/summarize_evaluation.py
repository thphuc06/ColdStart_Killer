#!/usr/bin/env python
"""Summarize an existing evaluation run.

Usage:
    python scripts/summarize_evaluation.py \\
        --run-dir .runtime/evaluation/eval_seed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.reporting import generate_metrics_summary_md


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
