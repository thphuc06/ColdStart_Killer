from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mongodb import (
    get_item_hype_profiles_collection,
    get_item_semantic_neighbors_collection,
    get_items_collection,
    get_retrieval_units_collection,
)
from src.recommendation.semantic_neighbors import build_item_semantic_neighbors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build semantic item neighbors from item_hype_profiles and Atlas vector search.")
    parser.add_argument("--dry-run", action="store_true", help="Preview semantic neighbor build without writing.")
    parser.add_argument("--write", action="store_true", help="Upsert item_semantic_neighbors into MongoDB.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum source item profiles to process.")
    parser.add_argument("--batch-size", type=int, default=500, help="Bulk write batch size.")
    parser.add_argument(
        "--hit-limit",
        type=int,
        default=100,
        help="Maximum retrieval-unit vector hits to inspect per source item.",
    )
    parser.add_argument(
        "--top-neighbors-per-item",
        type=int,
        default=50,
        help="Maximum semantic neighbors retained per source item.",
    )
    parser.add_argument(
        "--num-candidates",
        type=int,
        default=400,
        help="Atlas vector search numCandidates value for each source item query.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.write:
        print("ERROR: choose either --dry-run or --write, not both.", file=sys.stderr)
        return 2
    if args.limit is not None and args.limit <= 0:
        print("ERROR: --limit must be positive.", file=sys.stderr)
        return 2
    if args.batch_size <= 0:
        print("ERROR: --batch-size must be positive.", file=sys.stderr)
        return 2
    if args.hit_limit <= 0:
        print("ERROR: --hit-limit must be positive.", file=sys.stderr)
        return 2
    if args.top_neighbors_per_item <= 0:
        print("ERROR: --top-neighbors-per-item must be positive.", file=sys.stderr)
        return 2
    if args.num_candidates < args.hit_limit:
        print("ERROR: --num-candidates must be greater than or equal to --hit-limit.", file=sys.stderr)
        return 2

    write = bool(args.write)
    result = build_item_semantic_neighbors(
        item_hype_profiles_collection=get_item_hype_profiles_collection(),
        retrieval_units_collection=get_retrieval_units_collection(),
        items_collection=get_items_collection(),
        item_semantic_neighbors_collection=get_item_semantic_neighbors_collection() if write else None,
        write=write,
        limit_profiles=args.limit,
        batch_size=args.batch_size,
        retrieval_hit_limit=args.hit_limit,
        top_neighbors_per_item=args.top_neighbors_per_item,
        num_candidates=args.num_candidates,
    )
    result["mode"] = "write" if write else "dry-run"
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") or result.get("status") == "semantic_neighbors_unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())