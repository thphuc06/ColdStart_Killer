from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation.search_personalizer import personalized_search


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
                self.docs.append(dict(operation._doc.get("$setOnInsert", {})))
                upserted += 1
        return FakeBulkResult(upserted, matched)


def _item(item_id: str, *, category_id: str, brand: str) -> dict:
    return {
        "_id": item_id,
        "title_en": f"Item {item_id}",
        "brand": brand,
        "category_id": category_id,
        "price_bucket": "100k_300k",
        "price_vnd": 200000,
        "image_url": f"https://example.com/{item_id}.jpg",
        "quality_score": 0.7,
        "cold_start": {"is_cold_item": False, "interaction_count": 10},
    }


def _item_stats(item_id: str, quality: float) -> dict:
    return {"item_id": item_id, "quality_score": quality, "cold_start": {"is_cold_item": False, "interaction_count": 10}}


def _item_profile(item_id: str, index: int, category_id: str) -> dict:
    vector = [0.0] * 1024
    vector[index] = 1.0
    return {"item_id": item_id, "item_semantic_embedding": vector, "category_id": category_id, "price_bucket": "100k_300k"}


def _profile() -> dict:
    vector = [0.0] * 1024
    vector[1] = 1.0
    return {
        "user_id_hash": "u_skincare",
        "profile_status": "warm",
        "profile_quality": {"confidence": 0.9},
        "category_affinity": {"all_beauty": 1.0, "cell_phones_and_accessories": 0.1},
        "brand_affinity": {"BeautyBrand": 1.0},
        "price_affinity": {"preferred_buckets": {"100k_300k": 1.0}},
        "interest_vectors": [{"interest_id": "int_beauty", "label": "skincare", "embedding": vector, "weight": 5.0}],
        "negative_preferences": {"item_ids": [], "brands": [], "categories": [], "intents": []},
        "recent_item_ids": [],
        "purchased_item_ids": [],
    }


def test_personalized_search_keeps_specific_query_dominant_over_profile_bias() -> None:
    items = FakeCollection([
        _item("PHONE_CASE", category_id="cell_phones_and_accessories", brand="PhoneBrand"),
        _item("SKINCARE", category_id="all_beauty", brand="BeautyBrand"),
    ])
    item_stats = FakeCollection([_item_stats("PHONE_CASE", 0.7), _item_stats("SKINCARE", 0.7)])
    item_profiles = FakeCollection([
        _item_profile("PHONE_CASE", 0, "cell_phones_and_accessories"),
        _item_profile("SKINCARE", 1, "all_beauty"),
    ])
    logs = FakeCollection([])

    def fake_process_query(raw_query: str) -> dict:
        return {
            "original_query": raw_query,
            "language_detected": "vi",
            "english_query": raw_query,
            "hype_search_query_en": f"user looking for {raw_query} for everyday use",
            "bm25_search_query_en": raw_query,
            "hard_filters": {},
            "query_embedding": [0.0] * 1024,
        }

    def fake_run_search(_fixture: dict, top_k: int = 10):
        assert top_k >= 2
        return [
            {
                "item_id": "PHONE_CASE",
                "title": "Phone Case",
                "score": 0.95,
                "matched_intent": "iphone case",
                "matched_fact": "shockproof case",
                "is_cold_item": False,
                "interaction_count": 10,
                "debug": {"brand": "PhoneBrand", "category_id": "cell_phones_and_accessories", "price_bucket": "100k_300k", "price_vnd": 200000, "matched_channels": ["vector", "bm25"]},
            },
            {
                "item_id": "SKINCARE",
                "title": "Skincare",
                "score": 0.20,
                "matched_intent": "moisturizer",
                "matched_fact": "gentle skincare",
                "is_cold_item": False,
                "interaction_count": 10,
                "debug": {"brand": "BeautyBrand", "category_id": "all_beauty", "price_bucket": "100k_300k", "price_vnd": 200000, "matched_channels": ["vector"]},
            },
        ]

    payload = personalized_search(
        "u_skincare",
        "sess_001",
        "samsung galaxy s22 clear case",
        top_k=2,
        process_query_fn=fake_process_query,
        run_search_fn=fake_run_search,
        user_profiles_collection=FakeCollection([_profile()]),
        user_item_signals_collection=FakeCollection([]),
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_item_cf_edges_collection=FakeCollection([]),
        recommendation_logs_collection=logs,
    )

    assert [item["item_id"] for item in payload["items"]] == ["PHONE_CASE", "SKINCARE"]
    assert payload["query"]["query_type"] == "specific"
    assert payload["query"]["language_detected"] == "vi"
    assert payload["query"]["hype_search_query_en"].startswith("user looking for")
    assert payload["query"]["hard_filters"] == {}
    assert payload["snapshot"]["attempted"] == 2
    assert all(item.get("score_breakdown") for item in payload["items"])


def test_personalized_search_keeps_explanations_and_badges() -> None:
    items = FakeCollection([_item("A", category_id="all_beauty", brand="BeautyBrand")])
    item_stats = FakeCollection([_item_stats("A", 0.7)])
    item_profiles = FakeCollection([_item_profile("A", 1, "all_beauty")])

    payload = personalized_search(
        "u_demo",
        "sess_002",
        "gift ideas",
        top_k=1,
        process_query_fn=lambda raw_query: {
            "original_query": raw_query,
            "english_query": raw_query,
            "bm25_search_query_en": raw_query,
            "hard_filters": {},
            "query_embedding": [0.0] * 1024,
        },
        run_search_fn=lambda _fixture, top_k=10: [
            {
                "item_id": "A",
                "title": "Gift Item",
                "score": 0.4,
                "matched_intent": "gift idea",
                "matched_fact": "giftable beauty set",
                "is_cold_item": False,
                "interaction_count": 10,
                "debug": {"brand": "BeautyBrand", "category_id": "all_beauty", "price_bucket": "100k_300k", "price_vnd": 200000, "matched_channels": ["vector", "bm25"]},
            }
        ],
        user_profiles_collection=FakeCollection([]),
        user_item_signals_collection=FakeCollection([]),
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_item_cf_edges_collection=FakeCollection([]),
        recommendation_logs_collection=FakeCollection([]),
    )

    item = payload["items"][0]
    assert item["reason_badges"]
    assert item["explanations"]
    assert item["matched_fact"] == "giftable beauty set"


def test_personalized_search_excludes_exact_hidden_query_result_before_logging() -> None:
    profile = _profile()
    profile["negative_preferences"]["item_ids"] = ["A"]
    payload = personalized_search(
        "u_skincare",
        "sess_hidden",
        "gentle cleanser",
        top_k=1,
        process_query_fn=lambda raw_query: {
            "original_query": raw_query,
            "english_query": raw_query,
            "bm25_search_query_en": raw_query,
            "hard_filters": {},
            "query_embedding": [0.0] * 1024,
        },
        run_search_fn=lambda _fixture, top_k=10: [
            {
                "item_id": "A",
                "title": "Hidden Item",
                "score": 0.9,
                "debug": {"brand": "BeautyBrand", "category_id": "all_beauty", "price_bucket": "100k_300k"},
            }
        ],
        user_profiles_collection=FakeCollection([profile]),
        user_item_signals_collection=FakeCollection([]),
        items_collection=FakeCollection([_item("A", category_id="all_beauty", brand="BeautyBrand")]),
        item_stats_collection=FakeCollection([_item_stats("A", 0.7)]),
        item_hype_profiles_collection=FakeCollection([_item_profile("A", 1, "all_beauty")]),
        item_item_cf_edges_collection=FakeCollection([]),
        recommendation_logs_collection=FakeCollection([]),
    )

    assert payload["items"] == []
    assert payload["snapshot"]["attempted"] == 0


def test_broad_search_cf_uses_only_seed_eligible_signals() -> None:
    items = FakeCollection(
        [
            _item("FROM_CLICK", category_id="all_beauty", brand="BeautyBrand"),
            _item("FROM_CART", category_id="all_beauty", brand="BeautyBrand"),
        ]
    )
    payload = personalized_search(
        "u_skincare",
        "sess_seed",
        "gift ideas",
        top_k=2,
        process_query_fn=lambda raw_query: {
            "original_query": raw_query,
            "english_query": raw_query,
            "bm25_search_query_en": raw_query,
            "hard_filters": {},
            "query_embedding": [0.0] * 1024,
        },
        run_search_fn=lambda _fixture, top_k=10: [
            {"item_id": "FROM_CLICK", "title": "Click Neighbor", "score": 0.3, "debug": {"brand": "BeautyBrand", "category_id": "all_beauty", "price_bucket": "100k_300k"}},
            {"item_id": "FROM_CART", "title": "Cart Neighbor", "score": 0.3, "debug": {"brand": "BeautyBrand", "category_id": "all_beauty", "price_bucket": "100k_300k"}},
        ],
        user_profiles_collection=FakeCollection([_profile()]),
        user_item_signals_collection=FakeCollection(
            [
                {"user_id_hash": "u_skincare", "item_id": "CLICK_ONLY", "implicit_score": 0.35, "positive_score": 0.35, "seed_eligible": False},
                {"user_id_hash": "u_skincare", "item_id": "CART_SEED", "implicit_score": 4.0, "positive_score": 4.0, "seed_eligible": True},
            ]
        ),
        items_collection=items,
        item_stats_collection=FakeCollection([_item_stats("FROM_CLICK", 0.7), _item_stats("FROM_CART", 0.7)]),
        item_hype_profiles_collection=FakeCollection([_item_profile("FROM_CLICK", 1, "all_beauty"), _item_profile("FROM_CART", 1, "all_beauty")]),
        item_item_cf_edges_collection=FakeCollection(
            [
                {"item_id": "CLICK_ONLY", "neighbor_item_id": "FROM_CLICK", "cf_score": 0.9, "support": 2},
                {"item_id": "CART_SEED", "neighbor_item_id": "FROM_CART", "cf_score": 0.9, "support": 2},
            ]
        ),
        recommendation_logs_collection=FakeCollection([]),
    )

    cards = {card["item_id"]: card for card in payload["items"]}
    assert "Collaborative Filtering" not in cards["FROM_CLICK"]["reason_badges"]
    assert "Collaborative Filtering" in cards["FROM_CART"]["reason_badges"]
