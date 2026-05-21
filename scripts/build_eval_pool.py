#!/usr/bin/env python
"""Build the judgment pool for manual labeling.

Usage:
    python scripts/build_eval_pool.py \\
        --queries evaluation/queries/retrieval_queries_seed.json \\
        --out .runtime/evaluation/pool_seed \\
        --top-k 20 \\
        --variants title_only vector_only bm25_only hybrid_union hybrid_no_cold_boost
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.contracts import RunConfig
from src.evaluation.dataset import load_eval_queries
from src.evaluation.runner import load_or_build_fixtures
from src.evaluation.variants import EVALUATION_VARIANTS, run_variant


def main() -> int:
    parser = argparse.ArgumentParser(description="Build judgment pool for manual labeling")
    parser.add_argument("--queries", required=True, help="Path to retrieval_queries_seed.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--top-k", type=int, default=20, help="Top K results per variant (default: 20)")
    parser.add_argument(
        "--variants", nargs="+", default=list(EVALUATION_VARIANTS),
        help=f"Variants to run (default: {' '.join(EVALUATION_VARIANTS)})",
    )
    parser.add_argument("--use-fake-results", action="store_true", help="Use fake results for testing")

    args = parser.parse_args()

    queries_path = Path(args.queries)
    if not queries_path.exists():
        print(f"ERROR: Queries file not found: {queries_path}", file=sys.stderr)
        return 1

    queries = load_eval_queries(queries_path)
    print(f"Loaded {len(queries)} queries")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build fixtures
    fixture_path = out_dir / "query_fixtures.json"
    fixtures, fix_failures = load_or_build_fixtures(
        queries, fixture_path,
        use_cache=False,
        use_fake=args.use_fake_results,
    )

    # Run all variants and collect pool
    pool_rows: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    all_failures = list(fix_failures)

    for query in queries:
        fixture = fixtures.get(query.query_id)
        if fixture is None:
            continue

        for variant in args.variants:
            from src.evaluation.runner import _build_fake_results

            if args.use_fake_results:
                results = _build_fake_results(query.query_id, variant, args.top_k)
                failure = None
            else:
                results, failure = run_variant(
                    fixture, variant, query.query_id, args.top_k,
                )

            if failure:
                all_failures.append(failure)
                continue

            for r in results:
                pair = (query.query_id, r.item_id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                pool_rows.append({
                    "query_id": query.query_id,
                    "raw_query": query.raw_query,
                    "slices": ",".join(query.slices),
                    "variant": variant,
                    "rank": r.rank,
                    "item_id": r.item_id,
                    "title": r.title,
                    "brand": r.brand,
                    "category_id": r.category_id,
                    "price_vnd": r.price_vnd or "",
                    "price_bucket": r.price_bucket,
                    "matched_intent": r.matched_intent,
                    "matched_fact": r.matched_fact,
                    "score": r.score,
                    "channels": ",".join(r.channels),
                    "relevance": "",
                    "reason": "",
                    "labels": "",
                })

    # Write judgment_pool.csv
    pool_path = out_dir / "judgment_pool.csv"
    if pool_rows:
        with pool_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(pool_rows[0].keys()))
            writer.writeheader()
            writer.writerows(pool_rows)

    # Write failures
    from dataclasses import asdict
    with (out_dir / "failures.json").open("w", encoding="utf-8") as f:
        json.dump([asdict(f_) if hasattr(f_, '__dataclass_fields__') else f_ for f_ in all_failures],
                  f, indent=2, ensure_ascii=False, default=str)

    # Manifest
    with (out_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump({
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "artifacts": [
                {"path": "judgment_pool.csv", "type": "judgment_pool"},
                {"path": "failures.json", "type": "failures"},
            ],
        }, f, indent=2)

    print(f"\nJudgment pool: {len(pool_rows)} unique (query, item) pairs")
    print(f"Failures: {len(all_failures)}")
    print(f"Written to {pool_path}")
    print()
    print("Fill relevance, reason, and labels columns in the CSV.")
    print("Then convert judged rows into evaluation/judgments/retrieval_judgments_seed.json using:")
    print("  python scripts/import_eval_judgments.py --csv <path_to_csv> --out evaluation/judgments/retrieval_judgments_seed.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
