from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import create_behavior_indexes
from src import mongodb


def _spec_by_name(name: str):
    return next(spec for spec in create_behavior_indexes.build_index_specs() if spec.name == name)


def test_index_plan_includes_all_phase1_collections() -> None:
    plan = create_behavior_indexes.build_plan()
    assert "users" in plan["collections"]
    assert "recommendation_logs" in plan["collections"]
    assert "clickstream_events" in plan["collections"]
    assert "item_item_cf_edges" in plan["collections"]
    assert "seller_product_drafts" in plan["collections"]
    assert "web_enrichment_requests" in plan["collections"]
    assert "seller_indexing_previews" in plan["collections"]
    assert "evaluation_runs" in plan["collections"]
    assert "job_runs" in plan["collections"]


def test_clickstream_impression_idempotency_indexes_are_partial_and_unique() -> None:
    idempotency = _spec_by_name("uniq_clickstream_events_idempotency_key")
    impression = _spec_by_name("uniq_clickstream_events_impression_request_item")
    triplet = _spec_by_name("idx_clickstream_events_request_item_type")

    assert idempotency.unique is True
    assert idempotency.partial_filter_expression == {"idempotency_key": {"$exists": True}}

    assert impression.collection == "clickstream_events"
    assert impression.unique is True
    assert impression.keys == (("request_id", 1), ("item_id", 1))
    assert impression.partial_filter_expression == {"event_type": "impression"}

    assert triplet.keys == (("request_id", 1), ("item_id", 1), ("event_type", 1))
    assert triplet.unique is False


def test_ttl_is_disabled_by_default_and_optional_for_demo_safety() -> None:
    default_specs = create_behavior_indexes.build_index_specs()
    assert not any(spec.name.startswith("ttl_") for spec in default_specs)

    ttl_specs = create_behavior_indexes.build_index_specs(event_ttl_days=90)
    ttl = next(spec for spec in ttl_specs if spec.name == "ttl_clickstream_events_timestamp")
    assert ttl.expire_after_seconds == 90 * 24 * 60 * 60


def test_seller_preview_bundle_has_private_artifact_indexes() -> None:
    unique = _spec_by_name("uniq_seller_indexing_previews_preview_id")
    by_draft = _spec_by_name("idx_seller_indexing_previews_draft_created")

    assert unique.collection == "seller_indexing_previews"
    assert unique.unique is True
    assert by_draft.keys == (("draft_id", 1), ("created_at", -1))


def test_dry_run_main_prints_plan_without_requiring_mongodb(capsys) -> None:
    result = create_behavior_indexes.main(["--dry-run"])
    captured = capsys.readouterr()
    assert result == 0
    assert '"mode": "dry-run"' in captured.out
    assert "uniq_clickstream_events_impression_request_item" in captured.out


class FakeCollection:
    def __init__(self) -> None:
        self.calls = []

    def create_index(self, keys, **kwargs):
        self.calls.append((keys, kwargs))
        return kwargs["name"]


class FakeDatabase:
    def __init__(self) -> None:
        self.collections = {}

    def __getitem__(self, name: str):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


def test_apply_indexes_uses_create_index_without_drop_commands() -> None:
    db = FakeDatabase()
    specs = [
        _spec_by_name("uniq_users_user_id_hash"),
        _spec_by_name("uniq_clickstream_events_impression_request_item"),
    ]
    applied = create_behavior_indexes.apply_indexes(db, specs)
    assert applied == [
        {"collection": "users", "index": "uniq_users_user_id_hash"},
        {"collection": "clickstream_events", "index": "uniq_clickstream_events_impression_request_item"},
    ]
    assert db.collections["users"].calls[0][1]["unique"] is True
    assert "partialFilterExpression" in db.collections["clickstream_events"].calls[0][1]
    assert not hasattr(db.collections["users"], "drop_index")


def test_new_mongodb_getters_reuse_existing_get_database(monkeypatch) -> None:
    calls = []

    class GetterDatabase:
        def __getitem__(self, name: str):
            calls.append(name)
            return f"collection:{name}"

    monkeypatch.setattr(mongodb, "get_database", lambda: GetterDatabase())

    assert mongodb.get_users_collection() == "collection:users"
    assert mongodb.get_sessions_collection() == "collection:sessions"
    assert mongodb.get_recommendation_logs_collection() == "collection:recommendation_logs"
    assert mongodb.get_clickstream_events_collection() == "collection:clickstream_events"
    assert mongodb.get_user_item_signals_collection() == "collection:user_item_signals"
    assert mongodb.get_user_profiles_collection() == "collection:user_profiles"
    assert mongodb.get_item_hype_profiles_collection() == "collection:item_hype_profiles"
    assert mongodb.get_item_semantic_neighbors_collection() == "collection:item_semantic_neighbors"
    assert mongodb.get_item_item_cf_edges_collection() == "collection:item_item_cf_edges"
    assert mongodb.get_item_stats_collection() == "collection:item_stats"
    assert mongodb.get_query_embedding_cache_collection() == "collection:query_embedding_cache"
    assert mongodb.get_seller_product_drafts_collection() == "collection:seller_product_drafts"
    assert mongodb.get_web_enrichment_requests_collection() == "collection:web_enrichment_requests"
    assert mongodb.get_seller_indexing_previews_collection() == "collection:seller_indexing_previews"
    assert mongodb.get_synthetic_personas_collection() == "collection:synthetic_personas"
    assert mongodb.get_evaluation_runs_collection() == "collection:evaluation_runs"
    assert mongodb.get_job_runs_collection() == "collection:job_runs"
    assert calls == [
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
        "seller_indexing_previews",
        "synthetic_personas",
        "evaluation_runs",
        "job_runs",
    ]
