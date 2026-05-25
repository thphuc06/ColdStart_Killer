from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_item_item_cf as build_item_item_cf_script
from src.recommendation.item_item_cf import build_item_item_cf_edges


FIXED_NOW = "2026-01-10T00:00:00+00:00"


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
        matched = 0
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
                matched += 1
                before = dict(found)
                found.update(set_doc)
                if found != before:
                    modified += 1

        class Result:
            upserted_count = upserted
            matched_count = matched
            modified_count = modified

        return Result()

    def delete_many(self, filter_doc: dict):
        before = len(self.docs)
        if not filter_doc:
            self.docs = []
        else:
            retained_ids = set(filter_doc["_id"]["$nin"])
            self.docs = [doc for doc in self.docs if doc.get("_id") in retained_ids]

        class Result:
            deleted_count = before - len(self.docs)

        return Result()


def _signal(
    user_id_hash: str,
    item_id: str,
    *,
    implicit_score: float,
    preference: bool = True,
    positive_score: float | None = None,
    clicks: int = 1,
    views: int = 0,
    carts: int = 0,
    purchases: int = 0,
    last_interaction_at: str = "2026-01-10T00:00:00+00:00",
) -> dict:
    return {
        "user_id_hash": user_id_hash,
        "item_id": item_id,
        "implicit_score": implicit_score,
        "positive_score": implicit_score if positive_score is None else positive_score,
        "preference": preference,
        "event_counts": {
            "impression": 1,
            "click": clicks,
            "view_detail": views,
            "add_to_cart": carts,
            "purchase": purchases,
            "wishlist": 0,
            "hide": 0,
            "dislike": 0,
        },
        "derivation": {
            "model_version": "signal_test_v1",
            "source_collection": "clickstream_events",
            "source_event_count": 2,
            "built_at": last_interaction_at,
        },
        "last_interaction_at": last_interaction_at,
    }


def _item(item_id: str) -> dict:
    return {"_id": item_id, "title_en": f"Item {item_id}"}


def test_build_item_item_cf_creates_symmetric_edges_with_support_and_event_evidence() -> None:
    result = build_item_item_cf_edges(
        user_item_signals_collection=FakeCollection(
            [
                _signal("u1", "A", implicit_score=3.0, clicks=1, views=1, carts=1, purchases=0),
                _signal("u1", "B", implicit_score=2.0, clicks=1, views=1, carts=1, purchases=1),
                _signal("u2", "A", implicit_score=4.0, clicks=1, views=1, carts=0, purchases=1),
                _signal("u2", "B", implicit_score=5.0, clicks=1, views=1, carts=0, purchases=1),
            ]
        ),
        items_collection=FakeCollection([_item("A"), _item("B")]),
        min_support=2,
        updated_at=FIXED_NOW,
    )

    assert result["ok"] is True
    assert result["stats"]["undirected_pairs_retained"] == 1
    assert result["stats"]["directional_edges_built"] == 2

    edges = {(edge["item_id"], edge["neighbor_item_id"]): edge for edge in result["sample_edges"]}
    edge_ab = edges[("A", "B")]
    edge_ba = edges[("B", "A")]

    assert edge_ab["support"] == 2
    assert edge_ba["support"] == 2
    assert edge_ab["co_view_count"] == 2
    assert edge_ab["co_click_count"] == 2
    assert edge_ab["co_cart_count"] == 1
    assert edge_ab["co_purchase_count"] == 1
    assert math.isclose(edge_ab["cf_score"], 3.0)
    assert math.isclose(edge_ba["cf_score"], 3.0)
    assert edge_ab["derivation"]["model_version"]
    assert edge_ab["derivation"]["source_signal_model_version"] == "signal_test_v1"
    assert edge_ab["derivation"]["source_signal_count"] == 4


def test_build_item_item_cf_applies_support_threshold_and_caps_items_per_user() -> None:
    result = build_item_item_cf_edges(
        user_item_signals_collection=FakeCollection(
            [
                _signal("u1", "A", implicit_score=5.0),
                _signal("u1", "B", implicit_score=4.0),
                _signal("u1", "C", implicit_score=3.0),
                _signal("u2", "A", implicit_score=5.0),
                _signal("u2", "B", implicit_score=4.0),
                _signal("u3", "A", implicit_score=5.0),
                _signal("u3", "B", implicit_score=4.0),
            ]
        ),
        items_collection=FakeCollection([_item("A"), _item("B"), _item("C")]),
        min_support=2,
        max_items_per_user=2,
        updated_at=FIXED_NOW,
    )

    assert result["stats"]["undirected_pairs_retained"] == 1
    assert {(edge["item_id"], edge["neighbor_item_id"]) for edge in result["sample_edges"]} == {
        ("A", "B"),
        ("B", "A"),
    }


def test_build_item_item_cf_uses_behavior_signals_without_embeddings_and_skips_missing_items() -> None:
    result = build_item_item_cf_edges(
        user_item_signals_collection=FakeCollection(
            [
                _signal("u1", "A", implicit_score=2.0, preference=True),
                _signal("u1", "B", implicit_score=2.0, preference=True),
                _signal("u1", "MISSING", implicit_score=10.0, preference=True),
                _signal("u2", "A", implicit_score=2.0, preference=True),
                _signal("u2", "B", implicit_score=2.0, preference=True),
            ]
        ),
        items_collection=FakeCollection([_item("A"), _item("B")]),
        min_support=2,
        updated_at=FIXED_NOW,
    )

    assert result["ok"] is True
    assert result["stats"]["missing_items_skipped"] >= 1
    assert result["stats"]["directional_edges_built"] == 2


def test_build_item_item_cf_keeps_symmetry_when_neighbor_cap_is_reached() -> None:
    result = build_item_item_cf_edges(
        user_item_signals_collection=FakeCollection(
            [
                _signal("u1", "A", implicit_score=5.0),
                _signal("u1", "B", implicit_score=4.0),
                _signal("u1", "C", implicit_score=3.0),
                _signal("u2", "A", implicit_score=5.0),
                _signal("u2", "B", implicit_score=4.0),
                _signal("u2", "C", implicit_score=3.0),
            ]
        ),
        items_collection=FakeCollection([_item("A"), _item("B"), _item("C")]),
        min_support=2,
        top_neighbors_per_item=1,
        updated_at=FIXED_NOW,
    )

    edge_keys = {(edge["item_id"], edge["neighbor_item_id"]) for edge in result["sample_edges"]}
    assert result["stats"]["undirected_pairs_retained"] == 3
    assert result["stats"]["undirected_pairs_selected"] == 1
    assert len(edge_keys) == 2
    assert all((right, left) in edge_keys for left, right in edge_keys)


def test_build_item_item_cf_replace_existing_deletes_stale_edges_after_full_write() -> None:
    edges = FakeCollection([{"_id": "OLD::STALE", "item_id": "OLD", "neighbor_item_id": "STALE"}])
    result = build_item_item_cf_edges(
        user_item_signals_collection=FakeCollection(
            [
                _signal("u1", "A", implicit_score=3.0),
                _signal("u1", "B", implicit_score=2.0),
                _signal("u2", "A", implicit_score=3.0),
                _signal("u2", "B", implicit_score=2.0),
            ]
        ),
        items_collection=FakeCollection([_item("A"), _item("B")]),
        item_item_cf_edges_collection=edges,
        write=True,
        replace_existing=True,
        min_support=2,
        updated_at=FIXED_NOW,
    )

    assert result["stats"]["stale_edges_deleted"] == 1
    assert {(doc["item_id"], doc["neighbor_item_id"]) for doc in edges.docs} == {("A", "B"), ("B", "A")}


def test_build_item_item_cf_rejects_limited_write_mode() -> None:
    with pytest.raises(ValueError, match="unsafe_partial_cf_write"):
        build_item_item_cf_edges(
            user_item_signals_collection=FakeCollection([
                _signal("u1", "A", implicit_score=3.0),
                _signal("u1", "B", implicit_score=2.0),
            ]),
            items_collection=FakeCollection([_item("A"), _item("B")]),
            item_item_cf_edges_collection=FakeCollection([]),
            write=True,
            limit_users=1,
            updated_at=FIXED_NOW,
        )


def test_phase7_script_dry_run_does_not_write_edges(monkeypatch, capsys) -> None:
    user_item_signals = FakeCollection(
        [
            _signal("u1", "A", implicit_score=3.0),
            _signal("u1", "B", implicit_score=2.0),
            _signal("u2", "A", implicit_score=3.0),
            _signal("u2", "B", implicit_score=2.0),
        ]
    )
    items = FakeCollection([_item("A"), _item("B")])
    edges = FakeCollection([])

    monkeypatch.setattr(build_item_item_cf_script, "get_user_item_signals_collection", lambda: user_item_signals)
    monkeypatch.setattr(build_item_item_cf_script, "get_items_collection", lambda: items)
    monkeypatch.setattr(build_item_item_cf_script, "get_item_item_cf_edges_collection", lambda: edges)

    exit_code = build_item_item_cf_script.main(["--dry-run", "--limit-users", "2"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"mode": "dry-run"' in captured.out
    assert edges.docs == []
