#!/usr/bin/env python
"""Run Phase 12 personalization and CF evaluation.

Examples:
    python scripts/run_personalization_evaluation.py --dry-run
    python scripts/run_personalization_evaluation.py --dry-run --write-artifacts
    python scripts/run_personalization_evaluation.py --dry-run --no-artifacts
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
    artifact_group = parser.add_mutually_exclusive_group()
    artifact_group.add_argument(
        "--write-artifacts",
        action="store_true",
        help="Write local report artifacts. During --dry-run, artifacts are skipped unless this flag is set.",
    )
    artifact_group.add_argument(
        "--no-artifacts",
        action="store_true",
        help="Skip local report artifacts even for non-dry runs.",
    )
    return parser


def _should_write_artifacts(args: argparse.Namespace) -> bool:
    if args.no_artifacts:
        return False
    if args.write_artifacts:
        return True
    return not args.dry_run


def _format_baseline_row(row: dict[str, object]) -> str:
    return (
        "    "
        f"{row['baseline']}: users={row['evaluated_user_count']}, "
        f"hit@10={float(row['hit_rate_at_10']):.4f}, "
        f"recall@20={float(row['recall_at_20']):.4f}, "
        f"map@20={float(row['map_at_20']):.4f}, "
        f"coverage={float(row['coverage']):.4f}, "
        f"cold@20={float(row['cold_start_exposure_at_20']):.4f}, "
        f"cf_count={int(row['cf_supported_recommendation_count'])}, "
        f"cf_rate={float(row['cf_supported_recommendation_rate']):.4f}"
    )


def _build_terminal_summary(
    run_data: dict[str, object],
    *,
    live_state_counts: dict[str, int],
    artifact_paths: dict[str, str] | None,
    artifacts_skipped_reason: str | None,
    include_json_summary: bool = False,
) -> str:
    config = run_data["config"]  # type: ignore[index]
    baselines = run_data["baseline_summaries"]  # type: ignore[index]
    comparisons = run_data.get("comparisons", [])  # type: ignore[union-attr]
    lines = [
        f"Personalization evaluation completed: {config['run_id']}",
        f"  data_label: {config['data_label']}",
        "  caveat: Synthetic/demo metrics are indicative only; do not present them as human-audited ground truth.",
        f"  algorithm_version: {config.get('algorithm_version', 'unknown')}",
        f"  ranking_version: {config.get('ranking_version', 'unknown')}",
        f"  users: {config['user_count']}",
        f"  evaluated_users: {config['evaluated_user_count']}",
        f"  events: {config['event_count']}",
        "  live_state_counts:",
    ]
    for key, value in sorted(live_state_counts.items()):
        lines.append(f"    {key}: {value}")

    if artifact_paths:
        lines.append("  artifacts:")
        for name, path in sorted(artifact_paths.items()):
            lines.append(f"    {name}: {path}")
    else:
        lines.append(f"  artifacts: skipped ({artifacts_skipped_reason or 'not requested'})")

    if include_json_summary:
        lines.append("  baseline_summaries_json:")
        lines.append(json.dumps(baselines, indent=2, ensure_ascii=False))
    else:
        lines.append("  baseline_summaries:")
        for row in baselines:  # type: ignore[assignment]
            lines.append(_format_baseline_row(row))

    lines.append("  key_comparisons:")
    for row in comparisons:  # type: ignore[assignment]
        lines.append(
            "    "
            f"{row['comparison']}: "
            f"hit@10_delta={float(row['hit_rate_at_10_delta']):.4f}, "
            f"recall@20_delta={float(row['recall_at_20_delta']):.4f}, "
            f"map@20_delta={float(row['map_at_20_delta']):.4f}, "
            f"cf_supported_delta={int(row['cf_supported_count_delta'])}"
        )

    return "\n".join(lines)


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
    if args.no_artifacts and args.write_evaluation_run:
        print("ERROR: --no-artifacts cannot be combined with --write-evaluation-run", file=sys.stderr)
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
    paths: dict[str, str] | None = None
    artifacts_skipped_reason: str | None = None
    if _should_write_artifacts(args):
        paths = write_personalization_outputs(run_data, args.out)
    elif args.dry_run and not args.write_artifacts:
        artifacts_skipped_reason = "--dry-run skips filesystem writes by default; use --write-artifacts to save reports"
    else:
        artifacts_skipped_reason = "--no-artifacts"

    print(
        _build_terminal_summary(
            run_data,
            live_state_counts=live_inputs.get("live_state_counts", {}),
            artifact_paths=paths,
            artifacts_skipped_reason=artifacts_skipped_reason,
            include_json_summary=bool(args.print_json_summary),
        )
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
