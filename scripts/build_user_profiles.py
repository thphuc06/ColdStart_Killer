from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.profile_builder import build_user_profiles
from src.mongodb import (
    get_clickstream_events_collection,
    get_item_hype_profiles_collection,
    get_items_collection,
    get_retrieval_units_collection,
    get_recommendation_logs_collection,
    get_user_item_signals_collection,
    get_user_profiles_collection,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build behavior-derived user_profiles from signals and item embeddings.")
    parser.add_argument("--dry-run", action="store_true", help="Preview profile build without writing.")
    parser.add_argument("--write", action="store_true", help="Upsert user_profiles into MongoDB.")
    parser.add_argument("--limit-users", type=int, default=None, help="Maximum users to process.")
    parser.add_argument("--batch-size", type=int, default=500, help="Bulk write batch size.")
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

    write = bool(args.write)
    result = build_user_profiles(
        user_item_signals_collection=get_user_item_signals_collection(),
        clickstream_events_collection=get_clickstream_events_collection(),
        recommendation_logs_collection=get_recommendation_logs_collection(),
        item_hype_profiles_collection=get_item_hype_profiles_collection(),
        items_collection=get_items_collection(),
        retrieval_units_collection=get_retrieval_units_collection(),
        user_profiles_collection=get_user_profiles_collection() if write else None,
        write=write,
        limit_users=args.limit_users,
        batch_size=args.batch_size,
    )
    result["mode"] = "write" if write else "dry-run"
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())