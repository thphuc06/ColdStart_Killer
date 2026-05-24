from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pymongo.errors import DuplicateKeyError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.event_logger import (
    impression_idempotency_key,
    log_clickstream_event,
    log_recommendation_snapshot,
)


class FakeBulkResult:
    def __init__(self, upserted_count: int, matched_count: int) -> None:
        self.upserted_count = upserted_count
        self.matched_count = matched_count
        self.modified_count = 0


class FakeRecommendationLogsCollection:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict] = {}
        self.operations = []

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        self.operations.extend(operations)
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
        self.docs: list[dict] = []

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

        idempotency_key = doc.get("idempotency_key")
        if idempotency_key and self.find_one({"idempotency_key": idempotency_key}):
            raise DuplicateKeyError("duplicate idempotency_key")

        if doc.get("event_type") == "impression" and doc.get("request_id"):
            existing_impression = self.find_one(
                {
                    "request_id": doc["request_id"],
                    "item_id": doc["item_id"],
                    "event_type": "impression",
                }
            )
            if existing_impression:
                raise DuplicateKeyError("duplicate impression request/item")

        self.docs.append(dict(doc))
        return FakeInsertOneResult(inserted_id=f"inserted_{len(self.docs)}")


def test_log_recommendation_snapshot_upserts_one_row_per_item_and_stores_versions() -> None:
    collection = FakeRecommendationLogsCollection()
    items = [
        {
            "item_id": "B001",
            "title": "Demo",
            "score": 0.75,
            "matched_intent": "gift for oily skin",
            "matched_fact": "lightweight moisturizer",
            "debug": {"matched_channels": ["vector", "bm25"]},
        },
        {"item_id": "B002", "rank_position": 4, "final_score": 0.5},
    ]

    first = log_recommendation_snapshot(
        request_id="req_001",
        user_id_hash="u_demo",
        session_id="sess_001",
        surface="search",
        items=items,
        algorithm_version="algo_test",
        ranking_version="rank_test",
        query={"raw_query": "kem duong", "english_query": "moisturizer", "query_type": "normal"},
        recommendation_logs_collection=collection,
    )
    second = log_recommendation_snapshot(
        request_id="req_001",
        user_id_hash="u_demo",
        session_id="sess_001",
        surface="search",
        items=items,
        algorithm_version="algo_test",
        ranking_version="rank_test",
        recommendation_logs_collection=collection,
    )

    assert first["inserted"] == 2
    assert first["existing"] == 0
    assert second["inserted"] == 0
    assert second["existing"] == 2
    assert len(collection.docs) == 2

    doc = collection.docs[("req_001", "B001")]
    assert doc["algorithm_version"] == "algo_test"
    assert doc["ranking_version"] == "rank_test"
    assert doc["rank_position"] == 1
    assert doc["scores"]["query_hybrid_score"] == 0.75
    assert doc["scores"]["final_score"] == 0.75
    assert doc["attribution"]["matched_channels"] == ["vector", "bm25"]
    assert doc["is_synthetic"] is False


def test_log_clickstream_event_makes_duplicate_impression_idempotent() -> None:
    collection = FakeClickstreamEventsCollection()

    first = log_clickstream_event(
        event_id="evt_001",
        request_id="req_001",
        user_id_hash="u_demo",
        session_id="sess_001",
        surface="home",
        event_type="impression",
        item_id="B001",
        clickstream_events_collection=collection,
    )
    second = log_clickstream_event(
        event_id="evt_002",
        request_id="req_001",
        user_id_hash="u_demo",
        session_id="sess_001",
        surface="home",
        event_type="impression",
        item_id="B001",
        clickstream_events_collection=collection,
    )

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["idempotent"] is True
    assert len(collection.docs) == 1
    assert collection.docs[0]["idempotency_key"] == impression_idempotency_key("req_001", "B001")


def test_log_clickstream_event_allows_repeated_clicks_when_event_ids_differ() -> None:
    collection = FakeClickstreamEventsCollection()

    first = log_clickstream_event(
        event_id="evt_click_001",
        request_id="req_001",
        user_id_hash="u_demo",
        session_id="sess_001",
        surface="search",
        event_type="click",
        item_id="B001",
        clickstream_events_collection=collection,
    )
    second = log_clickstream_event(
        event_id="evt_click_002",
        request_id="req_001",
        user_id_hash="u_demo",
        session_id="sess_001",
        surface="search",
        event_type="click",
        item_id="B001",
        clickstream_events_collection=collection,
    )

    assert first["inserted"] is True
    assert second["inserted"] is True
    assert len(collection.docs) == 2
    assert [doc["event_id"] for doc in collection.docs] == ["evt_click_001", "evt_click_002"]


def test_log_clickstream_event_same_event_id_is_idempotent_retry() -> None:
    collection = FakeClickstreamEventsCollection()
    kwargs = {
        "event_id": "evt_retry",
        "request_id": "req_001",
        "user_id_hash": "u_demo",
        "session_id": "sess_001",
        "surface": "search",
        "event_type": "click",
        "item_id": "B001",
        "clickstream_events_collection": collection,
    }

    first = log_clickstream_event(**kwargs)
    second = log_clickstream_event(**kwargs)

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["idempotent"] is True
    assert len(collection.docs) == 1


def test_log_clickstream_event_requires_request_id_for_attributed_surfaces() -> None:
    collection = FakeClickstreamEventsCollection()
    with pytest.raises(ValueError, match="request_id is required for impression"):
        log_clickstream_event(
            event_id="evt_001",
            user_id_hash="u_demo",
            session_id="sess_001",
            surface="home",
            event_type="impression",
            item_id="B001",
            clickstream_events_collection=collection,
        )

    with pytest.raises(ValueError, match="request_id is required for search click"):
        log_clickstream_event(
            event_id="evt_002",
            user_id_hash="u_demo",
            session_id="sess_001",
            surface="search",
            event_type="click",
            item_id="B001",
            clickstream_events_collection=collection,
        )


def test_log_clickstream_event_rejects_unknown_event_type_via_schema() -> None:
    collection = FakeClickstreamEventsCollection()
    with pytest.raises(Exception):
        log_clickstream_event(
            event_id="evt_001",
            user_id_hash="u_demo",
            session_id="sess_001",
            surface="cart",
            event_type="double_click",
            item_id="B001",
            clickstream_events_collection=collection,
        )
