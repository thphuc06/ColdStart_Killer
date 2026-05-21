from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.indexing import DEFAULT_LIMIT, first_uninserted_index_from_mongodb, index_items_from_dataframe
from src.validation import assert_required_columns


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and index MVP items into MongoDB.")
    parser.add_argument("--csv", default="analysis/mvp_3000_items_diverse.csv", help="Input MVP CSV.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Item limit. Default: 50.")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based CSV row offset to start indexing from.")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Start from the first CSV row whose parent_asin is not already present in MongoDB items.",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="Delay between sequential Ollama calls.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Prepare docs with Ollama/embeddings but do not write MongoDB.",
    )
    parser.add_argument("--write", action="store_true", help="Write to MongoDB.")
    args = parser.parse_args()

    csv_path = ROOT / args.csv
    df = pd.read_csv(csv_path)
    assert_required_columns(df)
    start_index = first_uninserted_index_from_mongodb(df) if args.resume else args.start_index
    result = index_items_from_dataframe(
        df,
        limit=args.limit,
        dry_run=not args.write,
        sleep_seconds=args.sleep_seconds,
        start_index=start_index,
    )
    result["resume"] = args.resume
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
