from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.synthetic_generator import (
    DEFAULT_ITEMS_PER_REQUEST,
    DEFAULT_REQUESTS_PER_USER,
    DEFAULT_SEED,
    DEFAULT_SYNTHETIC_USERS,
    build_synthetic_behavior_plan,
    load_candidates_from_collections,
    write_synthetic_behavior_plan,
)
from src.mongodb import (
    get_clickstream_events_collection,
    get_item_hype_profiles_collection,
    get_items_collection,
    get_recommendation_logs_collection,
    get_synthetic_personas_collection,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed synthetic behavior logs and clickstream events.")
    parser.add_argument("--dry-run", action="store_true", help="Build the synthetic plan without writing.")
    parser.add_argument("--write", action="store_true", help="Write synthetic personas, recommendation logs, and events.")
    parser.add_argument("--users", type=int, default=DEFAULT_SYNTHETIC_USERS, help="Number of synthetic users.")
    parser.add_argument(
        "--requests-per-user",
        type=int,
        default=DEFAULT_REQUESTS_PER_USER,
        help="Recommendation requests per synthetic user.",
    )
    parser.add_argument(
        "--items-per-request",
        type=int,
        default=DEFAULT_ITEMS_PER_REQUEST,
        help="Shown items per synthetic request.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic random seed.")
    parser.add_argument("--candidate-limit", type=int, default=None, help="Optional catalog candidate limit.")
    return parser.parse_args(argv)


def _positive_or_none(value: int | None, name: str) -> str | None:
    if value is not None and value <= 0:
        return f"{name} must be positive"
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.write:
        print("ERROR: choose either --dry-run or --write, not both.", file=sys.stderr)
        return 2
    for value, name in (
        (args.users, "--users"),
        (args.requests_per_user, "--requests-per-user"),
        (args.items_per_request, "--items-per-request"),
        (args.candidate_limit, "--candidate-limit"),
    ):
        error = _positive_or_none(value, name)
        if error:
            print(f"ERROR: {error}.", file=sys.stderr)
            return 2

    candidates = load_candidates_from_collections(
        items_collection=get_items_collection(),
        item_hype_profiles_collection=get_item_hype_profiles_collection(),
        limit=args.candidate_limit,
    )
    plan = build_synthetic_behavior_plan(
        candidates=candidates,
        users=args.users,
        requests_per_user=args.requests_per_user,
        items_per_request=args.items_per_request,
        seed=args.seed,
    )

    output = {
        "mode": "write" if args.write else "dry-run",
        "seed": args.seed,
        "candidate_count": len(candidates),
        "summary": plan["summary"],
        "samples": plan["samples"],
        "write_result": None,
    }

    if args.write:
        output["write_result"] = write_synthetic_behavior_plan(
            plan=plan,
            synthetic_personas_collection=get_synthetic_personas_collection(),
            recommendation_logs_collection=get_recommendation_logs_collection(),
            clickstream_events_collection=get_clickstream_events_collection(),
        )

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
