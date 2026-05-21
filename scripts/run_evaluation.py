#!/usr/bin/env python
"""Run the full evaluation pipeline for ColdStart_Killer.

Usage:
    python scripts/run_evaluation.py \\
        --queries evaluation/queries/retrieval_queries_seed.json \\
        --judgments evaluation/judgments/retrieval_judgments_seed.json \\
        --out .runtime/evaluation/eval_seed \\
        --top-k 10 \\
        --k-values 1 3 5 10 \\
        --relevance-threshold 2 \\
        --variants title_only vector_only bm25_only hybrid_union hybrid_no_cold_boost

    # Smoke test (no MongoDB/Ollama/BGE-M3 required):
    python scripts/run_evaluation.py \\
        --queries evaluation/queries/retrieval_queries_seed.json \\
        --judgments evaluation/judgments/retrieval_judgments_seed.json \\
        --out .runtime/evaluation/smoke \\
        --use-fake-results
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.contracts import RunConfig, validate_run_config
from src.evaluation.dataset import load_eval_queries, load_relevance_judgments
from src.evaluation.reporting import write_evaluation_outputs
from src.evaluation.runner import run_evaluation
from src.evaluation.variants import EVALUATION_VARIANTS


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run ColdStart_Killer retrieval evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--queries", required=True, help="Path to retrieval_queries_seed.json")
    parser.add_argument("--judgments", required=True, help="Path to retrieval_judgments_seed.json")
    parser.add_argument("--out", required=True, help="Output directory for artifacts")
    parser.add_argument("--top-k", type=int, default=10, help="Top K results per variant (default: 10)")
    parser.add_argument("--k-values", type=int, nargs="+", default=[1, 3, 5, 10], help="K values for metrics")
    parser.add_argument("--relevance-threshold", type=int, default=2, help="Binary relevance threshold")
    parser.add_argument(
        "--variants", nargs="+", default=list(EVALUATION_VARIANTS),
        help=f"Variants to run (default: {' '.join(EVALUATION_VARIANTS)})",
    )
    parser.add_argument("--use-fake-results", action="store_true", help="Use fake results for smoke testing")
    parser.add_argument("--use-cached-fixtures", action="store_true", default=False, help="Use cached fixtures")
    parser.add_argument("--allow-stale-fixtures", action="store_true", default=False, help="Allow stale fixture cache")

    args = parser.parse_args()

    # Validate inputs
    queries_path = Path(args.queries)
    judgments_path = Path(args.judgments)
    if not queries_path.exists():
        print(f"ERROR: Queries file not found: {queries_path}", file=sys.stderr)
        return 1
    if not judgments_path.exists():
        print(f"ERROR: Judgments file not found: {judgments_path}", file=sys.stderr)
        return 1

    # Validate variants
    for v in args.variants:
        if v not in EVALUATION_VARIANTS:
            print(f"ERROR: Invalid variant: {v!r}. Valid: {EVALUATION_VARIANTS}", file=sys.stderr)
            return 1

    # Load data
    try:
        queries = load_eval_queries(queries_path)
        judgments = load_relevance_judgments(judgments_path)
    except Exception as exc:
        print(f"ERROR: Failed to load input files: {exc}", file=sys.stderr)
        return 1

    if not queries:
        print("ERROR: No queries loaded", file=sys.stderr)
        return 1

    # Build config
    config = RunConfig(
        run_id=Path(args.out).name,
        queries_path=str(queries_path),
        judgments_path=str(judgments_path),
        output_dir=str(args.out),
        variants=args.variants,
        top_k=args.top_k,
        k_values=args.k_values,
        relevance_threshold=args.relevance_threshold,
        use_cached_fixtures=args.use_cached_fixtures,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        git_commit=_git_commit(),
        plan_version="1.0",
        code_version="1.0",
        python_version=platform.python_version(),
        platform=platform.platform(),
    )

    try:
        validate_run_config(config)
    except Exception as exc:
        print(f"ERROR: Invalid config: {exc}", file=sys.stderr)
        return 1

    # Run evaluation
    print(f"Running evaluation: {config.run_id}")
    print(f"  Queries: {len(queries)}")
    print(f"  Judgments: {len(judgments)}")
    print(f"  Variants: {', '.join(config.variants)}")
    print(f"  Fake results: {args.use_fake_results}")
    print()

    t_start = time.perf_counter()
    run_data = run_evaluation(
        config=config,
        queries=queries,
        judgments=judgments,
        use_fake_results=args.use_fake_results,
    )
    t_end = time.perf_counter()

    # Write outputs
    paths = write_evaluation_outputs(run_data, args.out)

    # Print summary
    n_failures = len(run_data.get("failures", []))
    n_results = len(run_data.get("results", []))
    elapsed = t_end - t_start

    print(f"Evaluation completed in {elapsed:.1f}s")
    print(f"  Results: {n_results}")
    print(f"  Failures: {n_failures}")
    print()
    print("Artifacts written:")
    for name, path in sorted(paths.items()):
        print(f"  {name}: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
