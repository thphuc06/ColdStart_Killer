from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mongodb import (
    get_item_hype_profiles_collection,
    get_items_collection,
    get_retrieval_units_collection,
)
from src.recommendation.item_hype_profiles import build_item_hype_profiles


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build item_hype_profiles from HyPE retrieval units.")
    parser.add_argument("--dry-run", action="store_true", help="Preview profile build without writing.")
    parser.add_argument("--write", action="store_true", help="Upsert item_hype_profiles into MongoDB.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum item profiles to process.")
    parser.add_argument("--batch-size", type=int, default=500, help="Bulk write batch size.")
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

    write = bool(args.write)
    result = build_item_hype_profiles(
        retrieval_units_collection=get_retrieval_units_collection(),
        items_collection=get_items_collection(),
        item_hype_profiles_collection=get_item_hype_profiles_collection() if write else None,
        limit_profiles=args.limit,
        write=write,
        batch_size=args.batch_size,
    )
    result["mode"] = "write" if write else "dry-run"
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
