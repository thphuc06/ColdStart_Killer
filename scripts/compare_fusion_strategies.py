#!/usr/bin/env python
"""Compare search fusion strategies without changing production defaults.

Examples:
    python scripts/compare_fusion_strategies.py --dry-run
    python scripts/compare_fusion_strategies.py --dry-run --modes unionWith rankFusion
    python scripts/compare_fusion_strategies.py --dry-run --write-artifacts
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.fusion_comparison import (  # noqa: E402
    DEFAULT_FUSION_QUERIES,
    FusionComparisonConfig,
    build_catalog_backed_query_fixture,
    run_fusion_comparison,
    write_fusion_comparison_artifact,
)


def _default_output_dir() -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return ROOT / ".runtime" / "fusion_comparison" / stamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare stable unionWith/manual RRF search with optional native fusion. "
            "This is read-only and never writes MongoDB."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit read-only mode. This script is read-only by design and defaults to dry-run behavior.",
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        default=list(DEFAULT_FUSION_QUERIES),
        help="Queries to compare. Defaults to a small non-sensitive smoke set.",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["unionWith", "rankFusion", "scoreFusion"],
        default=["unionWith", "rankFusion", "scoreFusion"],
        help="Fusion modes to compare. scoreFusion is reported as not implemented unless code support exists.",
    )
    parser.add_argument("--top-k", type=int, default=10, help="Top-k results to compare.")
    parser.add_argument("--strict", action="store_true", help="Fail on unsupported native fusion instead of skipping.")
    parser.add_argument(
        "--live-query-processing",
        action="store_true",
        help=(
            "Use process_query() and the configured embedding model. By default the script uses a "
            "catalog-backed smoke fixture to avoid local model latency."
        ),
    )
    parser.add_argument(
        "--write-artifacts",
        action="store_true",
        help="Write a local JSON report under .runtime/fusion_comparison. Does not write MongoDB.",
    )
    parser.add_argument("--out", default=str(_default_output_dir()), help="Local artifact output directory.")
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print full JSON report instead of the compact terminal summary.",
    )
    return parser


def _format_mode_summary(mode: str, row: dict[str, object]) -> str:
    return (
        f"  {mode}: queries={row.get('queries')}, ok={row.get('ok', 0)}, "
        f"unsupported={row.get('unsupported', 0)}, errors={row.get('error', 0)}, "
        f"not_implemented={row.get('not_implemented', 0)}, "
        f"avg_latency_ms={row.get('avg_latency_ms')}, "
        f"avg_overlap_vs_unionWith={row.get('avg_overlap_vs_unionWith')}"
    )


def _print_summary(report: dict[str, object], *, artifact_path: Path | None) -> None:
    print("Fusion comparison completed")
    print("  dry_run: true")
    print("  MongoDB write: false")
    print("  default_search_mode: unionWith/manual RRF (unchanged)")
    print(f"  query_processing: {report.get('query_processing_mode')}")
    print(f"  scoreFusion: {report.get('score_fusion_status')}")
    print(f"  caveat: {report.get('caveat')}")
    print("  summary:")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    for mode, row in sorted(summary.items()):
        if isinstance(row, dict):
            print(_format_mode_summary(str(mode), row))
    if artifact_path:
        print(f"  artifact: {artifact_path}")
    else:
        print("  artifact: skipped (use --write-artifacts to save local JSON)")

    queries = report.get("queries") if isinstance(report.get("queries"), list) else []
    for query_result in queries:
        if not isinstance(query_result, dict):
            continue
        print(f"  query: {query_result.get('query')}")
        for row in query_result.get("modes", []):
            if not isinstance(row, dict):
                continue
            print(
                "    "
                f"{row.get('mode')}: status={row.get('status')}, "
                f"results={row.get('result_count')}, "
                f"latency_ms={row.get('latency_ms')}, "
                f"overlap={row.get('top_k_overlap_vs_unionWith')}"
            )
            if row.get("message"):
                print(f"      note: {row.get('message')}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.top_k <= 0:
        print("ERROR: --top-k must be positive", file=sys.stderr)
        return 2
    config = FusionComparisonConfig(
        queries=tuple(args.queries),
        modes=tuple(args.modes),  # type: ignore[arg-type]
        top_k=args.top_k,
        strict=bool(args.strict),
    )
    try:
        if args.live_query_processing:
            report = run_fusion_comparison(config=config)
            report["query_processing_mode"] = "process_query"
        else:
            report = run_fusion_comparison(
                config=config,
                process_query_fn=build_catalog_backed_query_fixture,
            )
            report["query_processing_mode"] = "catalog_backed_fixture"
            report["query_processing_caveat"] = (
                "Default CLI smoke uses a real catalog embedding fixture to avoid loading the local "
                "embedding model. Use --live-query-processing for true process_query() comparison."
            )
    except Exception as exc:
        print(f"ERROR: fusion comparison failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    artifact_path = None
    if args.write_artifacts:
        artifact_path = write_fusion_comparison_artifact(report, args.out)

    if args.print_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        _print_summary(report, artifact_path=artifact_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
