from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mongodb import (
    get_item_item_cf_edges_collection,
    get_items_collection,
    get_user_item_signals_collection,
)
from src.recommendation.item_item_cf import build_item_item_cf_edges


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build item_item_cf_edges from multi-user implicit behavior signals.")
    parser.add_argument("--dry-run", action="store_true", help="Preview CF edge build without writing.")
    parser.add_argument("--write", action="store_true", help="Upsert item_item_cf_edges into MongoDB.")
    parser.add_argument("--limit-users", type=int, default=None, help="Maximum users to process.")
    parser.add_argument("--batch-size", type=int, default=500, help="Bulk write batch size.")
    parser.add_argument("--min-support", type=int, default=2, help="Minimum multi-user support required for a CF edge.")
    parser.add_argument(
        "--max-items-per-user",
        type=int,
        default=30,
        help="Cap positive items per user before generating item pairs.",
    )
    parser.add_argument(
        "--top-neighbors-per-item",
        type=int,
        default=50,
        help="Maximum retained CF neighbors per source item.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="On a full write rebuild, remove stored CF edges absent from the rebuilt graph.",
    )
    parser.add_argument(
        "--input-policy",
        choices=("current_supported", "qualified_deliberate"),
        default=None,
        help="CF signal eligibility policy. Writes are allowed only for the configured runtime policy.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.write:
        print("ERROR: choose either --dry-run or --write, not both.", file=sys.stderr)
        return 2
    if args.limit_users is not None and args.limit_users <= 0:
        print("ERROR: --limit-users must be positive.", file=sys.stderr)
        return 2
    if args.batch_size <= 0:
        print("ERROR: --batch-size must be positive.", file=sys.stderr)
        return 2
    if args.min_support <= 0:
        print("ERROR: --min-support must be positive.", file=sys.stderr)
        return 2
    if args.max_items_per_user <= 1:
        print("ERROR: --max-items-per-user must be greater than 1.", file=sys.stderr)
        return 2
    if args.top_neighbors_per_item <= 0:
        print("ERROR: --top-neighbors-per-item must be positive.", file=sys.stderr)
        return 2
    if args.replace_existing and args.limit_users is not None:
        print("ERROR: --replace-existing cannot be combined with --limit-users.", file=sys.stderr)
        return 2

    write = bool(args.write)
    result = build_item_item_cf_edges(
        user_item_signals_collection=get_user_item_signals_collection(),
        items_collection=get_items_collection(),
        item_item_cf_edges_collection=get_item_item_cf_edges_collection() if write else None,
        write=write,
        limit_users=args.limit_users,
        batch_size=args.batch_size,
        min_support=args.min_support,
        max_items_per_user=args.max_items_per_user,
        top_neighbors_per_item=args.top_neighbors_per_item,
        replace_existing=bool(args.replace_existing),
        input_policy=args.input_policy,
    )
    result["mode"] = "write" if write else "dry-run"
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
