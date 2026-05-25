from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation.similar_products import get_similar_products


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


def _item(item_id: str, *, category_id: str, price_bucket: str) -> dict:
    return {
        "_id": item_id,
        "title_en": f"Item {item_id}",
        "brand": "Brand",
        "category_id": category_id,
        "price_bucket": price_bucket,
        "price_vnd": 200000,
        "image_url": f"https://example.com/{item_id}.jpg",
        "quality_score": 0.7,
        "cold_start": {"is_cold_item": False, "interaction_count": 10},
    }


def _item_stats(item_id: str, quality: float) -> dict:
    return {"item_id": item_id, "quality_score": quality, "cold_start": {"is_cold_item": False, "interaction_count": 10}}


def _item_profile(item_id: str, index: int, category_id: str, price_bucket: str) -> dict:
    vector = [0.0] * 1024
    vector[index] = 1.0
    return {"item_id": item_id, "item_semantic_embedding": vector, "category_id": category_id, "price_bucket": price_bucket}


def test_similar_products_returns_semantic_and_cf_evidence_when_available() -> None:
    items = FakeCollection([
        _item("A", category_id="cell_phones_and_accessories", price_bucket="100k_300k"),
        _item("B", category_id="cell_phones_and_accessories", price_bucket="100k_300k"),
        _item("C", category_id="cell_phones_and_accessories", price_bucket="100k_300k"),
    ])
    item_stats = FakeCollection([_item_stats("A", 0.7), _item_stats("B", 0.8), _item_stats("C", 0.75)])
    item_profiles = FakeCollection([
        _item_profile("A", 0, "cell_phones_and_accessories", "100k_300k"),
        _item_profile("B", 0, "cell_phones_and_accessories", "100k_300k"),
        _item_profile("C", 1, "cell_phones_and_accessories", "100k_300k"),
    ])
    semantic = FakeCollection([
        {"item_id": "A", "neighbors": [{"neighbor_item_id": "B", "neighbor_score": 0.93, "matched_unit_ids": ["u1"], "matched_aspects": ["constraint"]}]}
    ])
    cf = FakeCollection([
        {"item_id": "A", "neighbor_item_id": "C", "cf_score": 0.81, "support": 3, "co_click_count": 2, "co_cart_count": 1}
    ])
    logs = FakeCollection([])

    payload = get_similar_products(
        "u_demo",
        "sess_001",
        "A",
        top_k=2,
        user_profiles_collection=FakeCollection([]),
        user_item_signals_collection=FakeCollection([]),
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_semantic_neighbors_collection=semantic,
        item_item_cf_edges_collection=cf,
        recommendation_logs_collection=logs,
    )

    assert [item["item_id"] for item in payload["items"]] == ["B", "C"]
    assert "Collaborative Filtering" in payload["items"][1]["reason_badges"]
    assert any("support=3" in explanation for explanation in payload["items"][1]["explanations"])
    assert payload["snapshot"]["attempted"] == 2


def test_similar_products_falls_back_when_semantic_neighbors_are_missing() -> None:
    items = FakeCollection([
        _item("A", category_id="cell_phones_and_accessories", price_bucket="100k_300k"),
        _item("B", category_id="cell_phones_and_accessories", price_bucket="100k_300k"),
        _item("C", category_id="all_beauty", price_bucket="100k_300k"),
    ])
    item_stats = FakeCollection([_item_stats("A", 0.7), _item_stats("B", 0.75), _item_stats("C", 0.6)])
    item_profiles = FakeCollection([
        _item_profile("A", 0, "cell_phones_and_accessories", "100k_300k"),
        _item_profile("B", 1, "cell_phones_and_accessories", "100k_300k"),
    ])

    payload = get_similar_products(
        "u_demo",
        "sess_002",
        "A",
        top_k=1,
        user_profiles_collection=FakeCollection([]),
        user_item_signals_collection=FakeCollection([]),
        items_collection=items,
        item_stats_collection=item_stats,
        item_hype_profiles_collection=item_profiles,
        item_semantic_neighbors_collection=FakeCollection([]),
        item_item_cf_edges_collection=FakeCollection([]),
        recommendation_logs_collection=FakeCollection([]),
    )

    assert payload["items"]
    assert payload["items"][0]["item_id"] == "B"
    assert payload["items"][0]["candidate_sources"] == ["metadata_fallback"]


def test_similar_products_does_not_restore_disliked_neighbor_from_fallback() -> None:
    profile = {
        "user_id_hash": "u_demo",
        "negative_preferences": {"item_ids": ["B"], "brands": [], "categories": [], "intents": []},
        "purchased_item_ids": [],
    }
    payload = get_similar_products(
        "u_demo",
        "sess_disliked_only",
        "A",
        top_k=1,
        user_profiles_collection=FakeCollection([profile]),
        user_item_signals_collection=FakeCollection([]),
        items_collection=FakeCollection(
            [
                _item("A", category_id="cell_phones_and_accessories", price_bucket="100k_300k"),
                _item("B", category_id="cell_phones_and_accessories", price_bucket="100k_300k"),
            ]
        ),
        item_stats_collection=FakeCollection([_item_stats("A", 0.7), _item_stats("B", 0.9)]),
        item_hype_profiles_collection=FakeCollection(
            [
                _item_profile("A", 0, "cell_phones_and_accessories", "100k_300k"),
                _item_profile("B", 0, "cell_phones_and_accessories", "100k_300k"),
            ]
        ),
        item_semantic_neighbors_collection=FakeCollection(
            [{"item_id": "A", "neighbors": [{"neighbor_item_id": "B", "neighbor_score": 0.99}]}]
        ),
        item_item_cf_edges_collection=FakeCollection([]),
        recommendation_logs_collection=FakeCollection([]),
    )

    assert payload["items"] == []
    assert payload["snapshot"]["attempted"] == 0
