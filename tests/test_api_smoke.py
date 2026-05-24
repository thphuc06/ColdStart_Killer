from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app


def test_health_endpoint_returns_versions() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["algorithm_version"]
    assert payload["ranking_version"]


def test_demo_users_route_returns_users_and_personas(monkeypatch) -> None:
    class FakeCursor(list):
        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, n):
            return FakeCursor(self[:n])

    class FakeCollection:
        def __init__(self, docs):
            self.docs = docs

        def find(self, *_args, **_kwargs):
            return FakeCursor(self.docs)

    import src.api.routes_users as routes_users

    monkeypatch.setattr(routes_users, "get_users_collection", lambda: FakeCollection([{"user_id_hash": "u_1"}]))
    monkeypatch.setattr(
        routes_users,
        "get_synthetic_personas_collection",
        lambda: FakeCollection([
            {
                "persona_id": "p_budget_skincare",
                "label": "Budget skincare shopper",
                "intent_keywords": ["cleanser"],
            }
        ]),
    )

    client = TestClient(create_app())
    response = client.get("/api/users/demo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["users"][0]["user_id_hash"] == "u_1"
    assert payload["personas"][0]["persona_id"] == "p_budget_skincare"
    assert "intent_embedding" not in payload["personas"][0]


def test_feed_home_route_delegates_to_service(monkeypatch) -> None:
    expected = {
        "request_id": "req_1",
        "surface": "home",
        "items": [{"item_id": "A1", "title": "Example"}],
        "algorithm_version": "rec_v1",
        "ranking_version": "rank_v1",
        "snapshot": {"ok": True},
    }

    def fake_service(**kwargs):
        assert kwargs["user_id_hash"] == "u_1"
        assert kwargs["session_id"] == "sess_1"
        assert kwargs["top_k"] == 5
        return dict(expected)

    import src.api.routes_feed as routes_feed

    monkeypatch.setattr(routes_feed, "get_homepage_feed", fake_service)
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/feed/home", params={"user_id_hash": "u_1", "session_id": "sess_1", "top_k": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req_1"
    assert payload["user_id_hash"] == "u_1"
    assert payload["items"][0]["item_id"] == "A1"


def test_search_route_delegates_to_service(monkeypatch) -> None:
    expected = {
        "request_id": "req_search_1",
        "surface": "search",
        "items": [{"item_id": "A2"}],
        "query": {"raw_query": "iphone case"},
        "algorithm_version": "rec_v1",
        "ranking_version": "rank_v1",
        "snapshot": {"ok": True},
    }

    def fake_service(**kwargs):
        assert kwargs["raw_query"] == "iphone case"
        return dict(expected)

    import src.api.routes_search as routes_search

    monkeypatch.setattr(routes_search, "personalized_search", fake_service)
    client = TestClient(create_app())
    response = client.get(
        "/api/search",
        params={"user_id_hash": "u_2", "session_id": "sess_2", "q": "iphone case"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req_search_1"
    assert payload["user_id_hash"] == "u_2"


def test_items_route_returns_404_when_missing(monkeypatch) -> None:
    class FakeItemsCollection:
        def find_one(self, *_args, **_kwargs):
            return None

    import src.api.routes_items as routes_items

    monkeypatch.setattr(routes_items, "get_items_collection", lambda: FakeItemsCollection())
    client = TestClient(create_app())
    response = client.get("/api/items/does-not-exist")
    assert response.status_code == 404


def test_events_route_delegates_to_logger(monkeypatch) -> None:
    called = {}

    def fake_log_clickstream_event(**kwargs):
        called.update(kwargs)
        return {"ok": True, "inserted": True, "event_id": "evt_1"}

    import src.api.routes_events as routes_events

    monkeypatch.setattr(routes_events, "log_clickstream_event", fake_log_clickstream_event)
    client = TestClient(create_app())
    response = client.post(
        "/api/events",
        json={
            "user_id_hash": "u_1",
            "session_id": "sess_1",
            "item_id": "A1",
            "event_type": "click",
            "surface": "home",
            "request_id": "req_1",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert called["item_id"] == "A1"


def test_debug_user_route_returns_joined_debug_payload(monkeypatch) -> None:
    class FakeCursor(list):
        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, n):
            return FakeCursor(self[:n])

    class FakeCollection:
        def __init__(self, docs):
            self.docs = docs

        def find_one(self, *_args, **_kwargs):
            return self.docs[0] if self.docs else None

        def find(self, *_args, **_kwargs):
            return FakeCursor(self.docs)

    import src.api.routes_debug as routes_debug

    monkeypatch.setattr(routes_debug, "get_users_collection", lambda: FakeCollection([{"user_id_hash": "u_1"}]))
    monkeypatch.setattr(routes_debug, "get_user_profiles_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "profile_status": "warming"}]))
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "item_id": "A1"}]))
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "request_id": "req_1"}]))
    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "event_id": "evt_1"}]))
    monkeypatch.setattr(routes_debug, "get_item_item_cf_edges_collection", lambda: FakeCollection([{"item_id": "A1", "neighbor_item_id": "A2"}]))

    client = TestClient(create_app())
    response = client.get("/api/debug/user/u_1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["profile_status"] == "warming"
    assert payload["signals"][0]["item_id"] == "A1"


def test_demo_reset_dry_run_reports_counts(monkeypatch) -> None:
    class FakeCollection:
        def __init__(self, count):
            self.count = count

        def count_documents(self, *_args, **_kwargs):
            return self.count

        def delete_many(self, *_args, **_kwargs):
            raise AssertionError("delete_many should not be called in dry-run")

    import src.api.routes_debug as routes_debug

    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: FakeCollection(11))
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection", lambda: FakeCollection(12))
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: FakeCollection(13))
    monkeypatch.setattr(routes_debug, "get_user_profiles_collection", lambda: FakeCollection(14))
    monkeypatch.setattr(routes_debug, "get_item_stats_collection", lambda: FakeCollection(15))
    client = TestClient(create_app())
    response = client.post("/api/demo/reset")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert payload["delete_counts"]["clickstream_events"] == 11


def test_demo_reset_write_requires_confirmation(monkeypatch) -> None:
    class FakeCollection:
        def __init__(self, count):
            self.count = count

        def count_documents(self, *_args, **_kwargs):
            return self.count

        def delete_many(self, *_args, **_kwargs):
            raise AssertionError("delete_many should not be called without confirmation")

    import src.api.routes_debug as routes_debug

    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: FakeCollection(11))
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection", lambda: FakeCollection(12))
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: FakeCollection(13))
    monkeypatch.setattr(routes_debug, "get_user_profiles_collection", lambda: FakeCollection(14))
    monkeypatch.setattr(routes_debug, "get_item_stats_collection", lambda: FakeCollection(15))

    client = TestClient(create_app())
    response = client.post("/api/demo/reset?write=true")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "confirmation_required"
    assert detail["expected_confirm"] == "DEMO_RESET"
