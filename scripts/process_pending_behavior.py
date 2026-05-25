from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.incremental_processor import process_pending_behavior
from src.mongodb import (
    get_clickstream_events_collection,
    get_item_hype_profiles_collection,
    get_item_stats_collection,
    get_items_collection,
    get_recommendation_logs_collection,
    get_retrieval_units_collection,
    get_user_item_signals_collection,
    get_user_profiles_collection,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally apply pending behavior to complete affected signals, item stats, and profiles."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview the pending batch without writing MongoDB.")
    mode.add_argument("--write", action="store_true", help="Apply the pending batch and mark selected events processed.")
    parser.add_argument("--max-events", type=int, default=100, help="Maximum pending events to apply in timestamp order.")
    parser.add_argument(
        "--no-item-stats",
        action="store_true",
        help="Skip item_stats recomputation for this batch.",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="Bulk write batch size.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_events <= 0:
        print("ERROR: --max-events must be positive.", file=sys.stderr)
        return 2
    if args.batch_size <= 0:
        print("ERROR: --batch-size must be positive.", file=sys.stderr)
        return 2

    write = bool(args.write)
    rebuild_item_stats = not bool(args.no_item_stats)
    result = process_pending_behavior(
        clickstream_events_collection=get_clickstream_events_collection(),
        recommendation_logs_collection=get_recommendation_logs_collection(),
        user_item_signals_collection=get_user_item_signals_collection() if write else None,
        item_stats_collection=get_item_stats_collection() if write and rebuild_item_stats else None,
        user_profiles_collection=get_user_profiles_collection() if write else None,
        item_hype_profiles_collection=get_item_hype_profiles_collection() if write else None,
        items_collection=get_items_collection() if write else None,
        retrieval_units_collection=get_retrieval_units_collection() if write else None,
        write=write,
        rebuild_item_stats=rebuild_item_stats,
        max_events=args.max_events,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
