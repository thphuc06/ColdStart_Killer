from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import get_settings


CATALOG_COLLECTIONS: set[str] = {"items", "retrieval_units"}
SOFT_RESET_FILTER: dict[str, Any] = {"is_synthetic": {"$ne": True}}
SOFT_RESET_COLLECTIONS: tuple[str, ...] = ("recommendation_logs", "clickstream_events")
SOFT_RESET_KEEP_COLLECTIONS: tuple[str, ...] = (
    "items",
    "retrieval_units",
    "item_hype_profiles",
    "item_semantic_neighbors",
    "item_item_cf_edges",
    "synthetic_personas",
)
FULL_RESET_COLLECTIONS: tuple[str, ...] = (
    "recommendation_logs",
    "clickstream_events",
    "user_item_signals",
    "user_profiles",
    "item_stats",
    "item_item_cf_edges",
)
FULL_RESET_KEEP_COLLECTIONS: tuple[str, ...] = (
    "items",
    "retrieval_units",
    "item_hype_profiles",
    "synthetic_personas",
)
REBUILD_ORDER_AFTER_FULL_RESET: tuple[str, ...] = (
    "python scripts/seed_synthetic_clickstream.py --dry-run",
    "python scripts/seed_synthetic_clickstream.py --write",
    "python scripts/build_user_item_signals.py --dry-run --rebuild-item-stats",
    "python scripts/build_user_item_signals.py --write --rebuild-item-stats",
    "python scripts/build_user_profiles.py --dry-run",
    "python scripts/build_user_profiles.py --write",
    "python scripts/build_item_item_cf.py --dry-run",
    "python scripts/build_item_item_cf.py --write",
    "python scripts/build_item_semantic_neighbors.py --dry-run",
)
REBUILD_ORDER_AFTER_SOFT_RESET: tuple[str, ...] = (
    "Use existing seeded/precomputed synthetic CF edges for quick recovery.",
    "Optionally process new live demo events: python scripts/build_user_item_signals.py --dry-run --rebuild-item-stats",
    "Optionally rebuild profiles/CF if you want the current session reflected in downstream artifacts.",
)


@dataclass(frozen=True)
class ResetTarget:
    collection: str
    filter: dict[str, Any]


def build_reset_targets(*, full: bool, include_semantic_neighbors: bool = False) -> list[ResetTarget]:
    if full:
        names = list(FULL_RESET_COLLECTIONS)
        if include_semantic_neighbors:
            names.append("item_semantic_neighbors")
        targets = [ResetTarget(collection=name, filter={}) for name in names]
    else:
        targets = [ResetTarget(collection=name, filter=dict(SOFT_RESET_FILTER)) for name in SOFT_RESET_COLLECTIONS]
    validate_reset_targets(targets)
    return targets


def validate_reset_targets(targets: list[ResetTarget]) -> None:
    blocked = sorted({target.collection for target in targets if target.collection in CATALOG_COLLECTIONS})
    if blocked:
        raise ValueError(f"Refusing to reset catalog collections: {', '.join(blocked)}")


def _required_confirmation(full: bool) -> str:
    return "FULL_DEMO_RESET" if full else "DEMO_RESET"


def _mode_label(write: bool) -> str:
    return "write" if write else "dry-run"


def rebuild_order_for_reset(*, full: bool, include_semantic_neighbors: bool = False) -> list[str]:
    if not full:
        return list(REBUILD_ORDER_AFTER_SOFT_RESET)
    steps = list(REBUILD_ORDER_AFTER_FULL_RESET)
    if include_semantic_neighbors:
        steps.append("python scripts/build_item_semantic_neighbors.py --write")
    else:
        steps.append("item_semantic_neighbors kept unless --include-semantic-neighbors is used.")
    return steps


def execute_reset(
    database: Any,
    *,
    full: bool,
    write: bool,
    confirm: str | None = None,
    include_semantic_neighbors: bool = False,
) -> dict[str, Any]:
    if write and confirm != _required_confirmation(full):
        raise RuntimeError(
            f"Confirmation required. Pass --confirm {_required_confirmation(full)} for this reset mode."
        )

    targets = build_reset_targets(full=full, include_semantic_neighbors=include_semantic_neighbors)
    counts = {
        target.collection: database[target.collection].count_documents(target.filter) for target in targets
    }
    result: dict[str, Any] = {
        "mode": _mode_label(write),
        "reset_type": "full" if full else "soft",
        "dry_run": not write,
        "protected_collections": sorted(CATALOG_COLLECTIONS),
        "kept_collections": list(FULL_RESET_KEEP_COLLECTIONS if full else SOFT_RESET_KEEP_COLLECTIONS),
        "precomputed_cf_note": (
            "Soft reset keeps seeded/precomputed item_item_cf_edges for quick demo recovery."
            if not full
            else "Full reset clears item_item_cf_edges so CF must be rebuilt from user_item_signals."
        ),
        "rebuild_order": rebuild_order_for_reset(
            full=full,
            include_semantic_neighbors=include_semantic_neighbors,
        ),
        "targets": [
            {"collection": target.collection, "filter": target.filter, "matched_count": counts[target.collection]}
            for target in targets
        ],
    }
    if not write:
        return result

    deleted = {
        target.collection: database[target.collection].delete_many(target.filter).deleted_count for target in targets
    }
    result["deleted"] = deleted
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Safely reset behavior/recommendation demo data. Dry-run is the default. "
            "This script never targets items or retrieval_units."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--soft", action="store_true", help="Reset non-synthetic live demo logs/events only.")
    mode.add_argument("--full", action="store_true", help="Reset behavior-derived collections.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode. This is also the default.")
    parser.add_argument("--write", action="store_true", help="Actually delete matched behavior docs.")
    parser.add_argument("--confirm", default=None, help="Required confirmation string for --write.")
    parser.add_argument(
        "--include-semantic-neighbors",
        action="store_true",
        help="With --full, also clear item_semantic_neighbors for a complete semantic-neighbor rebuild.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    full = bool(args.full)
    if args.dry_run and args.write:
        print("ERROR: choose either --dry-run or --write, not both.", file=sys.stderr)
        return 2
    if args.include_semantic_neighbors and not full:
        print("ERROR: --include-semantic-neighbors requires --full.", file=sys.stderr)
        return 2

    settings = get_settings()
    payload: dict[str, Any] = {
        "target_database": settings.mongodb_db_name,
        "write_requested": bool(args.write),
        "required_confirmation": _required_confirmation(full),
        "catalog_collections_protected": sorted(CATALOG_COLLECTIONS),
    }
    if args.write and args.confirm != _required_confirmation(full):
        payload["ok"] = False
        payload["error"] = f"Confirmation required. Pass --confirm {_required_confirmation(full)} for this reset mode."
        print(json.dumps(payload, indent=2))
        return 2
    if args.write:
        print(
            json.dumps(
                {
                    "preflight": "about_to_write",
                    "target_database": settings.mongodb_db_name,
                    "required_confirmation": _required_confirmation(full),
                    "protected_collections": sorted(CATALOG_COLLECTIONS),
                },
                indent=2,
            ),
            file=sys.stderr,
        )

    try:
        from src.mongodb import get_database

        payload.update(
            execute_reset(
                get_database(),
                full=full,
                write=bool(args.write),
                confirm=args.confirm,
                include_semantic_neighbors=bool(args.include_semantic_neighbors),
            )
        )
    except Exception as exc:
        payload["ok"] = False
        payload["error"] = str(exc)
        print(json.dumps(payload, indent=2))
        return 2

    payload["ok"] = True
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
