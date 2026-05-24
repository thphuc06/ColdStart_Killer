#!/usr/bin/env python
"""Run Phase 12 personalization and CF evaluation.

Examples:
    python scripts/run_personalization_evaluation.py --dry-run
    python scripts/run_personalization_evaluation.py --out .runtime/evaluation/personalization_live
    python scripts/run_personalization_evaluation.py --write-evaluation-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.personalization_eval import (
    PersonalizationEvalConfig,
    evaluate_personalization,
    load_live_personalization_inputs,
    persist_evaluation_run,
    write_personalization_outputs,
)


def _default_output_dir() -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return str(ROOT / ".runtime" / "evaluation" / f"personalization_{stamp}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Phase 12 personalization and CF evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--out", default=_default_output_dir(), help="Output directory for evaluation artifacts")
    parser.add_argument("--top-k", type=int, default=20, help="Recommendation list length to evaluate")
    parser.add_argument("--train-ratio", type=float, default=0.7, help="Temporal split ratio for train events")
    parser.add_argument("--dry-run", action="store_true", help="Do not write evaluation_runs to MongoDB")
    parser.add_argument(
        "--write-evaluation-run",
        action="store_true",
        help="Persist a compact summary into evaluation_runs after local artifacts are written",
    )
    parser.add_argument(
        "--real-data",
        action="store_true",
        help="Label the run as live/non-synthetic instead of synthetic/demo",
    )
    parser.add_argument(
        "--print-json-summary",
        action="store_true",
        help="Print baseline_summaries as JSON to stdout after completion",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.top_k <= 0:
        print("ERROR: --top-k must be positive", file=sys.stderr)
        return 1
    if not 0 < args.train_ratio < 1:
        print("ERROR: --train-ratio must be between 0 and 1", file=sys.stderr)
        return 1
    if args.dry_run and args.write_evaluation_run:
        print("ERROR: --dry-run cannot be combined with --write-evaluation-run", file=sys.stderr)
        return 1

    try:
        live_inputs = load_live_personalization_inputs()
    except Exception as exc:
        print(f"ERROR: failed to load live MongoDB inputs: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    config = PersonalizationEvalConfig(
        run_id=Path(args.out).name,
        output_dir=str(args.out),
        train_ratio=args.train_ratio,
        top_k=args.top_k,
        synthetic_data=not args.real_data,
        extra_metadata={"live_state_counts": live_inputs.get("live_state_counts", {})},
    )

    run_data = evaluate_personalization(
        items=live_inputs["items"],
        clickstream_events=live_inputs["clickstream_events"],
        recommendation_logs=live_inputs.get("recommendation_logs"),
        item_stats=live_inputs.get("item_stats"),
        config=config,
    )
    paths = write_personalization_outputs(run_data, args.out)

    print(f"Personalization evaluation completed: {run_data['config']['run_id']}")
    print(f"  data_label: {run_data['config']['data_label']}")
    print(f"  users: {run_data['config']['user_count']}")
    print(f"  evaluated_users: {run_data['config']['evaluated_user_count']}")
    print(f"  events: {run_data['config']['event_count']}")
    print("  live_state_counts:")
    for key, value in sorted(live_inputs.get("live_state_counts", {}).items()):
        print(f"    {key}: {value}")
    print("  artifacts:")
    for name, path in sorted(paths.items()):
        print(f"    {name}: {path}")

    if args.print_json_summary:
        print(json.dumps(run_data["baseline_summaries"], indent=2, ensure_ascii=False))
    else:
        print("  baseline_summaries:")
        for row in run_data["baseline_summaries"]:
            print(
                "    "
                f"{row['baseline']}: users={row['evaluated_user_count']}, "
                f"hit@10={row['hit_rate_at_10']:.4f}, "
                f"recall@20={row['recall_at_20']:.4f}, "
                f"map@20={row['map_at_20']:.4f}, "
                f"cf_count={row['cf_supported_recommendation_count']}"
            )

    if args.write_evaluation_run:
        try:
            mongo_write = persist_evaluation_run(run_data)
        except Exception as exc:
            print(f"ERROR: failed to write evaluation_runs summary: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(f"  evaluation_runs_inserted_id: {mongo_write['inserted_id']}")
    elif args.dry_run:
        print("  evaluation_runs write skipped due to --dry-run")
    else:
        print("  evaluation_runs write skipped (use --write-evaluation-run to persist summary)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
