from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mongodb import collection_counts, ping_mongodb


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test MongoDB Atlas connection.")
    parser.add_argument("--counts", action="store_true", help="Also count items and retrieval_units.")
    args = parser.parse_args()

    result = ping_mongodb()
    if args.counts and result.get("ok"):
        result["counts"] = collection_counts()
    print(json.dumps(result, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

