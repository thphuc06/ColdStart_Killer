from __future__ import annotations

import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_user_profiles as build_user_profiles_script
from src.behavior.profile_builder import build_user_profiles
from src.recommendation.schemas import EMBEDDING_DIM


FIXED_NOW = "2026-01-02T00:00:00+00:00"


def _embedding(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]
        self.bulk_calls = []

    def find(self, filter_doc: dict, projection: dict | None = None):
        def matches(doc: dict) -> bool:
            for key, value in filter_doc.items():
                if isinstance(value, dict) and "$in" in value:
                    if doc.get(key) not in value["$in"]:
                        return False
                    continue
                if key == "$or":
                    return any(all(doc.get(k) == v for k, v in clause.items()) for clause in value)
                if doc.get(key) != value:
                    return False
            return True

        matched = []
        for doc in self.docs:
            if not filter_doc or matches(doc):
                if projection:
                    matched.append({key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc})
                else:
                    matched.append(dict(doc))
        return FakeCursor(matched)

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        self.bulk_calls.extend(operations)
        upserted = 0
        modified = 0
        for operation in operations:
            filter_doc = operation._filter
            set_doc = dict(operation._doc.get("$set", {}))
            set_on_insert = dict(operation._doc.get("$setOnInsert", {}))
            found = None
            for doc in self.docs:
                if all(doc.get(key) == value for key, value in filter_doc.items()):
                    found = doc
                    break
            if found is None:
                self.docs.append({**set_on_insert, **set_doc})
                upserted += 1
            else:
                before = dict(found)
                found.update(set_doc)
                if found != before:
                    modified += 1

        class Result:
            upserted_count = upserted
            modified_count = modified

        return Result()


def _signal(
    user_id_hash: str,
    item_id: str,
    *,
    positive_score: float,
    negative_score: float = 0.0,
    last_interaction_at: str = "2026-01-01T00:00:00+00:00",
    reason_intent: str | None = None,
    clicks: int = 1,
    views: int = 0,
    carts: int = 0,
    purchases: int = 0,
    hides: int = 0,
    dislikes: int = 0,
) -> dict:
    implicit = positive_score - negative_score
    return {
        "user_id_hash": user_id_hash,
        "item_id": item_id,
        "implicit_score": implicit,
        "positive_score": positive_score,
        "negative_score": negative_score,
        "preference": implicit > 0 and positive_score >= 1.0,
        "event_counts": {
            "impression": 1,
            "click": clicks,
            "view_detail": views,
            "add_to_cart": carts,
            "purchase": purchases,
            "wishlist": 0,
            "hide": hides,
            "dislike": dislikes,
        },
        "reason_scores": (
            [{"intent": reason_intent, "score": positive_score, "source": "search_click", "last_seen_at": last_interaction_at}]
            if reason_intent
            else []
        ),
        "first_interaction_at": last_interaction_at,
        "last_interaction_at": last_interaction_at,
        "updated_at": last_interaction_at,
    }


def _event(
    user_id_hash: str,
    item_id: str,
    *,
    event_type: str,
    request_id: str | None = None,
    timestamp: str = "2026-01-01T00:00:00+00:00",
) -> dict:
    return {
        "event_id": f"evt_{user_id_hash}_{item_id}_{event_type}_{timestamp[-8:-6]}",
        "request_id": request_id,
        "user_id_hash": user_id_hash,
        "item_id": item_id,
        "event_type": event_type,
        "surface": "search",
        "timestamp": timestamp,
        "created_at": timestamp,
    }


def _log(request_id: str, item_id: str, *, intent: str) -> dict:
    return {
        "request_id": request_id,
        "item_id": item_id,
        "attribution": {"matched_intents": [intent], "matched_facts": [], "matched_channels": ["vector"]},
        "scores": {"final_score": 0.8},
        "shown_at": "2026-01-01T00:00:00+00:00",
        "surface": "search",
    }


def _log_with_matched_unit(request_id: str, item_id: str, *, unit_id: str, query_type: str = "specific") -> dict:
    return {
        "request_id": request_id,
        "item_id": item_id,
        "query": {"raw_query": "mock query", "query_type": query_type, "query_embedding": _embedding(900)},
        "attribution": {
            "matched_unit_ids": [unit_id],
            "matched_intents": ["search intent"],
            "matched_facts": [],
            "matched_channels": ["vector"],
        },
        "scores": {"final_score": 0.9},
        "shown_at": "2026-01-01T00:00:00+00:00",
        "surface": "search",
    }


def _item_profile(item_id: str, index: int, *, category_id: str, price_bucket: str = "100k_300k") -> dict:
    return {
        "item_id": item_id,
        "item_semantic_embedding": _embedding(index),
        "top_aspects": ["persona", "function"],
        "num_hype_units": 4,
        "category_id": category_id,
        "price_bucket": price_bucket,
    }


def _item(item_id: str, *, brand: str, category_id: str, price_bucket: str = "100k_300k", price_vnd: int = 200000) -> dict:
    return {
        "_id": item_id,
        "brand": brand,
        "category_id": category_id,
        "price_bucket": price_bucket,
        "price_vnd": price_vnd,
    }


def _retrieval_unit(unit_id: str, item_id: str, embedding_index: int, unit_type: str = "hype_question") -> dict:
    return {
        "_id": unit_id,
        "item_id": item_id,
        "unit_type": unit_type,
        "embedding": _embedding(embedding_index),
    }


def test_build_user_profiles_derives_embeddings_affinities_and_recent_items() -> None:
    user_signals = FakeCollection(
        [
            _signal("u_demo", "B001", positive_score=3.0, reason_intent="oil control", clicks=2, carts=1, purchases=1),
            _signal("u_demo", "B002", positive_score=2.0, last_interaction_at="2026-01-01T01:00:00+00:00", reason_intent="lightweight"),
            _signal(
                "u_demo",
                "B003",
                positive_score=0.0,
                negative_score=3.0,
                last_interaction_at="2026-01-01T02:00:00+00:00",
                hides=1,
                dislikes=1,
            ),
        ]
    )
    events = FakeCollection(
        [
            _event("u_demo", "B001", event_type="click", request_id="req_001", timestamp="2026-01-01T00:10:00+00:00"),
            _event("u_demo", "B001", event_type="purchase", request_id="req_001", timestamp="2026-01-01T00:20:00+00:00"),
            _event("u_demo", "B002", event_type="click", request_id="req_002", timestamp="2026-01-01T01:10:00+00:00"),
            _event("u_demo", "B003", event_type="dislike", request_id="req_003", timestamp="2026-01-01T02:10:00+00:00"),
        ]
    )
    logs = FakeCollection([_log("req_001", "B001", intent="oil control"), _log("req_002", "B002", intent="lightweight")])
    item_profiles = FakeCollection(
        [
            _item_profile("B001", 0, category_id="all_beauty"),
            _item_profile("B002", 1, category_id="all_beauty"),
            _item_profile("B003", 2, category_id="all_beauty"),
        ]
    )
    items = FakeCollection(
        [
            _item("B001", brand="BrandA", category_id="all_beauty", price_vnd=220000),
            _item("B002", brand="BrandB", category_id="all_beauty", price_vnd=180000),
            _item("B003", brand="BrandC", category_id="all_beauty", price_vnd=250000),
        ]
    )

    result = build_user_profiles(
        user_item_signals_collection=user_signals,
        clickstream_events_collection=events,
        recommendation_logs_collection=logs,
        item_hype_profiles_collection=item_profiles,
        items_collection=items,
        updated_at=FIXED_NOW,
    )

    assert result["ok"] is True
    assert result["stats"]["profiles_built"] == 1
    profile = result["sample_profiles"][0]
    assert profile["user_id_hash"] == "u_demo"
    assert profile["profile_status"] == "warm"
    assert profile["profile_quality"]["num_positive_items"] == 2
    assert profile["category_affinity"]["all_beauty"] == 1.0
    assert profile["brand_affinity"]["BrandA"] == 1.0
    assert profile["price_affinity"]["median_purchased_price"] == 220000
    assert profile["recent_item_ids"][0] == "B003"
    assert "B001" in profile["purchased_item_ids"]
    assert "B003" in profile["negative_preferences"]["item_ids"]
    assert len(profile["interest_vectors"]) >= 1
    assert len(profile["short_term_embedding_preview"]) == 5
    assert len(profile["long_term_embedding_preview"]) == 5


def test_build_user_profiles_creates_multiple_interests_for_dissimilar_positive_items() -> None:
    user_signals = FakeCollection(
        [
            _signal("u_multi", "B001", positive_score=3.0, reason_intent="skincare"),
            _signal("u_multi", "B002", positive_score=3.0, last_interaction_at="2026-01-01T03:00:00+00:00", reason_intent="phone case"),
        ]
    )
    events = FakeCollection([
        _event("u_multi", "B001", event_type="click", request_id="req_001"),
        _event("u_multi", "B002", event_type="click", request_id="req_002", timestamp="2026-01-01T03:10:00+00:00"),
    ])
    logs = FakeCollection([_log("req_001", "B001", intent="skincare"), _log("req_002", "B002", intent="phone case")])
    item_profiles = FakeCollection([
        _item_profile("B001", 0, category_id="all_beauty"),
        _item_profile("B002", 800, category_id="cell_phones_and_accessories"),
    ])
    items = FakeCollection([
        _item("B001", brand="BrandA", category_id="all_beauty"),
        _item("B002", brand="BrandB", category_id="cell_phones_and_accessories"),
    ])

    result = build_user_profiles(
        user_item_signals_collection=user_signals,
        clickstream_events_collection=events,
        recommendation_logs_collection=logs,
        item_hype_profiles_collection=item_profiles,
        items_collection=items,
        updated_at=FIXED_NOW,
    )

    profile = result["sample_profiles"][0]
    assert len(profile["interest_vectors"]) == 2
    assert result["stats"]["calibration"]["users_with_1_interest"] == 0


def test_build_user_profiles_caps_interests_and_merges_when_limit_reached() -> None:
    signals = []
    events_docs = []
    logs_docs = []
    item_profiles_docs = []
    items_docs = []
    for index in range(9):
        item_id = f"B{index:03d}"
        signals.append(_signal("u_cap", item_id, positive_score=2.0, last_interaction_at=f"2026-01-01T0{index}:00:00+00:00", reason_intent=f"intent_{index}"))
        events_docs.append(_event("u_cap", item_id, event_type="click", request_id=f"req_{index}", timestamp=f"2026-01-01T0{index}:10:00+00:00"))
        logs_docs.append(_log(f"req_{index}", item_id, intent=f"intent_{index}"))
        item_profiles_docs.append(_item_profile(item_id, index, category_id=f"cat_{index}"))
        items_docs.append(_item(item_id, brand=f"Brand{index}", category_id=f"cat_{index}"))

    result = build_user_profiles(
        user_item_signals_collection=FakeCollection(signals),
        clickstream_events_collection=FakeCollection(events_docs),
        recommendation_logs_collection=FakeCollection(logs_docs),
        item_hype_profiles_collection=FakeCollection(item_profiles_docs),
        items_collection=FakeCollection(items_docs),
        updated_at=FIXED_NOW,
    )

    profile = result["sample_profiles"][0]
    assert len(profile["interest_vectors"]) == 8
    assert result["stats"]["calibration"]["users_with_8plus_interests"] == 1


def test_build_user_profiles_requires_repeated_negative_evidence_for_brand_and_category() -> None:
    result = build_user_profiles(
        user_item_signals_collection=FakeCollection(
            [
                _signal("u_neg", "B001", positive_score=0.0, negative_score=2.0, hides=1, dislikes=1),
                _signal(
                    "u_neg",
                    "B002",
                    positive_score=0.0,
                    negative_score=2.5,
                    hides=1,
                    dislikes=1,
                    last_interaction_at="2026-01-01T01:00:00+00:00",
                ),
            ]
        ),
        clickstream_events_collection=FakeCollection([
            _event("u_neg", "B001", event_type="dislike", timestamp="2026-01-01T00:10:00+00:00"),
            _event("u_neg", "B002", event_type="dislike", timestamp="2026-01-01T01:10:00+00:00"),
        ]),
        recommendation_logs_collection=FakeCollection([]),
        item_hype_profiles_collection=FakeCollection([
            _item_profile("B001", 0, category_id="all_beauty"),
            _item_profile("B002", 1, category_id="all_beauty"),
        ]),
        items_collection=FakeCollection([
            _item("B001", brand="BrandA", category_id="all_beauty"),
            _item("B002", brand="BrandA", category_id="all_beauty"),
        ]),
        updated_at=FIXED_NOW,
    )

    profile = result["sample_profiles"][0]
    assert profile["profile_status"] == "warming"
    assert "BrandA" in profile["negative_preferences"]["brands"]
    assert "all_beauty" in profile["negative_preferences"]["categories"]


def test_build_user_profiles_uses_surface_context_for_search_event_vector() -> None:
    result = build_user_profiles(
        user_item_signals_collection=FakeCollection(
            [
                _signal(
                    "u_surface",
                    "B010",
                    positive_score=2.0,
                    reason_intent="search intent",
                    last_interaction_at="2026-01-01T01:00:00+00:00",
                )
            ]
        ),
        clickstream_events_collection=FakeCollection(
            [
                {
                    **_event(
                        "u_surface",
                        "B010",
                        event_type="click",
                        request_id="req_surface",
                        timestamp="2026-01-01T01:10:00+00:00",
                    ),
                }
            ]
        ),
        recommendation_logs_collection=FakeCollection(
            [
                _log_with_matched_unit(
                    "req_surface",
                    "B010",
                    unit_id="ru_1",
                    query_type="specific",
                )
            ]
        ),
        item_hype_profiles_collection=FakeCollection([_item_profile("B010", 0, category_id="all_beauty")]),
        items_collection=FakeCollection([_item("B010", brand="BrandX", category_id="all_beauty")]),
        retrieval_units_collection=FakeCollection([_retrieval_unit("ru_1", "B010", 600)]),
        updated_at=FIXED_NOW,
    )

    profile = result["sample_profiles"][0]
    interest_embedding = profile["interest_vectors"][0]["embedding"]
    assert interest_embedding[600] > interest_embedding[0]
    assert interest_embedding[900] > 0.0


def test_phase6_script_dry_run_does_not_write_profiles(monkeypatch, capsys) -> None:
    user_signals = FakeCollection([_signal("u_script", "B001", positive_score=3.0, reason_intent="skincare")])
    events = FakeCollection([_event("u_script", "B001", event_type="click", request_id="req_001")])
    logs = FakeCollection([_log("req_001", "B001", intent="skincare")])
    item_profiles = FakeCollection([_item_profile("B001", 0, category_id="all_beauty")])
    items = FakeCollection([_item("B001", brand="BrandA", category_id="all_beauty")])
    retrieval_units = FakeCollection([])
    user_profiles = FakeCollection([])

    monkeypatch.setattr(build_user_profiles_script, "get_user_item_signals_collection", lambda: user_signals)
    monkeypatch.setattr(build_user_profiles_script, "get_clickstream_events_collection", lambda: events)
    monkeypatch.setattr(build_user_profiles_script, "get_recommendation_logs_collection", lambda: logs)
    monkeypatch.setattr(build_user_profiles_script, "get_item_hype_profiles_collection", lambda: item_profiles)
    monkeypatch.setattr(build_user_profiles_script, "get_items_collection", lambda: items)
    monkeypatch.setattr(build_user_profiles_script, "get_retrieval_units_collection", lambda: retrieval_units)
    monkeypatch.setattr(build_user_profiles_script, "get_user_profiles_collection", lambda: user_profiles)

    exit_code = build_user_profiles_script.main(["--dry-run", "--limit-users", "1"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"mode": "dry-run"' in captured.out
    assert user_profiles.docs == []
