from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import get_settings


class FakeCursor(list):
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        return FakeCursor(self[:n])


class FakeItemsCollection:
    def __init__(self):
        self.find_calls = []
        self.docs = [
            {
                "_id": "ITEM_A",
                "title_en": "Hydrating Cleanser",
                "brand": "DemoBeauty",
                "category_id": "all_beauty",
                "source_category": "All Beauty",
                "price_bucket": "100k_300k",
                "price_vnd": 199000,
                "quality_score": 0.9,
            },
            {
                "_id": "ITEM_B",
                "title_en": "USB-C Charger",
                "brand": "DemoTech",
                "category_id": "all_electronics",
                "source_category": "All Electronics",
                "price_bucket": "300k_500k",
                "price_vnd": 349000,
                "quality_score": 0.8,
            },
        ]

    def find(self, *args, **kwargs):
        self.find_calls.append((args, kwargs))
        return FakeCursor(self.docs)


class FakeUsersCollection:
    def __init__(self, *, matched_count: int = 1):
        self.matched_count = matched_count
        self.updates = []

    def update_one(self, filter_doc, update_doc):
        self.updates.append((filter_doc, update_doc))
        return SimpleNamespace(matched_count=self.matched_count, modified_count=1)


class FakeEventsCollection:
    def __init__(self):
        self.inserted = []

    def find_one(self, *_args, **_kwargs):
        return None

    def insert_one(self, doc):
        self.inserted.append(doc)
        return SimpleNamespace(inserted_id=doc["event_id"])


def _patch_collections(monkeypatch, *, users=None, events=None, items=None):
    import src.api.routes_onboarding as routes_onboarding

    items = items or FakeItemsCollection()
    users = users or FakeUsersCollection()
    events = events or FakeEventsCollection()
    monkeypatch.setattr(routes_onboarding, "get_items_collection", lambda: items)
    monkeypatch.setattr(routes_onboarding, "get_users_collection", lambda: users)
    monkeypatch.setattr(routes_onboarding, "get_clickstream_events_collection", lambda: events)
    return users, events, items


def test_onboarding_options_are_catalog_backed_and_read_only(monkeypatch) -> None:
    _users, _events, items = _patch_collections(monkeypatch)
    client = TestClient(create_app())

    response = client.get("/api/onboarding/options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["enabled"] is True
    assert payload["source"] == "catalog_snapshot"
    assert payload["categories"][0]["id"] == "all_beauty"
    assert payload["seed_items"][0]["item_id"] == "ITEM_A"
    assert items.find_calls


def test_onboarding_preview_is_read_only(monkeypatch) -> None:
    users, events, _items = _patch_collections(monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/api/onboarding/preview",
        json={
            "user_id_hash": "u_new",
            "selected_categories": ["all_beauty"],
            "selected_price_buckets": ["100k_300k"],
            "selected_intents": ["daily_use"],
            "selected_seed_item_ids": ["ITEM_A"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["write_performed"] is False
    assert payload["preview"]["summary"]
    assert users.updates == []
    assert events.inserted == []


def test_complete_onboarding_updates_user_and_logs_onboarding_seed_events_only(monkeypatch) -> None:
    users, events, _items = _patch_collections(monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/api/onboarding/complete",
        json={
            "user_id_hash": "u_new",
            "session_id": "sess_onboarding",
            "selected_categories": ["all_beauty"],
            "selected_price_buckets": ["100k_300k"],
            "selected_intents": ["daily_use"],
            "selected_seed_item_ids": ["ITEM_A"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["write_performed"] is True
    assert payload["events_attempted"] == 1
    assert users.updates[0][0] == {"user_id_hash": "u_new"}
    user_update = users.updates[0][1]["$set"]
    assert user_update["onboarding"]["completed"] is True
    assert user_update["onboarding"]["selected_intents"] == ["daily_use"]
    assert len(events.inserted) == 1
    event = events.inserted[0]
    assert event["surface"] == "onboarding"
    assert event["event_type"] == "wishlist"
    assert event["item_id"] == "ITEM_A"
    assert event["metadata"]["source"] == "onboarding_v1"
    assert event["metadata"]["selected_categories"] == ["all_beauty"]


def test_complete_onboarding_with_no_seed_items_does_not_fake_item_events(monkeypatch) -> None:
    users, events, _items = _patch_collections(monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/api/onboarding/complete",
        json={
            "user_id_hash": "u_new",
            "session_id": "sess_onboarding",
            "selected_categories": ["all_beauty"],
            "selected_price_buckets": [],
            "selected_intents": ["gift_ready"],
            "selected_seed_item_ids": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["events_attempted"] == 0
    assert users.updates
    assert events.inserted == []


def test_onboarding_rejects_invalid_preferences(monkeypatch) -> None:
    _patch_collections(monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/api/onboarding/preview",
        json={
            "selected_categories": ["not_a_category"],
            "selected_price_buckets": ["100k_300k"],
            "selected_intents": ["daily_use"],
            "selected_seed_item_ids": [],
        },
    )

    assert response.status_code == 400
    assert "unknown categories" in response.json()["detail"]


def test_onboarding_rejects_too_many_seed_items(monkeypatch) -> None:
    _patch_collections(monkeypatch)
    client = TestClient(create_app())

    response = client.post(
        "/api/onboarding/preview",
        json={
            "selected_categories": [],
            "selected_price_buckets": [],
            "selected_intents": [],
            "selected_seed_item_ids": [f"ITEM_{idx}" for idx in range(9)],
        },
    )

    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


def test_onboarding_disabled_blocks_writes(monkeypatch) -> None:
    import src.api.routes_onboarding as routes_onboarding

    users, events, _items = _patch_collections(monkeypatch)
    monkeypatch.setattr(routes_onboarding, "get_settings", lambda: replace(get_settings(), enable_onboarding=False))
    client = TestClient(create_app())

    options_response = client.get("/api/onboarding/options")
    assert options_response.status_code == 200
    assert options_response.json()["enabled"] is False

    complete_response = client.post(
        "/api/onboarding/complete",
        json={
            "user_id_hash": "u_new",
            "session_id": "sess_onboarding",
            "selected_categories": ["all_beauty"],
            "selected_price_buckets": [],
            "selected_intents": [],
            "selected_seed_item_ids": ["ITEM_A"],
        },
    )
    assert complete_response.status_code == 403
    assert users.updates == []
    assert events.inserted == []
