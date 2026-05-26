from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, DESCENDING


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import get_settings


COLLECTION_NAMES: tuple[str, ...] = (
    "users",
    "sessions",
    "recommendation_logs",
    "clickstream_events",
    "user_item_signals",
    "user_profiles",
    "item_hype_profiles",
    "item_semantic_neighbors",
    "item_item_cf_edges",
    "item_stats",
    "query_embedding_cache",
    "seller_product_drafts",
    "web_enrichment_requests",
    "synthetic_personas",
    "evaluation_runs",
    "job_runs",
)


@dataclass(frozen=True)
class IndexSpec:
    collection: str
    keys: tuple[tuple[str, int], ...]
    name: str
    unique: bool = False
    partial_filter_expression: dict[str, Any] | None = None
    expire_after_seconds: int | None = None

    def kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"name": self.name}
        if self.unique:
            kwargs["unique"] = True
        if self.partial_filter_expression is not None:
            kwargs["partialFilterExpression"] = self.partial_filter_expression
        if self.expire_after_seconds is not None:
            kwargs["expireAfterSeconds"] = self.expire_after_seconds
        return kwargs

    def to_plan(self) -> dict[str, Any]:
        plan = {
            "collection": self.collection,
            "keys": [{"field": field, "direction": direction} for field, direction in self.keys],
            "name": self.name,
        }
        plan.update(self.kwargs())
        return plan


def _idx(
    collection: str,
    keys: tuple[tuple[str, int], ...],
    name: str,
    *,
    unique: bool = False,
    partial_filter_expression: dict[str, Any] | None = None,
    expire_after_seconds: int | None = None,
) -> IndexSpec:
    return IndexSpec(
        collection=collection,
        keys=keys,
        name=name,
        unique=unique,
        partial_filter_expression=partial_filter_expression,
        expire_after_seconds=expire_after_seconds,
    )


def build_index_specs(event_ttl_days: int = 0) -> list[IndexSpec]:
    ttl_seconds = event_ttl_days * 24 * 60 * 60 if event_ttl_days > 0 else None
    specs = [
        _idx("users", (("user_id_hash", ASCENDING),), "uniq_users_user_id_hash", unique=True),
        _idx("users", (("profile_status", ASCENDING),), "idx_users_profile_status"),
        _idx("sessions", (("session_id", ASCENDING),), "uniq_sessions_session_id", unique=True),
        _idx(
            "sessions",
            (("user_id_hash", ASCENDING), ("started_at", DESCENDING)),
            "idx_sessions_user_started_at",
        ),
        _idx(
            "recommendation_logs",
            (("request_id", ASCENDING), ("item_id", ASCENDING)),
            "uniq_recommendation_logs_request_item",
            unique=True,
        ),
        _idx(
            "recommendation_logs",
            (("user_id_hash", ASCENDING), ("shown_at", DESCENDING)),
            "idx_recommendation_logs_user_shown_at",
        ),
        _idx(
            "recommendation_logs",
            (("session_id", ASCENDING), ("shown_at", DESCENDING)),
            "idx_recommendation_logs_session_shown_at",
        ),
        _idx(
            "recommendation_logs",
            (("item_id", ASCENDING), ("shown_at", DESCENDING)),
            "idx_recommendation_logs_item_shown_at",
        ),
        _idx(
            "recommendation_logs",
            (("surface", ASCENDING), ("shown_at", DESCENDING)),
            "idx_recommendation_logs_surface_shown_at",
        ),
        _idx(
            "recommendation_logs",
            (("algorithm_version", ASCENDING), ("ranking_version", ASCENDING)),
            "idx_recommendation_logs_algorithm_ranking",
        ),
        _idx("clickstream_events", (("event_id", ASCENDING),), "uniq_clickstream_events_event_id", unique=True),
        _idx(
            "clickstream_events",
            (("idempotency_key", ASCENDING),),
            "uniq_clickstream_events_idempotency_key",
            unique=True,
            partial_filter_expression={"idempotency_key": {"$exists": True}},
        ),
        _idx(
            "clickstream_events",
            (("request_id", ASCENDING), ("item_id", ASCENDING)),
            "uniq_clickstream_events_impression_request_item",
            unique=True,
            partial_filter_expression={"event_type": "impression"},
        ),
        _idx(
            "clickstream_events",
            (("request_id", ASCENDING), ("item_id", ASCENDING), ("event_type", ASCENDING)),
            "idx_clickstream_events_request_item_type",
        ),
        _idx(
            "clickstream_events",
            (("user_id_hash", ASCENDING), ("timestamp", DESCENDING)),
            "idx_clickstream_events_user_timestamp",
        ),
        _idx(
            "clickstream_events",
            (("session_id", ASCENDING), ("timestamp", DESCENDING)),
            "idx_clickstream_events_session_timestamp",
        ),
        _idx(
            "clickstream_events",
            (("item_id", ASCENDING), ("event_type", ASCENDING), ("timestamp", DESCENDING)),
            "idx_clickstream_events_item_type_timestamp",
        ),
        _idx(
            "clickstream_events",
            (("processed", ASCENDING), ("timestamp", ASCENDING)),
            "idx_clickstream_events_processed_timestamp",
        ),
        _idx(
            "user_item_signals",
            (("user_id_hash", ASCENDING), ("item_id", ASCENDING)),
            "uniq_user_item_signals_user_item",
            unique=True,
        ),
        _idx(
            "user_item_signals",
            (("user_id_hash", ASCENDING), ("implicit_score", DESCENDING)),
            "idx_user_item_signals_user_score",
        ),
        _idx(
            "user_item_signals",
            (("item_id", ASCENDING), ("implicit_score", DESCENDING)),
            "idx_user_item_signals_item_score",
        ),
        _idx("user_item_signals", (("updated_at", DESCENDING),), "idx_user_item_signals_updated_at"),
        _idx("user_profiles", (("user_id_hash", ASCENDING),), "uniq_user_profiles_user_id_hash", unique=True),
        _idx("user_profiles", (("profile_status", ASCENDING),), "idx_user_profiles_profile_status"),
        _idx("user_profiles", (("updated_at", DESCENDING),), "idx_user_profiles_updated_at"),
        _idx("item_hype_profiles", (("item_id", ASCENDING),), "uniq_item_hype_profiles_item_id", unique=True),
        _idx("item_hype_profiles", (("category_id", ASCENDING),), "idx_item_hype_profiles_category_id"),
        _idx("item_hype_profiles", (("updated_at", DESCENDING),), "idx_item_hype_profiles_updated_at"),
        _idx(
            "item_semantic_neighbors",
            (("item_id", ASCENDING),),
            "uniq_item_semantic_neighbors_item_id",
            unique=True,
        ),
        _idx(
            "item_semantic_neighbors",
            (("neighbors.neighbor_item_id", ASCENDING),),
            "idx_item_semantic_neighbors_neighbor_item_id",
        ),
        _idx(
            "item_item_cf_edges",
            (("item_id", ASCENDING), ("neighbor_item_id", ASCENDING)),
            "uniq_item_item_cf_edges_item_neighbor",
            unique=True,
        ),
        _idx(
            "item_item_cf_edges",
            (("item_id", ASCENDING), ("cf_score", DESCENDING)),
            "idx_item_item_cf_edges_item_score",
        ),
        _idx(
            "item_item_cf_edges",
            (("neighbor_item_id", ASCENDING),),
            "idx_item_item_cf_edges_neighbor_item_id",
        ),
        _idx("item_item_cf_edges", (("support", DESCENDING),), "idx_item_item_cf_edges_support"),
        _idx("item_item_cf_edges", (("updated_at", DESCENDING),), "idx_item_item_cf_edges_updated_at"),
        _idx("item_stats", (("item_id", ASCENDING),), "uniq_item_stats_item_id", unique=True),
        _idx(
            "item_stats",
            (("cold_start.is_cold_item", ASCENDING), ("quality_score", DESCENDING)),
            "idx_item_stats_cold_quality",
        ),
        _idx("item_stats", (("ctr", DESCENDING),), "idx_item_stats_ctr"),
        _idx("item_stats", (("cold_start.interaction_count", DESCENDING),), "idx_item_stats_interaction_count"),
        _idx(
            "query_embedding_cache",
            (("query_hash", ASCENDING),),
            "uniq_query_embedding_cache_query_hash",
            unique=True,
        ),
        _idx(
            "query_embedding_cache",
            (("last_used_at", DESCENDING),),
            "idx_query_embedding_cache_last_used_at",
        ),
        _idx("seller_product_drafts", (("draft_id", ASCENDING),), "uniq_seller_product_drafts_draft_id", unique=True),
        _idx(
            "seller_product_drafts",
            (("seller_id", ASCENDING), ("created_at", DESCENDING)),
            "idx_seller_product_drafts_seller_created",
        ),
        _idx(
            "seller_product_drafts",
            (("status", ASCENDING), ("updated_at", DESCENDING)),
            "idx_seller_product_drafts_status_updated",
        ),
        _idx(
            "seller_product_drafts",
            (("proposed_item_id", ASCENDING),),
            "idx_seller_product_drafts_proposed_item_id",
        ),
        _idx(
            "web_enrichment_requests",
            (("request_id", ASCENDING),),
            "uniq_web_enrichment_requests_request_id",
            unique=True,
        ),
        _idx(
            "web_enrichment_requests",
            (("draft_id", ASCENDING), ("created_at", DESCENDING)),
            "idx_web_enrichment_requests_draft_created",
        ),
        _idx(
            "web_enrichment_requests",
            (("provider", ASCENDING), ("status", ASCENDING)),
            "idx_web_enrichment_requests_provider_status",
        ),
        _idx(
            "web_enrichment_requests",
            (("status", ASCENDING), ("updated_at", DESCENDING)),
            "idx_web_enrichment_requests_status_updated",
        ),
        _idx("synthetic_personas", (("persona_id", ASCENDING),), "uniq_synthetic_personas_persona_id", unique=True),
        _idx("evaluation_runs", (("run_id", ASCENDING),), "uniq_evaluation_runs_run_id", unique=True),
        _idx(
            "evaluation_runs",
            (("algorithm_version", ASCENDING), ("ranking_version", ASCENDING), ("created_at", DESCENDING)),
            "idx_evaluation_runs_algorithm_ranking_created",
        ),
        _idx("job_runs", (("job_run_id", ASCENDING),), "uniq_job_runs_job_run_id", unique=True),
        _idx(
            "job_runs",
            (("job_type", ASCENDING), ("created_at", DESCENDING)),
            "idx_job_runs_type_created",
        ),
        _idx(
            "job_runs",
            (("status", ASCENDING), ("created_at", DESCENDING)),
            "idx_job_runs_status_created",
        ),
    ]
    if ttl_seconds is not None:
        specs.append(
            _idx(
                "clickstream_events",
                (("timestamp", ASCENDING),),
                "ttl_clickstream_events_timestamp",
                expire_after_seconds=ttl_seconds,
            )
        )
    return specs


def build_plan(event_ttl_days: int = 0) -> dict[str, Any]:
    return {
        "collections": list(COLLECTION_NAMES),
        "event_ttl_days": event_ttl_days,
        "ttl_enabled": event_ttl_days > 0,
        "indexes": [spec.to_plan() for spec in build_index_specs(event_ttl_days)],
    }


def apply_indexes(database: Any, specs: list[IndexSpec]) -> list[dict[str, Any]]:
    applied = []
    for spec in specs:
        collection = database[spec.collection]
        index_name = collection.create_index(list(spec.keys), **spec.kwargs())
        applied.append({"collection": spec.collection, "index": index_name})
    return applied


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create behavior/recommendation MongoDB indexes.")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned indexes without writing.")
    parser.add_argument("--write", action="store_true", help="Create indexes in the configured MongoDB database.")
    parser.add_argument(
        "--event-ttl-days",
        type=int,
        default=None,
        help="Optional TTL for clickstream_events.timestamp. 0 disables TTL for demo.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run and args.write:
        print("ERROR: choose either --dry-run or --write, not both.", file=sys.stderr)
        return 2

    settings = get_settings()
    event_ttl_days = settings.event_ttl_days if args.event_ttl_days is None else args.event_ttl_days
    if event_ttl_days < 0:
        print("ERROR: --event-ttl-days must be >= 0.", file=sys.stderr)
        return 2

    specs = build_index_specs(event_ttl_days)
    payload = {"mode": "write" if args.write else "dry-run", **build_plan(event_ttl_days)}

    if not args.write:
        print(json.dumps(payload, indent=2))
        return 0

    from src.mongodb import get_database

    applied = apply_indexes(get_database(), specs)
    payload["applied"] = applied
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
