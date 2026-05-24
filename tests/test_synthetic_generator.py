from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from pymongo.errors import DuplicateKeyError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.synthetic_generator import (
    SyntheticCandidate,
    build_synthetic_behavior_plan,
    compute_persona_item_match,
    simulate_click_probability,
    write_synthetic_behavior_plan,
)
from src.recommendation.schemas import EMBEDDING_DIM


def _embedding(index: int) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    vector[index] = 1.0
    return vector


def _candidate(
    idx: int,
    *,
    category_id: str = "all_beauty",
    price_bucket: str = "100k_300k",
) -> SyntheticCandidate:
    return SyntheticCandidate(
        item_id=f"B{idx:04d}",
        title=f"Product {idx}",
        brand="Demo",
        category_id=category_id,
        price_bucket=price_bucket,
        price_vnd=200000,
        image_url=None,
        quality_score=0.7,
        item_semantic_embedding=_embedding(idx % EMBEDDING_DIM),
        top_aspects=["persona", "function"],
        num_hype_units=4,
    )


def _candidate_pool() -> list[SyntheticCandidate]:
    pool = []
    for idx in range(30):
        pool.append(_candidate(idx, category_id="all_beauty", price_bucket="100k_300k"))
    for idx in range(30, 60):
        pool.append(_candidate(idx, category_id="cell_phones_and_accessories", price_bucket="300k_500k"))
    for idx in range(60, 90):
        pool.append(_candidate(idx, category_id="all_electronics", price_bucket="500k_1m"))
    return pool


def test_compute_persona_item_match_prefers_matching_category_and_price() -> None:
    persona = {
        "preferred_categories": {"all_beauty": 1.0},
        "preferred_price_buckets": {"100k_300k": 1.0},
        "intent_embedding": _embedding(0),
    }
    good = _candidate(0, category_id="all_beauty", price_bucket="100k_300k")
    weak = _candidate(31, category_id="cell_phones_and_accessories", price_bucket="500k_1m")

    assert compute_persona_item_match(persona, good) > compute_persona_item_match(persona, weak)
    assert 0.0 <= compute_persona_item_match(persona, good) <= 1.0


def test_simulate_click_probability_decreases_with_rank() -> None:
    top = simulate_click_probability(0.8, 1)
    lower = simulate_click_probability(0.8, 10)
    assert top > lower
    assert 0.0 <= lower <= top <= 0.95


def test_build_synthetic_behavior_plan_has_logs_events_and_overlap() -> None:
    plan = build_synthetic_behavior_plan(
        candidates=_candidate_pool(),
        users=8,
        requests_per_user=2,
        items_per_request=8,
        seed=7,
    )
    summary = plan["summary"]

    assert summary["personas"] == 8
    assert summary["users"] == 8
    assert summary["requests"] == 16
    assert summary["recommendation_log_rows"] == 128
    assert summary["event_counts"]["impression"] == 128
    assert summary["event_counts"]["click"] > 0
    assert summary["positive_items_per_user"]["min"] >= 1
    assert summary["overlap_items_with_2plus_users"] > 0

    assert plan["requests"][0]["request_id"]
    assert plan["requests"][0]["items"][0]["item_id"]
    assert all(event["request_id"] and event["item_id"] for event in plan["events"])

    # Phase 4 must not materialize derived profile/signal/CF documents.
    assert "user_profiles" not in plan
    assert "user_item_signals" not in plan
    assert "item_item_cf_edges" not in plan


class FakeBulkResult:
    def __init__(self, upserted_count: int, matched_count: int = 0) -> None:
        self.upserted_count = upserted_count
        self.matched_count = matched_count
        self.modified_count = 0


class FakePersonaCollection:
    def __init__(self) -> None:
        self.operations = []

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        self.operations.extend(operations)
        return FakeBulkResult(upserted_count=len(operations))


class FakeRecommendationLogsCollection:
    def __init__(self) -> None:
        self.docs = {}

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        upserted = 0
        matched = 0
        for operation in operations:
            key = (operation._filter["request_id"], operation._filter["item_id"])
            if key in self.docs:
                matched += 1
                continue
            self.docs[key] = dict(operation._doc["$setOnInsert"])
            upserted += 1
        return FakeBulkResult(upserted_count=upserted, matched_count=matched)


class FakeInsertOneResult:
    def __init__(self, inserted_id: str) -> None:
        self.inserted_id = inserted_id


class FakeClickstreamEventsCollection:
    def __init__(self) -> None:
        self.docs = []

    def _matches(self, doc: dict, filter_doc: dict) -> bool:
        return all(doc.get(key) == value for key, value in filter_doc.items())

    def find_one(self, filter_doc: dict):
        for doc in self.docs:
            if self._matches(doc, filter_doc):
                return doc
        return None

    def insert_one(self, doc: dict):
        if self.find_one({"event_id": doc["event_id"]}):
            raise DuplicateKeyError("duplicate event_id")
        if doc.get("idempotency_key") and self.find_one({"idempotency_key": doc["idempotency_key"]}):
            raise DuplicateKeyError("duplicate idempotency_key")
        self.docs.append(dict(doc))
        return FakeInsertOneResult(str(len(self.docs)))


def test_write_synthetic_behavior_plan_writes_only_allowed_phase4_collections() -> None:
    plan = build_synthetic_behavior_plan(
        candidates=_candidate_pool(),
        users=3,
        requests_per_user=1,
        items_per_request=5,
        seed=11,
    )
    personas = FakePersonaCollection()
    logs = FakeRecommendationLogsCollection()
    events = FakeClickstreamEventsCollection()

    result = write_synthetic_behavior_plan(
        plan=plan,
        synthetic_personas_collection=personas,
        recommendation_logs_collection=logs,
        clickstream_events_collection=events,
    )

    assert result["personas_upserted"] == 8
    assert result["recommendation_logs_inserted"] == plan["summary"]["recommendation_log_rows"]
    assert result["clickstream_events_inserted"] == plan["summary"]["clickstream_events"]
    assert len(personas.operations) == 8
    assert len(logs.docs) == plan["summary"]["recommendation_log_rows"]
    assert len(events.docs) == plan["summary"]["clickstream_events"]
    assert all(doc["is_synthetic"] is True for doc in logs.docs.values())


def test_build_synthetic_behavior_plan_validates_inputs() -> None:
    with pytest.raises(ValueError, match="candidates must not be empty"):
        build_synthetic_behavior_plan(candidates=[])
    with pytest.raises(ValueError, match="users must be positive"):
        build_synthetic_behavior_plan(candidates=_candidate_pool(), users=0)
