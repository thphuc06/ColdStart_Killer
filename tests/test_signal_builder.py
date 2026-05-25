from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_user_item_signals as build_user_item_signals_script
from src.behavior.signal_builder import build_user_item_signals


FIXED_NOW = "2026-01-01T00:00:00+00:00"


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = list(docs)

    def limit(self, limit: int):
        self.docs = self.docs[:limit]
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeBulkResult:
    def __init__(self, *, upserted_count: int = 0, matched_count: int = 0, modified_count: int = 0) -> None:
        self.upserted_count = upserted_count
        self.matched_count = matched_count
        self.modified_count = modified_count


def _project(doc: dict, projection: dict | None) -> dict:
    if not projection:
        return dict(doc)
    return {key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc}


class FakeClickstreamEventsCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]
        self.bulk_calls = []

    def find(self, filter_doc: dict, projection: dict | None = None):
        assert filter_doc == {}
        return FakeCursor([_project(doc, projection) for doc in self.docs])

    def count_documents(self, filter_doc: dict):
        assert filter_doc == {}
        return len(self.docs)

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        self.bulk_calls.extend(operations)
        matched = 0
        modified = 0
        for operation in operations:
            event_id = operation._filter["event_id"]
            update = operation._doc.get("$set", {})
            for doc in self.docs:
                if doc.get("event_id") != event_id:
                    continue
                matched += 1
                before = dict(doc)
                doc.update(update)
                if doc != before:
                    modified += 1
                break
        return FakeBulkResult(matched_count=matched, modified_count=modified)


class FakeRecommendationLogsCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    def find(self, filter_doc: dict, projection: dict | None = None):
        clauses = filter_doc.get("$or", [])
        keys = {(clause["request_id"], clause["item_id"]) for clause in clauses}
        docs = [
            _project(doc, projection)
            for doc in self.docs
            if (doc.get("request_id"), doc.get("item_id")) in keys
        ]
        return FakeCursor(docs)


class FakeUpsertCollection:
    def __init__(self, key_fields: tuple[str, ...]) -> None:
        self.key_fields = key_fields
        self.docs = {}
        self.bulk_calls = []

    def _key(self, filter_doc: dict):
        return tuple(filter_doc[field] for field in self.key_fields)

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        self.bulk_calls.extend(operations)
        upserted = 0
        matched = 0
        modified = 0
        for operation in operations:
            key = self._key(operation._filter)
            set_doc = dict(operation._doc.get("$set", {}))
            insert_doc = dict(operation._doc.get("$setOnInsert", {}))
            if key not in self.docs:
                self.docs[key] = {**insert_doc, **set_doc}
                upserted += 1
                continue
            matched += 1
            before = dict(self.docs[key])
            self.docs[key].update(set_doc)
            if self.docs[key] != before:
                modified += 1
        return FakeBulkResult(upserted_count=upserted, matched_count=matched, modified_count=modified)


def _event(
    event_id: str,
    event_type: str,
    *,
    item_id: str = "B001",
    user_id_hash: str = "u_demo",
    request_id: str = "req_001",
    dwell_time_ms: int | None = None,
    timestamp: str | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "request_id": request_id,
        "user_id_hash": user_id_hash,
        "session_id": "sess_001",
        "surface": "search",
        "event_type": event_type,
        "item_id": item_id,
        "dwell_time_ms": dwell_time_ms,
        "timestamp": timestamp or f"2026-01-01T00:00:0{len(event_id) % 9}+00:00",
        "processed": False,
    }


def _recommendation_log(
    *,
    request_id: str = "req_001",
    item_id: str = "B001",
    score: float = 0.8,
    intents: list[str] | None = None,
    facts: list[str] | None = None,
    unit_ids: list[str] | None = None,
) -> dict:
    return {
        "request_id": request_id,
        "item_id": item_id,
        "scores": {"final_score": score, "profile_score": score / 2},
        "attribution": {
            "matched_intents": ["oil-control sunscreen"] if intents is None else intents,
            "matched_facts": facts or [],
            "matched_unit_ids": unit_ids or [],
            "candidate_sources": ["profile_seed"],
            "matched_channels": ["synthetic_persona_match"],
            "explanation": "Matched synthetic skincare intent.",
        },
        "shown_at": "2026-01-01T00:00:00+00:00",
    }


def _run_builder(events: list[dict], logs: list[dict] | None = None, **kwargs):
    return build_user_item_signals(
        clickstream_events_collection=FakeClickstreamEventsCollection(events),
        recommendation_logs_collection=FakeRecommendationLogsCollection(logs or []),
        updated_at=FIXED_NOW,
        **kwargs,
    )


def test_positive_events_create_positive_signal_and_preserve_recommendation_attribution() -> None:
    result = _run_builder(
        [
            _event("evt_imp", "impression", timestamp="2026-01-01T00:00:00+00:00"),
            _event("evt_click", "click", timestamp="2026-01-01T00:01:00+00:00"),
            _event("evt_view", "view_detail", dwell_time_ms=30_000, timestamp="2026-01-01T00:02:00+00:00"),
        ],
        [_recommendation_log()],
        rebuild_item_stats=True,
    )

    assert result["ok"] is True
    signal = result["sample_signals"][0]
    assert signal["event_counts"]["impression"] == 1
    assert signal["event_counts"]["click"] == 1
    assert signal["event_counts"]["view_detail"] == 1
    assert signal["positive_score"] == 2.5
    assert signal["negative_score"] == 0.0
    assert signal["implicit_score"] == 2.5
    assert signal["preference"] is True
    assert signal["first_interaction_at"] == "2026-01-01T00:00:00+00:00"
    assert signal["last_interaction_at"] == "2026-01-01T00:02:00+00:00"
    assert signal["reason_scores"][0]["intent"] == "oil-control sunscreen"
    assert signal["reason_scores"][0]["source"] == "profile_seed"
    assert signal["reason_scores"][0]["score"] > 0.0


def test_product_facts_and_unit_ids_do_not_become_interest_reasons() -> None:
    result = _run_builder(
        [_event("evt_click", "click")],
        [
            _recommendation_log(
                intents=[],
                facts=["The smartphone has a 6.4-inch AMOLED touchscreen."],
                unit_ids=["uuid-retrieval-unit"],
            )
        ],
    )

    assert result["sample_signals"][0]["reason_scores"] == []


def test_hide_and_dislike_create_negative_signal() -> None:
    result = _run_builder(
        [
            _event("evt_hide", "hide", request_id=None),
            _event("evt_dislike", "dislike", request_id=None),
        ]
    )

    signal = result["sample_signals"][0]
    assert signal["positive_score"] == 0.0
    assert signal["negative_score"] == 5.0
    assert signal["implicit_score"] == -5.0
    assert signal["preference"] is False
    assert signal["event_counts"]["hide"] == 1
    assert signal["event_counts"]["dislike"] == 1


def test_item_stats_counts_and_rates_are_deterministic() -> None:
    events = [
        _event("evt_imp_1", "impression"),
        _event("evt_imp_2", "impression"),
        _event("evt_imp_3", "impression"),
        _event("evt_imp_4", "impression"),
        _event("evt_click_1", "click"),
        _event("evt_click_2", "click"),
        _event("evt_view", "view_detail"),
        _event("evt_cart", "add_to_cart"),
        _event("evt_purchase", "purchase"),
        _event("evt_hide", "hide"),
        _event("evt_dislike", "dislike"),
    ]

    result = _run_builder(events, [_recommendation_log()], rebuild_item_stats=True)
    stats_doc = result["sample_item_stats"][0]

    assert stats_doc["impression_count"] == 4
    assert stats_doc["click_count"] == 2
    assert stats_doc["view_detail_count"] == 1
    assert stats_doc["add_to_cart_count"] == 1
    assert stats_doc["purchase_count"] == 1
    assert stats_doc["hide_count"] == 1
    assert stats_doc["dislike_count"] == 1
    assert math.isclose(stats_doc["ctr"], 0.5)
    assert math.isclose(stats_doc["cart_rate"], 0.25)
    assert math.isclose(stats_doc["purchase_rate"], 0.25)
    assert stats_doc["cold_start"]["interaction_count"] == 11
    assert stats_doc["cold_start"]["is_cold_item"] is True


def test_write_mode_is_idempotent_and_marks_events_processed_after_write() -> None:
    events = [
        _event("evt_imp", "impression"),
        _event("evt_click", "click"),
        _event("evt_cart", "add_to_cart"),
    ]
    clickstream = FakeClickstreamEventsCollection(events)
    logs = FakeRecommendationLogsCollection([_recommendation_log()])
    signals = FakeUpsertCollection(("user_id_hash", "item_id"))
    item_stats = FakeUpsertCollection(("_id",))

    first = build_user_item_signals(
        clickstream_events_collection=clickstream,
        recommendation_logs_collection=logs,
        user_item_signals_collection=signals,
        item_stats_collection=item_stats,
        write=True,
        rebuild_item_stats=True,
        updated_at=FIXED_NOW,
    )
    signal_after_first = dict(signals.docs[("u_demo", "B001")])
    stats_after_first = dict(item_stats.docs[("B001",)])

    second = build_user_item_signals(
        clickstream_events_collection=clickstream,
        recommendation_logs_collection=logs,
        user_item_signals_collection=signals,
        item_stats_collection=item_stats,
        write=True,
        rebuild_item_stats=True,
        updated_at=FIXED_NOW,
    )

    assert first["stats"]["signals_built"] == 1
    assert second["stats"]["signals_built"] == 1
    assert signals.docs[("u_demo", "B001")] == signal_after_first
    assert item_stats.docs[("B001",)] == stats_after_first
    assert signal_after_first["event_counts"]["impression"] == 1
    assert signal_after_first["event_counts"]["click"] == 1
    assert signal_after_first["event_counts"]["add_to_cart"] == 1
    assert signal_after_first["positive_score"] == 4.0
    assert all(doc["processed"] is True for doc in clickstream.docs)
    assert all(doc["processed_at"] == FIXED_NOW for doc in clickstream.docs)


def test_write_mode_rejects_limited_event_subset_before_overwriting_aggregates() -> None:
    clickstream = FakeClickstreamEventsCollection([_event("evt_click", "click"), _event("evt_cart", "add_to_cart")])
    signals = FakeUpsertCollection(("user_id_hash", "item_id"))

    with pytest.raises(ValueError, match="unsafe_partial_signal_write"):
        build_user_item_signals(
            clickstream_events_collection=clickstream,
            recommendation_logs_collection=FakeRecommendationLogsCollection([]),
            user_item_signals_collection=signals,
            write=True,
            limit_events=1,
            updated_at=FIXED_NOW,
        )

    assert signals.docs == {}
    assert clickstream.bulk_calls == []


def test_phase5_script_does_not_request_profile_or_cf_collections(monkeypatch, capsys) -> None:
    events = [_event("evt_click", "click")]
    logs = [_recommendation_log()]
    clickstream = FakeClickstreamEventsCollection(events)
    signals = FakeUpsertCollection(("user_id_hash", "item_id"))
    item_stats = FakeUpsertCollection(("_id",))

    monkeypatch.setattr(build_user_item_signals_script, "get_clickstream_events_collection", lambda: clickstream)
    monkeypatch.setattr(
        build_user_item_signals_script,
        "get_recommendation_logs_collection",
        lambda: FakeRecommendationLogsCollection(logs),
    )
    monkeypatch.setattr(build_user_item_signals_script, "get_user_item_signals_collection", lambda: signals)
    monkeypatch.setattr(build_user_item_signals_script, "get_item_stats_collection", lambda: item_stats)

    def forbidden_getter():
        raise AssertionError("Phase 5 must not access profile or CF collections")

    import src.mongodb as mongodb

    monkeypatch.setattr(mongodb, "get_user_profiles_collection", forbidden_getter)
    monkeypatch.setattr(mongodb, "get_item_item_cf_edges_collection", forbidden_getter)

    exit_code = build_user_item_signals_script.main(["--dry-run", "--rebuild-item-stats"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"mode": "dry-run"' in captured.out
    assert signals.docs == {}
    assert item_stats.docs == {}
