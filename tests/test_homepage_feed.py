from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation.homepage_feed import get_homepage_feed


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    def __iter__(self):
        return iter(self.docs)


class FakeBulkResult:
    def __init__(self, upserted: int, matched: int) -> None:
        self.upserted_count = upserted
        self.matched_count = matched
        self.modified_count = 0


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    def _matches(self, doc: dict, filter_doc: dict) -> bool:
        for key, value in filter_doc.items():
            if isinstance(value, dict) and "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
                continue
            if doc.get(key) != value:
                return False
        return True

    def find(self, filter_doc: dict, projection: dict | None = None):
        matched = []
        for doc in self.docs:
            if not filter_doc or self._matches(doc, filter_doc):
                if projection:
                    matched.append({key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc})
                else:
                    matched.append(dict(doc))
        return FakeCursor(matched)

    def find_one(self, filter_doc: dict, projection: dict | None = None):
        for doc in self.docs:
            if self._matches(doc, filter_doc):
                if projection:
                    return {key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc}
                return dict(doc)
        return None

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        upserted = 0
        matched = 0
        for operation in operations:
            key = (operation._filter.get("request_id"), operation._filter.get("item_id"))
            exists = False
            for doc in self.docs:
                if doc.get("request_id") == key[0] and doc.get("item_id") == key[1]:
                    exists = True
                    break
            if exists:
                matched += 1
            else:
                payload = dict(operation._doc.get("$setOnInsert", {}))
                self.docs.append(payload)
                upserted += 1
        return FakeBulkResult(upserted, matched)


def _embedding(index: int) -> list[float]:
    vector = [0.0] * 1024
    vector[index] = 1.0
    return vector


def _item(item_id: str, *, category_id: str, brand: str, price_bucket: str, cold: bool, quality: float) -> dict:
    return {
        "_id": item_id,
        "title_en": f"Item {item_id}",
        "brand": brand,
        "category_id": category_id,
        "price_bucket": price_bucket,
        "price_vnd": 200000,
        "image_url": f"https://example.com/{item_id}.jpg",
        "quality_score": quality,
        "cold_start": {"is_cold_item": cold, "interaction_count": 0 if cold else 25},
    }


def _item_stats(item_id: str, *, cold: bool, quality: float, interaction_count: int) -> dict:
    return {
        "item_id": item_id,
        "quality_score": quality,
        "cold_start": {"is_cold_item": cold, "interaction_count": interaction_count},
    }


def _item_profile(item_id: str, embedding_index: int, category_id: str, price_bucket: str) -> dict:
    return {
        "item_id": item_id,
        "item_semantic_embedding": _embedding(embedding_index),
        "category_id": category_id,
        "price_bucket": price_bucket,
        "top_aspects": ["function"],
    }


def _profile(user_id_hash: str, *, embedding_index: int, status: str = "warm") -> dict:
    return {
        "user_id_hash": user_id_hash,
        "profile_status": status,
        "profile_quality": {"confidence": 0.8},
        "category_affinity": {"cell_phones_and_accessories": 1.0, "all_beauty": 0.2},
        "brand_affinity": {"PhoneBrand": 1.0},
        "price_affinity": {"preferred_buckets": {"100k_300k": 1.0}},
        "interest_vectors": [
            {
                "interest_id": "int_phone",
                "label": "phone accessories",
                "embedding": _embedding(embedding_index),
                "weight": 5.0,
            }
        ],
        "negative_preferences": {"item_ids": [], "brands": [], "categories": [], "intents": []},
        "recent_item_ids": ["PHONE_SEED"],
        "purchased_item_ids": [],
    }


def _signal(
    item_id: str,
    *,
    positive_score: float = 4.6,
    implicit_score: float | None = None,
    seed_eligible: bool = True,
    engaged: float = 0.25,
    conversion: float = 4.0,
    exploratory: float = 0.35,
    last_interaction_at: str = "2026-01-01T00:05:00+00:00",
) -> dict:
    return {
        "user_id_hash": "u_phone",
        "item_id": item_id,
        "implicit_score": positive_score if implicit_score is None else implicit_score,
        "positive_score": positive_score,
        "negative_score": 0.0,
        "seed_eligible": seed_eligible,
        "intent_tier": "conversion" if conversion > 0 else ("engaged" if engaged > 0 else "exploratory"),
        "contributions": {
            "exploratory": exploratory,
            "engaged": engaged,
            "conversion": conversion,
        },
        "event_counts": {"click": 1, "view_detail": 0, "add_to_cart": 1, "purchase": 0, "wishlist": 0},
        "last_interaction_at": last_interaction_at,
        "preference": True,
    }


def test_homepage_feed_never_empty_logs_snapshot_and_keeps_cold_item_exposure() -> None:
    items = FakeCollection(
        [
            _item("PHONE_SEED", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.7),
            _item("PHONE_MATCH", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.8),
            _item("PHONE_CF", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.75),
            _item("COLD_NEW", category_id="cell_phones_and_accessories", brand="NewBrand", price_bucket="100k_300k", cold=True, quality=0.6),
        ]
    )
    item_stats = FakeCollection(
        [
            _item_stats("PHONE_SEED", cold=False, quality=0.7, interaction_count=25),
            _item_stats("PHONE_MATCH", cold=False, quality=0.8, interaction_count=30),
            _item_stats("PHONE_CF", cold=False, quality=0.75, interaction_count=22),
            _item_stats("COLD_NEW", cold=True, quality=0.6, interaction_count=0),
        ]
    )
    item_profiles = FakeCollection(
        [
            _item_profile("PHONE_SEED", 0, "cell_phones_and_accessories", "100k_300k"),
            _item_profile("PHONE_MATCH", 0, "cell_phones_and_accessories", "100k_300k"),
            _item_profile("PHONE_CF", 1, "cell_phones_and_accessories", "100k_300k"),
            _item_profile("COLD_NEW", 2, "cell_phones_and_accessories", "100k_300k"),
        ]
    )
    profiles = FakeCollection([_profile("u_phone", embedding_index=0)])
    signals = FakeCollection([_signal("PHONE_SEED")])
    semantic = FakeCollection([
        {
            "item_id": "PHONE_SEED",
            "neighbors": [{"neighbor_item_id": "PHONE_MATCH", "neighbor_score": 0.95, "matched_unit_ids": ["u1"], "matched_aspects": ["function"]}],
        }
    ])
    cf = FakeCollection([
        {"item_id": "PHONE_SEED", "neighbor_item_id": "PHONE_CF", "cf_score": 0.82, "support": 4, "co_click_count": 3, "co_cart_count": 1}
    ])
    logs = FakeCollection([])

    payload = get_homepage_feed(
        "u_phone",
        "sess_001",
        top_k=3,
        user_profiles_collection=profiles,
        user_item_signals_collection=signals,
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_semantic_neighbors_collection=semantic,
        item_item_cf_edges_collection=cf,
        recommendation_logs_collection=logs,
    )

    assert payload["items"]
    assert len(payload["items"]) == 3
    assert any(item["is_cold_item"] for item in payload["items"])
    assert all(item.get("score_breakdown") for item in payload["items"])
    assert all(item.get("reason_badges") for item in payload["items"])
    assert payload["snapshot"]["attempted"] == 3
    assert len(logs.docs) == 3


def test_homepage_feed_changes_with_different_profiles() -> None:
    items = FakeCollection(
        [
            _item("PHONE_ITEM", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.8),
            _item("BEAUTY_ITEM", category_id="all_beauty", brand="BeautyBrand", price_bucket="100k_300k", cold=False, quality=0.8),
        ]
    )
    item_stats = FakeCollection([
        _item_stats("PHONE_ITEM", cold=False, quality=0.8, interaction_count=20),
        _item_stats("BEAUTY_ITEM", cold=False, quality=0.8, interaction_count=20),
    ])
    item_profiles = FakeCollection([
        _item_profile("PHONE_ITEM", 0, "cell_phones_and_accessories", "100k_300k"),
        _item_profile("BEAUTY_ITEM", 1, "all_beauty", "100k_300k"),
    ])
    profiles = FakeCollection([
        _profile("u_phone", embedding_index=0),
        _profile("u_beauty", embedding_index=1),
    ])
    signals = FakeCollection([])
    empty = FakeCollection([])

    phone_payload = get_homepage_feed(
        "u_phone",
        "sess_phone",
        top_k=1,
        user_profiles_collection=profiles,
        user_item_signals_collection=signals,
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_semantic_neighbors_collection=empty,
        item_item_cf_edges_collection=empty,
        recommendation_logs_collection=FakeCollection([]),
    )
    beauty_payload = get_homepage_feed(
        "u_beauty",
        "sess_beauty",
        top_k=1,
        user_profiles_collection=profiles,
        user_item_signals_collection=signals,
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_semantic_neighbors_collection=empty,
        item_item_cf_edges_collection=empty,
        recommendation_logs_collection=FakeCollection([]),
    )

    assert phone_payload["items"][0]["item_id"] == "PHONE_ITEM"
    assert beauty_payload["items"][0]["item_id"] == "BEAUTY_ITEM"


def test_homepage_reason_uses_matching_category_interest_instead_of_stronger_unrelated_interest() -> None:
    beauty_item_profile = _item_profile("BEAUTY_ITEM", 0, "all_beauty", "100k_300k")
    beauty_item_profile["item_semantic_embedding"] = [0.6, 0.8] + ([0.0] * 1022)
    profile = _profile("u_mixed", embedding_index=0)
    profile["interest_vectors"] = [
        {
            "interest_id": "int_phone",
            "label": "phone screen specifications",
            "embedding": _embedding(0),
            "weight": 5.0,
            "categories": ["cell_phones_and_accessories"],
        },
        {
            "interest_id": "int_beauty",
            "label": "gentle skincare",
            "embedding": _embedding(1),
            "weight": 1.0,
            "categories": ["all_beauty"],
        },
    ]
    empty = FakeCollection([])

    payload = get_homepage_feed(
        "u_mixed",
        "sess_mixed",
        top_k=1,
        user_profiles_collection=FakeCollection([profile]),
        user_item_signals_collection=empty,
        items_collection=FakeCollection(
            [
                _item(
                    "BEAUTY_ITEM",
                    category_id="all_beauty",
                    brand="BeautyBrand",
                    price_bucket="100k_300k",
                    cold=True,
                    quality=0.8,
                )
            ]
        ),
        item_stats_collection=FakeCollection(
            [_item_stats("BEAUTY_ITEM", cold=True, quality=0.8, interaction_count=0)]
        ),
        item_hype_profiles_collection=FakeCollection([beauty_item_profile]),
        item_semantic_neighbors_collection=empty,
        item_item_cf_edges_collection=empty,
        recommendation_logs_collection=FakeCollection([]),
    )

    card = payload["items"][0]
    assert card["debug"]["profile_interest_label"] == "gentle skincare"
    assert "Boosted because it matches your gentle skincare interest." in card["explanations"]
    assert all("phone screen specifications" not in explanation for explanation in card["explanations"])


def test_homepage_does_not_apply_cross_category_profile_reason_without_matching_interest() -> None:
    profile = _profile("u_phone_only", embedding_index=0)
    profile["interest_vectors"] = [
        {
            "interest_id": "int_phone",
            "label": "phone accessories",
            "embedding": _embedding(0),
            "weight": 5.0,
            "categories": ["cell_phones_and_accessories"],
        }
    ]
    fashion_profile = _item_profile("FASHION_ITEM", 0, "amazon_fashion", "100k_300k")
    empty = FakeCollection([])

    payload = get_homepage_feed(
        "u_phone_only",
        "sess_cross_category",
        top_k=1,
        user_profiles_collection=FakeCollection([profile]),
        user_item_signals_collection=empty,
        items_collection=FakeCollection(
            [_item("FASHION_ITEM", category_id="amazon_fashion", brand="FashionBrand", price_bucket="100k_300k", cold=True, quality=0.8)]
        ),
        item_stats_collection=FakeCollection([_item_stats("FASHION_ITEM", cold=True, quality=0.8, interaction_count=0)]),
        item_hype_profiles_collection=FakeCollection([fashion_profile]),
        item_semantic_neighbors_collection=empty,
        item_item_cf_edges_collection=empty,
        recommendation_logs_collection=FakeCollection([]),
    )

    card = payload["items"][0]
    assert card["contributions"]["profile"] == 0.0
    assert "Profile" not in card["reason_badges"]
    assert card["debug"]["profile_interest_label"] == ""
    assert all("phone accessories" not in explanation for explanation in card["explanations"])


def test_homepage_seed_selection_ignores_recent_items_without_seed_eligible_signal() -> None:
    items = FakeCollection(
        [
            _item("RECENT_ONLY", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.7),
            _item("STRONG_SEED", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.8),
            _item("MATCH_FROM_STRONG", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.85),
            _item("CF_FROM_STRONG", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.82),
        ]
    )
    item_stats = FakeCollection(
        [
            _item_stats("RECENT_ONLY", cold=False, quality=0.7, interaction_count=20),
            _item_stats("STRONG_SEED", cold=False, quality=0.8, interaction_count=25),
            _item_stats("MATCH_FROM_STRONG", cold=False, quality=0.85, interaction_count=30),
            _item_stats("CF_FROM_STRONG", cold=False, quality=0.82, interaction_count=24),
        ]
    )
    item_profiles = FakeCollection(
        [
            _item_profile("RECENT_ONLY", 0, "cell_phones_and_accessories", "100k_300k"),
            _item_profile("STRONG_SEED", 0, "cell_phones_and_accessories", "100k_300k"),
            _item_profile("MATCH_FROM_STRONG", 0, "cell_phones_and_accessories", "100k_300k"),
            _item_profile("CF_FROM_STRONG", 1, "cell_phones_and_accessories", "100k_300k"),
        ]
    )
    profile = _profile("u_phone", embedding_index=0)
    profile["recent_item_ids"] = ["RECENT_ONLY"]
    signals = FakeCollection(
        [
            {
                **_signal(
                    "RECENT_ONLY",
                    positive_score=0.35,
                    implicit_score=0.35,
                    seed_eligible=False,
                    engaged=0.0,
                    conversion=0.0,
                    exploratory=0.35,
                    last_interaction_at="2026-01-01T00:06:00+00:00",
                ),
                "preference": False,
            },
            _signal("STRONG_SEED", last_interaction_at="2026-01-01T00:05:00+00:00"),
        ]
    )
    semantic = FakeCollection(
        [
            {"item_id": "RECENT_ONLY", "neighbors": [{"neighbor_item_id": "RECENT_ONLY", "neighbor_score": 0.99}]},
            {"item_id": "STRONG_SEED", "neighbors": [{"neighbor_item_id": "MATCH_FROM_STRONG", "neighbor_score": 0.95}]},
        ]
    )
    cf = FakeCollection(
        [
            {"item_id": "RECENT_ONLY", "neighbor_item_id": "RECENT_ONLY", "cf_score": 0.95, "support": 3, "co_click_count": 3, "co_cart_count": 1},
            {"item_id": "STRONG_SEED", "neighbor_item_id": "CF_FROM_STRONG", "cf_score": 0.9, "support": 4, "co_click_count": 3, "co_cart_count": 2},
        ]
    )

    payload = get_homepage_feed(
        "u_phone",
        "sess_seed_guard",
        top_k=4,
        user_profiles_collection=FakeCollection([profile]),
        user_item_signals_collection=signals,
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_semantic_neighbors_collection=semantic,
        item_item_cf_edges_collection=cf,
        recommendation_logs_collection=FakeCollection([]),
    )

    item_ids = {item["item_id"] for item in payload["items"]}
    assert "MATCH_FROM_STRONG" in item_ids
    assert "CF_FROM_STRONG" in item_ids


def test_homepage_does_not_restore_only_hidden_candidate_when_pool_is_exhausted() -> None:
    profile = _profile("u_phone", embedding_index=0)
    profile["negative_preferences"]["item_ids"] = ["BLOCKED"]
    payload = get_homepage_feed(
        "u_phone",
        "sess_hidden_only",
        top_k=1,
        user_profiles_collection=FakeCollection([profile]),
        user_item_signals_collection=FakeCollection([]),
        items_collection=FakeCollection(
            [_item("BLOCKED", category_id="cell_phones_and_accessories", brand="PhoneBrand", price_bucket="100k_300k", cold=False, quality=0.9)]
        ),
        item_stats_collection=FakeCollection([_item_stats("BLOCKED", cold=False, quality=0.9, interaction_count=20)]),
        item_hype_profiles_collection=FakeCollection([_item_profile("BLOCKED", 0, "cell_phones_and_accessories", "100k_300k")]),
        item_semantic_neighbors_collection=FakeCollection([]),
        item_item_cf_edges_collection=FakeCollection([]),
        recommendation_logs_collection=FakeCollection([]),
    )

    assert payload["items"] == []
    assert payload["snapshot"]["attempted"] == 0
