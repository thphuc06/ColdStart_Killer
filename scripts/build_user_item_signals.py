from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.signal_builder import build_user_item_signals
from src.mongodb import (
    get_clickstream_events_collection,
    get_item_stats_collection,
    get_recommendation_logs_collection,
    get_user_item_signals_collection,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build user_item_signals from clickstream behavior.")
    parser.add_argument("--dry-run", action="store_true", help="Preview signal build without writing.")
    parser.add_argument("--write", action="store_true", help="Upsert user_item_signals and mark events processed.")
    parser.add_argument(
        "--rebuild-item-stats",
        action="store_true",
        help="Also rebuild derived item_stats from the same clickstream events.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum clickstream events to process.")
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
    result = build_user_item_signals(
        clickstream_events_collection=get_clickstream_events_collection(),
        recommendation_logs_collection=get_recommendation_logs_collection(),
        user_item_signals_collection=get_user_item_signals_collection() if write else None,
        item_stats_collection=get_item_stats_collection() if write and args.rebuild_item_stats else None,
        write=write,
        rebuild_item_stats=bool(args.rebuild_item_stats),
        limit_events=args.limit,
        batch_size=args.batch_size,
    )
    result["mode"] = "write" if write else "dry-run"
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
