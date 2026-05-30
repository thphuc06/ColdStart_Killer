from __future__ import annotations

import pytest

import src.behavior.incremental_processor as processor


FIXED_NOW = "2026-01-03T00:00:00+00:00"


class FakeResult:
    def __init__(self, *, upserted_count: int = 0, modified_count: int = 0) -> None:
        self.upserted_count = upserted_count
        self.modified_count = modified_count


class FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = [dict(doc) for doc in (docs or [])]

    @staticmethod
    def _match(doc: dict, filter_doc: dict) -> bool:
        for key, value in filter_doc.items():
            if key == "$or":
                return any(FakeCollection._match(doc, clause) for clause in value)
            if isinstance(value, dict) and "$ne" in value:
                if doc.get(key) == value["$ne"]:
                    return False
                continue
            if isinstance(value, dict) and "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
                continue
            if doc.get(key) != value:
                return False
        return True

    def find(self, filter_doc: dict, projection: dict | None = None):
        rows = []
        for doc in self.docs:
            if not self._match(doc, filter_doc):
                continue
            if projection:
                rows.append({key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc})
            else:
                rows.append(dict(doc))
        return rows

    def bulk_write(self, operations, ordered=False):
        assert ordered is False
        upserted = 0
        modified = 0
        for operation in operations:
            match = next((doc for doc in self.docs if self._match(doc, operation._filter)), None)
            set_doc = dict(operation._doc.get("$set", {}))
            if match is None:
                self.docs.append({**operation._doc.get("$setOnInsert", {}), **set_doc})
                upserted += 1
                continue
            before = dict(match)
            match.update(set_doc)
            modified += int(match != before)
        return FakeResult(upserted_count=upserted, modified_count=modified)


def _event(event_id: str, event_type: str, timestamp: str, *, processed: bool, item_id: str = "A") -> dict:
    return {
        "event_id": event_id,
        "request_id": "",
        "user_id_hash": "u1",
        "item_id": item_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "processed": processed,
    }


def test_incremental_processor_recomputes_complete_affected_signal_and_marks_only_selected_batch(monkeypatch) -> None:
    events = FakeCollection(
        [
            _event("evt_old", "click", "2026-01-01T00:00:00+00:00", processed=True),
            _event("evt_apply", "add_to_cart", "2026-01-02T00:00:00+00:00", processed=False),
            _event("evt_later", "click", "2026-01-04T00:00:00+00:00", processed=False, item_id="B"),
        ]
    )
    signals = FakeCollection()
    item_stats = FakeCollection()
    profile_calls = []
    monkeypatch.setattr(
        processor,
        "build_user_profiles",
        lambda **kwargs: profile_calls.append(kwargs) or {"ok": True, "stats": {"profiles_built": 1, "profiles_written": 1}},
    )

    result = processor.process_pending_behavior(
        clickstream_events_collection=events,
        recommendation_logs_collection=FakeCollection(),
        user_item_signals_collection=signals,
        item_stats_collection=item_stats,
        user_profiles_collection=FakeCollection(),
        item_hype_profiles_collection=FakeCollection(),
        items_collection=FakeCollection(),
        write=True,
        max_events=1,
        updated_at=FIXED_NOW,
    )

    signal = signals.docs[0]
    assert result["processing_mode"] == "incremental_pending"
    assert result["events_selected"] == 1
    assert result["cf_refresh_required"] is True
    assert signal["item_id"] == "A"
    assert signal["event_counts"]["click"] == 1
    assert signal["event_counts"]["add_to_cart"] == 1
    assert profile_calls[0]["user_ids"] == {"u1"}
    assert next(doc for doc in events.docs if doc["event_id"] == "evt_apply")["processed"] is True
    assert next(doc for doc in events.docs if doc["event_id"] == "evt_later")["processed"] is False


def test_incremental_processor_does_not_mark_events_when_profile_refresh_fails(monkeypatch) -> None:
    events = FakeCollection([_event("evt_pending", "dislike", "2026-01-02T00:00:00+00:00", processed=False)])
    monkeypatch.setattr(
        processor,
        "build_user_profiles",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("profile failure")),
    )

    with pytest.raises(RuntimeError, match="profile failure"):
        processor.process_pending_behavior(
            clickstream_events_collection=events,
            recommendation_logs_collection=FakeCollection(),
            user_item_signals_collection=FakeCollection(),
            item_stats_collection=FakeCollection(),
            user_profiles_collection=FakeCollection(),
            item_hype_profiles_collection=FakeCollection(),
            items_collection=FakeCollection(),
            write=True,
            max_events=1,
            updated_at=FIXED_NOW,
        )

    assert events.docs[0]["processed"] is False


def test_incremental_processor_can_scope_pending_events_to_one_user(monkeypatch) -> None:
    events = FakeCollection(
        [
            {**_event("evt_other", "click", "2026-01-01T00:00:00+00:00", processed=False), "user_id_hash": "u_other"},
            {**_event("evt_target", "add_to_cart", "2026-01-02T00:00:00+00:00", processed=False), "user_id_hash": "u_target"},
        ]
    )
    profile_calls = []
    monkeypatch.setattr(
        processor,
        "build_user_profiles",
        lambda **kwargs: profile_calls.append(kwargs) or {"ok": True, "stats": {"profiles_built": 1, "profiles_written": 1}},
    )

    result = processor.process_pending_behavior(
        clickstream_events_collection=events,
        recommendation_logs_collection=FakeCollection(),
        user_item_signals_collection=FakeCollection(),
        item_stats_collection=FakeCollection(),
        user_profiles_collection=FakeCollection(),
        item_hype_profiles_collection=FakeCollection(),
        items_collection=FakeCollection(),
        write=True,
        max_events=10,
        user_id_hash="u_target",
        updated_at=FIXED_NOW,
    )

    assert result["target_user_id_hash"] == "u_target"
    assert result["events_selected"] == 1
    assert profile_calls[0]["user_ids"] == {"u_target"}
    assert next(doc for doc in events.docs if doc["event_id"] == "evt_target")["processed"] is True
    assert next(doc for doc in events.docs if doc["event_id"] == "evt_other")["processed"] is False
