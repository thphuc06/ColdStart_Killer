from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mongodb import get_items_collection, get_retrieval_units_collection


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear ColdStart Killer demo data.")
    parser.add_argument("--yes", action="store_true", help="Required confirmation.")
    parser.add_argument("--seller-only", action="store_true", help="Only clear seller UI inserted items.")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Refusing to delete data without --yes.")

    items = get_items_collection()
    retrieval_units = get_retrieval_units_collection()
    if args.seller_only:
        item_filter = {"source_dataset": "seller_ui"}
    else:
        item_filter = {"source_dataset": {"$in": ["Amazon Reviews 2023", "seller_ui"]}}

    item_ids = [doc["_id"] for doc in items.find(item_filter, {"_id": 1})]
    retrieval_result = retrieval_units.delete_many({"item_id": {"$in": item_ids}}) if item_ids else None
    item_result = items.delete_many(item_filter)
    print(
        json.dumps(
            {
                "deleted_items": item_result.deleted_count,
                "deleted_retrieval_units": retrieval_result.deleted_count if retrieval_result else 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

