#!/usr/bin/env python
"""Import human judgments from labeled CSV to JSON format.

Usage:
    python scripts/import_eval_judgments.py \
        --csv .runtime/evaluation/pool_seed/judgment_pool.csv \
        --out evaluation/judgments/retrieval_judgments_seed.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.contracts import RelevanceJudgment, validate_relevance_judgment, ContractValidationError


def main() -> int:
    parser = argparse.ArgumentParser(description="Import labeled CSV pool to evaluation JSON format")
    parser.add_argument("--csv", required=True, help="Path to labeled judgment_pool.csv")
    parser.add_argument("--out", default="evaluation/judgments/retrieval_judgments_seed.json", help="Output JSON path")
    parser.add_argument("--strict", action="store_true", help="Raise error if relevance is empty/invalid instead of skipping")

    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    out_path = Path(args.out)

    judgments = []
    skipped_empty = 0
    skipped_invalid = 0
    imported = 0
    seen_pairs = set()

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):  # header is row 1
            query_id = row.get("query_id", "").strip()
            item_id = row.get("item_id", "").strip()
            relevance_str = row.get("relevance", "").strip()
            reason = row.get("reason", "").strip()
            labels_str = row.get("labels", "").strip()

            if not query_id or not item_id:
                print(f"WARNING: Row {row_idx} is missing query_id or item_id. Skipped.", file=sys.stderr)
                continue

            pair = (query_id, item_id)
            if pair in seen_pairs:
                # Duplicates can happen if multiple variants returned the same product for the same query,
                # but build_eval_pool.py deduplicates them. Just in case there are duplicates in the CSV:
                continue

            if not relevance_str:
                if args.strict:
                    print(f"ERROR: Row {row_idx} has empty relevance, but --strict is enabled.", file=sys.stderr)
                    return 1
                skipped_empty += 1
                continue

            try:
                # Attempt to parse relevance as int
                relevance = int(float(relevance_str))
            except ValueError:
                if args.strict:
                    print(f"ERROR: Row {row_idx} has invalid relevance value '{relevance_str}'.", file=sys.stderr)
                    return 1
                print(f"WARNING: Row {row_idx} has invalid relevance value '{relevance_str}'. Skipped.", file=sys.stderr)
                skipped_invalid += 1
                continue

            # Parse labels
            labels = [l.strip() for l in labels_str.split(",") if l.strip()] if labels_str else []

            # Create and validate contract
            try:
                j = RelevanceJudgment(
                    query_id=query_id,
                    item_id=item_id,
                    relevance=relevance,
                    reason=reason,
                    labels=labels
                )
                validate_relevance_judgment(j)
            except (ContractValidationError, ValueError) as exc:
                if args.strict:
                    print(f"ERROR: Row {row_idx} failed validation: {exc}", file=sys.stderr)
                    return 1
                print(f"WARNING: Row {row_idx} failed validation: {exc}. Skipped.", file=sys.stderr)
                skipped_invalid += 1
                continue

            # Convert to dictionary representation for writing to JSON
            judgments.append({
                "query_id": j.query_id,
                "item_id": j.item_id,
                "relevance": j.relevance,
                "reason": j.reason,
                "labels": j.labels
            })
            seen_pairs.add(pair)
            imported += 1

    # Ensure parent directory of output exists
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(judgments, f, indent=2, ensure_ascii=False)

    print(f"\nSuccessfully imported {imported} judgments to {out_path}")
    print(f"Skipped {skipped_empty} empty rows")
    if skipped_invalid > 0:
        print(f"Skipped {skipped_invalid} invalid/malformed rows")

    return 0


if __name__ == "__main__":
    sys.exit(main())
