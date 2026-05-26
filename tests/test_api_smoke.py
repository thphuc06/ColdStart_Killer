from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app


ADMIN_TOKEN = "test-admin-token"


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN_TOKEN}


def _admin_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    return TestClient(create_app())


def test_health_endpoint_returns_versions() -> None:
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["algorithm_version"]
    assert payload["ranking_version"]


def test_evaluation_latest_route_returns_empty_state(monkeypatch) -> None:
    class FakeCursor(list):
        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, n):
            return FakeCursor(self[:n])

    class FakeCollection:
        def find(self, *_args, **_kwargs):
            return FakeCursor([])

    import src.api.routes_evaluation as routes_evaluation

    monkeypatch.setattr(routes_evaluation, "get_evaluation_runs_collection", lambda: FakeCollection())
    client = TestClient(create_app())
    response = client.get("/api/evaluation/runs/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["empty"] is True
    assert payload["latest"] is None


def test_seller_drafts_route_returns_disabled_state(monkeypatch) -> None:
    import src.api.routes_seller as routes_seller

    monkeypatch.setattr(
        routes_seller,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "enable_seller_tools": False,
                "seller_index_confirmation": "INDEX_SELLER_DRAFT",
            },
        )(),
    )
    client = TestClient(create_app())
    response = client.get("/api/seller/drafts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["enabled"] is False


def test_web_enrichment_preview_route_returns_disabled_state(monkeypatch) -> None:
    import src.api.routes_enrichment as routes_enrichment

    monkeypatch.setattr(
        routes_enrichment,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "enable_seller_tools": True,
                "enable_web_enrichment": False,
                "web_enrichment_provider": "tavily",
                "web_enrichment_apply_confirmation": "APPLY_WEB_ENRICHMENT",
            },
        )(),
    )
    client = TestClient(create_app())
    response = client.post("/api/enrichment/seller-drafts/draft_missing/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["enabled"] is False
    assert payload["status"] == "disabled"


def test_jobs_registry_route_requires_admin_and_returns_registry(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_JOB_TRIGGER_API", "false")
    client = _admin_client(monkeypatch)
    response = client.get("/api/jobs/registry", headers=_admin_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["trigger_api_enabled"] is False
    assert any(job["job_type"] == "fusion_comparison_dry_run" for job in payload["jobs"])


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

    monkeypatch.setattr(routes_users, "get_users_collection", lambda: FakeCollection([{"user_id_hash": "u_api_1"}]))
    monkeypatch.setattr(
        routes_users,
        "get_user_profiles_collection",
        lambda: FakeCollection([{"user_id_hash": "u_profile_1", "profile_status": "warm"}]),
    )
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
    assert payload["users"][0]["user_id_hash"] == "u_profile_1"
    assert payload["users"][0]["has_profile"] is True
    assert payload["users"][1]["user_id_hash"] == "u_api_1"
    assert payload["users"][1]["has_profile"] is False
    assert payload["personas"][0]["persona_id"] == "p_budget_skincare"
    assert "intent_embedding" not in payload["personas"][0]


def test_onboarding_options_route_returns_catalog_options(monkeypatch) -> None:
    class FakeCursor(list):
        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, n):
            return FakeCursor(self[:n])

    class FakeCollection:
        def find(self, *_args, **_kwargs):
            return FakeCursor(
                [
                    {
                        "_id": "A1",
                        "title_en": "Example",
                        "category_id": "all_beauty",
                        "source_category": "All Beauty",
                        "price_bucket": "100k_300k",
                    }
                ]
            )

    import src.api.routes_onboarding as routes_onboarding

    monkeypatch.setattr(routes_onboarding, "get_items_collection", lambda: FakeCollection())
    client = TestClient(create_app())
    response = client.get("/api/onboarding/options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["enabled"] is True
    assert payload["categories"][0]["id"] == "all_beauty"


def test_create_user_persists_username_for_personal_shopper(monkeypatch) -> None:
    class FakeUsersCollection:
        def __init__(self):
            self.inserted = None

        def insert_one(self, doc):
            self.inserted = doc

    import src.api.routes_users as routes_users

    users = FakeUsersCollection()
    monkeypatch.setattr(routes_users, "get_users_collection", lambda: users)

    client = TestClient(create_app())
    response = client.post(
        "/api/users",
        json={
            "display_name": "Phuc demo shopper",
            "allow_personalization": True,
            "allow_clickstream_logging": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["username"] == "Phuc demo shopper"
    assert response.json()["demo_label"] == "Phuc demo shopper"
    assert response.json()["demo_source"] == "user_created"
    assert users.inserted["username"] == "Phuc demo shopper"
    assert users.inserted["demo_label"] == "Phuc demo shopper"


def test_create_user_rejects_blank_username() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/users",
        json={
            "display_name": "   ",
            "allow_personalization": True,
            "allow_clickstream_logging": True,
        },
    )

    assert response.status_code == 422


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
    monkeypatch.setattr(routes_feed, "personalization_enabled_for_user", lambda *_args, **_kwargs: True)
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/feed/home", params={"user_id_hash": "u_1", "session_id": "sess_1", "top_k": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req_1"
    assert payload["user_id_hash"] == "u_1"
    assert payload["items"][0]["item_id"] == "A1"


def test_feed_home_route_disables_personalization_when_user_opted_out(monkeypatch) -> None:
    expected = {
        "request_id": "req_1",
        "surface": "home",
        "items": [{"item_id": "A1", "title": "Example"}],
        "algorithm_version": "rec_v1",
        "ranking_version": "rank_v1",
        "snapshot": {"ok": True},
        "personalized": False,
    }

    def fake_service(**kwargs):
        assert kwargs["personalized"] is False
        return dict(expected)

    import src.api.routes_feed as routes_feed

    monkeypatch.setattr(routes_feed, "get_homepage_feed", fake_service)
    monkeypatch.setattr(routes_feed, "personalization_enabled_for_user", lambda *_args, **_kwargs: False)

    client = TestClient(create_app())
    response = client.get("/api/feed/home", params={"user_id_hash": "u_1", "session_id": "sess_1"})

    assert response.status_code == 200
    assert response.json()["personalized"] is False


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
    monkeypatch.setattr(routes_search, "personalization_enabled_for_user", lambda *_args, **_kwargs: True)
    client = TestClient(create_app())
    response = client.get(
        "/api/search",
        params={"user_id_hash": "u_2", "session_id": "sess_2", "q": "iphone case"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "req_search_1"
    assert payload["user_id_hash"] == "u_2"


def test_search_route_disables_personalization_when_user_opted_out(monkeypatch) -> None:
    expected = {
        "request_id": "req_search_1",
        "surface": "search",
        "items": [{"item_id": "A2"}],
        "query": {"raw_query": "iphone case"},
        "algorithm_version": "rec_v1",
        "ranking_version": "rank_v1",
        "snapshot": {"ok": True},
        "personalized": False,
    }

    def fake_service(**kwargs):
        assert kwargs["personalized"] is False
        return dict(expected)

    import src.api.routes_search as routes_search

    monkeypatch.setattr(routes_search, "personalized_search", fake_service)
    monkeypatch.setattr(routes_search, "personalization_enabled_for_user", lambda *_args, **_kwargs: False)

    client = TestClient(create_app())
    response = client.get(
        "/api/search",
        params={"user_id_hash": "u_2", "session_id": "sess_2", "q": "iphone case"},
    )

    assert response.status_code == 200
    assert response.json()["personalized"] is False


def test_items_route_returns_404_when_missing(monkeypatch) -> None:
    class FakeItemsCollection:
        def find_one(self, *_args, **_kwargs):
            return None

    import src.api.routes_items as routes_items

    monkeypatch.setattr(routes_items, "get_items_collection", lambda: FakeItemsCollection())
    client = TestClient(create_app())
    response = client.get("/api/items/does-not-exist")
    assert response.status_code == 404


def test_items_similar_route_disables_personalization_when_user_opted_out(monkeypatch) -> None:
    expected = {
        "request_id": "req_sim_1",
        "surface": "detail_similar",
        "source_item_id": "item_1",
        "items": [{"item_id": "item_2"}],
        "algorithm_version": "rec_v1",
        "ranking_version": "rank_v1",
        "snapshot": {"ok": True},
        "personalized": False,
    }

    def fake_service(**kwargs):
        assert kwargs["personalized"] is False
        return dict(expected)

    import src.api.routes_items as routes_items

    monkeypatch.setattr(routes_items, "get_similar_products", fake_service)
    monkeypatch.setattr(routes_items, "personalization_enabled_for_user", lambda *_args, **_kwargs: False)

    client = TestClient(create_app())
    response = client.get(
        "/api/items/item_1/similar",
        params={"user_id_hash": "u_3", "session_id": "sess_3"},
    )

    assert response.status_code == 200
    assert response.json()["personalized"] is False


def test_items_route_returns_clear_primary_image_and_product_text(monkeypatch) -> None:
    class FakeItemsCollection:
        def find_one(self, *_args, **_kwargs):
            return {
                "_id": "item_1",
                "title_en": "Test Product",
                "brand": "Brand",
                "source_category": "Electronics",
                "category_id": "electronics",
                "category_path": ["electronics"],
                "price_vnd": 199000,
                "price_bucket": "100k_300k",
                "image_url": "https://m.media-amazon.com/images/I/main._AC_SR38,50_.jpg",
                "image_urls": [
                    "https://m.media-amazon.com/images/I/main._AC_SR38,50_.jpg",
                    "https://m.media-amazon.com/images/I/main._AC_.jpg",
                    "https://m.media-amazon.com/images/I/gallery._AC_US40_.jpg",
                ],
                "quality_score": 0.8,
                "cold_start": {"is_cold_item": False, "interaction_count": 3},
                "description_enriched": {},
                "source_text": {
                    "description_text": "A useful charger.",
                    "features_text": "Fast charge\nCompact size",
                    "details_text": "USB-C",
                },
            }

    import src.api.routes_items as routes_items

    monkeypatch.setattr(routes_items, "get_items_collection", lambda: FakeItemsCollection())
    client = TestClient(create_app())
    response = client.get("/api/items/item_1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["image_url"].endswith("/main._AC_.jpg")
    assert payload["image_fallback_url"].endswith("/main._AC_SR38,50_.jpg")
    assert payload["image_urls"][-1].endswith("/gallery._AC_.jpg")
    assert payload["source_text"]["features_text"] == "Fast charge\nCompact size"


def test_events_route_delegates_to_logger(monkeypatch) -> None:
    called = {}

    def fake_log_clickstream_event(**kwargs):
        called.update(kwargs)
        return {"ok": True, "inserted": True, "event_id": "evt_1"}

    import src.api.routes_events as routes_events

    monkeypatch.setattr(routes_events, "log_clickstream_event", fake_log_clickstream_event)
    monkeypatch.setattr(routes_events, "clickstream_logging_enabled_for_user", lambda *_args, **_kwargs: True)
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


def test_events_route_skips_when_user_disables_clickstream_logging(monkeypatch) -> None:
    called = []

    import src.api.routes_events as routes_events

    monkeypatch.setattr(routes_events, "clickstream_logging_enabled_for_user", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(routes_events, "log_clickstream_event", lambda **kwargs: called.append(kwargs) or {"ok": True})

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
    assert response.json()["skipped"] is True
    assert response.json()["reason"] == "clickstream_logging_disabled"
    assert called == []


def test_events_route_rejects_invalid_surface_with_422(monkeypatch) -> None:
    import src.api.routes_events as routes_events

    monkeypatch.setattr(routes_events, "clickstream_logging_enabled_for_user", lambda *_args, **_kwargs: True)

    client = TestClient(create_app())
    response = client.post(
        "/api/events",
        json={
            "user_id_hash": "u_1",
            "session_id": "sess_1",
            "item_id": "A1",
            "event_type": "click",
            "surface": "checkout",
        },
    )

    assert response.status_code == 422


def test_events_route_returns_400_for_missing_request_id_on_home_click(monkeypatch) -> None:
    import src.api.routes_events as routes_events

    monkeypatch.setattr(routes_events, "clickstream_logging_enabled_for_user", lambda *_args, **_kwargs: True)

    client = TestClient(create_app())
    response = client.post(
        "/api/events",
        json={
            "user_id_hash": "u_1",
            "session_id": "sess_1",
            "item_id": "A1",
            "event_type": "click",
            "surface": "home",
        },
    )

    assert response.status_code == 400
    assert "request_id is required for home click events" in response.json()["detail"]


def test_events_route_allows_direct_detail_events_without_request_id(monkeypatch) -> None:
    called = {}

    def fake_log_clickstream_event(**kwargs):
        called.update(kwargs)
        return {"ok": True, "inserted": True, "event_id": "evt_detail_1"}

    import src.api.routes_events as routes_events

    monkeypatch.setattr(routes_events, "clickstream_logging_enabled_for_user", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(routes_events, "log_clickstream_event", fake_log_clickstream_event)

    client = TestClient(create_app())
    response = client.post(
        "/api/events",
        json={
            "user_id_hash": "u_1",
            "session_id": "sess_1",
            "item_id": "A1",
            "event_type": "view_detail",
            "surface": "detail",
            "dwell_time_ms": 1200,
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert called["surface"] == "detail"
    assert called["request_id"] is None


def test_debug_routes_require_admin_token(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    client = TestClient(create_app())
    response = client.get("/api/demo/status")

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "admin_token_required"


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

        def count_documents(self, filter_doc):
            if filter_doc.get("processed") == {"$ne": True}:
                return sum(1 for doc in self.docs if doc.get("processed") is not True)
            return len(self.docs)

    import src.api.routes_debug as routes_debug

    monkeypatch.setattr(routes_debug, "get_users_collection", lambda: FakeCollection([{"user_id_hash": "u_1"}]))
    monkeypatch.setattr(routes_debug, "get_user_profiles_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "profile_status": "warming", "updated_at": "2026-01-01T01:00:00+00:00"}]))
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "item_id": "A1", "updated_at": "2026-01-01T01:00:00+00:00"}]))
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "request_id": "req_1"}]))
    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: FakeCollection([{"user_id_hash": "u_1", "event_id": "evt_1", "timestamp": "2026-01-01T02:00:00+00:00", "processed": False}]))
    monkeypatch.setattr(routes_debug, "get_item_item_cf_edges_collection", lambda: FakeCollection([{"item_id": "A1", "neighbor_item_id": "A2"}]))

    client = _admin_client(monkeypatch)
    response = client.get("/api/debug/user/u_1", headers=_admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["profile_status"] == "warming"
    assert payload["signals"][0]["item_id"] == "A1"
    assert payload["freshness"]["state"] == "stale"
    assert payload["freshness"]["pending_event_count"] == 1
    assert payload["freshness"]["stale_components"] == ["signals", "profile"]
    assert payload["freshness"]["cf_built_at"] is None
    assert payload["freshness"]["model_versions"]["configured"]["signal_model_version"]
    assert payload["freshness"]["model_versions"]["stored"]["signal_model_version"] is None


def test_debug_version_snapshot_marks_profile_and_cf_stale_when_signal_lineage_is_old() -> None:
    import src.api.routes_debug as routes_debug

    configured_versions = routes_debug.configured_model_versions(routes_debug.get_settings())
    configured_signal_version = configured_versions["signal_model_version"]
    stale_signal_version = f"{configured_signal_version}__legacy"
    snapshot = routes_debug._model_versions_snapshot(
        profile_doc={
            "derivation": {
                "model_version": configured_versions["profile_model_version"],
                "source_signal_model_version": stale_signal_version,
            }
        },
        signals=[{"derivation": {"model_version": configured_signal_version}}],
        cf_edges=[
            {
                "derivation": {
                    "model_version": configured_versions["cf_model_version"],
                    "source_signal_model_version": stale_signal_version,
                }
            }
        ],
    )

    assert "profile" in snapshot["stale_version_components"]
    assert "cf" in snapshot["stale_version_components"]


def test_freshness_snapshot_marks_cf_refresh_required_when_signals_are_newer_than_graph() -> None:
    import src.api.routes_debug as routes_debug

    snapshot = routes_debug._freshness_snapshot(
        profile_doc={"updated_at": "2026-01-02T00:00:00+00:00"},
        signals=[
            {
                "updated_at": "2026-01-02T00:00:00+00:00",
                "derivation": {"built_at": "2026-01-02T00:00:00+00:00"},
            }
        ],
        events=[{"timestamp": "2026-01-01T00:00:00+00:00", "processed": True}],
        cf_edges=[],
        cf_lineage_docs=[
            {
                "updated_at": "2026-01-01T00:00:00+00:00",
                "derivation": {
                    "built_at": "2026-01-01T00:00:00+00:00",
                    "source_signal_built_at": "2026-01-01T00:00:00+00:00",
                    "input_policy": "current_supported",
                },
            }
        ],
        pending_event_count=0,
    )

    assert snapshot["components"]["cf"]["state"] == "refresh_required"
    assert snapshot["components"]["cf"]["input_policy"] == "current_supported"
    assert "cf" in snapshot["stale_components"]


def test_freshness_snapshot_does_not_report_cf_current_without_graph_watermark() -> None:
    import src.api.routes_debug as routes_debug

    snapshot = routes_debug._freshness_snapshot(
        profile_doc=None,
        signals=[],
        events=[],
        cf_edges=[],
        pending_event_count=0,
    )

    assert snapshot["components"]["cf"]["state"] == "unavailable"


def test_demo_reset_dry_run_reports_counts(monkeypatch) -> None:
    class FakeCollection:
        def __init__(self, count):
            self.count = count

        def count_documents(self, *_args, **_kwargs):
            return self.count

        def delete_many(self, *_args, **_kwargs):
            raise AssertionError("delete_many should not be called in dry-run")

    class FakeDatabase:
        def __getitem__(self, name):
            return FakeCollection(11 if name == "clickstream_events" else 12)

    import src.api.routes_debug as routes_debug

    monkeypatch.setattr(routes_debug, "get_database", lambda: FakeDatabase())
    client = _admin_client(monkeypatch)
    response = client.post("/api/demo/reset", headers=_admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "dry-run"
    assert {target["collection"] for target in payload["targets"]} == {
        "recommendation_logs",
        "clickstream_events",
        "user_item_signals",
        "user_profiles",
        "item_stats",
    }
    assert any("build_user_item_signals.py --write --rebuild-item-stats" in step for step in payload["rebuild_order"])
    assert payload["protected_collections"] == ["items", "retrieval_units"]


def test_demo_reset_write_requires_confirmation(monkeypatch) -> None:
    class FakeCollection:
        def __init__(self, count):
            self.count = count

        def count_documents(self, *_args, **_kwargs):
            return self.count

        def delete_many(self, *_args, **_kwargs):
            raise AssertionError("delete_many should not be called without confirmation")

    import src.api.routes_debug as routes_debug

    monkeypatch.setattr(routes_debug, "get_database", lambda: {"clickstream_events": FakeCollection(11)})

    client = _admin_client(monkeypatch)
    response = client.post("/api/demo/reset?write=true", headers=_admin_headers())
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "confirmation_required"
    assert detail["expected_confirm"] == "DEMO_RESET"


def test_demo_reset_write_clears_catalog_cache(monkeypatch) -> None:
    import src.api.routes_debug as routes_debug

    cache_clears = []

    monkeypatch.setattr(routes_debug, "get_database", lambda: object())
    monkeypatch.setattr(
        routes_debug,
        "execute_reset",
        lambda *_args, **_kwargs: {"mode": "write", "deleted": {"item_stats": 4}},
    )
    monkeypatch.setattr(routes_debug, "clear_catalog_snapshot_cache", lambda: cache_clears.append(True))

    client = _admin_client(monkeypatch)
    response = client.post("/api/demo/reset?write=true&confirm=DEMO_RESET", headers=_admin_headers())

    assert response.status_code == 200
    assert response.json()["mode"] == "write"
    assert cache_clears == [True]


def test_demo_seed_write_requires_confirmation(monkeypatch) -> None:
    import src.api.routes_debug as routes_debug

    def fail_load_candidates(**_kwargs):
        raise AssertionError("seed plan should not be built without confirmation")

    monkeypatch.setattr(routes_debug, "load_candidates_from_collections", fail_load_candidates)

    client = _admin_client(monkeypatch)
    response = client.post("/api/demo/seed?write=true", headers=_admin_headers())

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "confirmation_required"
    assert detail["expected_confirm"] == "SEED_DEMO_BEHAVIOR"


def test_demo_status_reports_counts_and_protected_collections(monkeypatch) -> None:
    class FakeCollection:
        def __init__(self, count):
            self.count = count

        def count_documents(self, *_args, **_kwargs):
            return self.count

    import src.api.routes_debug as routes_debug

    monkeypatch.setattr(routes_debug, "get_users_collection", lambda: FakeCollection(2))
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection", lambda: FakeCollection(3))
    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: FakeCollection(4))
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: FakeCollection(5))
    monkeypatch.setattr(routes_debug, "get_user_profiles_collection", lambda: FakeCollection(6))
    monkeypatch.setattr(routes_debug, "get_item_stats_collection", lambda: FakeCollection(7))
    monkeypatch.setattr(routes_debug, "get_item_item_cf_edges_collection", lambda: FakeCollection(8))
    monkeypatch.setattr(routes_debug, "get_item_hype_profiles_collection", lambda: FakeCollection(9))
    monkeypatch.setattr(routes_debug, "get_item_semantic_neighbors_collection", lambda: FakeCollection(10))
    monkeypatch.setattr(routes_debug, "get_synthetic_personas_collection", lambda: FakeCollection(11))

    client = _admin_client(monkeypatch)
    response = client.get("/api/demo/status", headers=_admin_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["item_item_cf_edges"] == 8
    assert payload["cf_evidence_available"] is True
    assert payload["protected_collections"] == ["items", "retrieval_units"]
    assert "seeded/precomputed synthetic behavior" in payload["precomputed_cf_note"]


@pytest.mark.parametrize(
    ("path", "expected_confirm"),
    [
        ("/api/debug/process-events?write=true", "PROCESS_EVENTS_WRITE"),
        ("/api/debug/apply-pending-behavior?write=true", "APPLY_PENDING_BEHAVIOR_WRITE"),
        ("/api/debug/rebuild-profiles?write=true", "REBUILD_PROFILES_WRITE"),
        ("/api/debug/rebuild-cf?write=true", "REBUILD_CF_WRITE"),
    ],
)
def test_debug_write_endpoints_require_confirmation(monkeypatch, path: str, expected_confirm: str) -> None:
    client = _admin_client(monkeypatch)
    response = client.post(path, headers=_admin_headers())

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "confirmation_required"
    assert detail["expected_confirm"] == expected_confirm


def test_process_events_full_write_without_limit_clears_catalog_cache(monkeypatch) -> None:
    import src.api.routes_debug as routes_debug

    sentinel = object()
    build_calls = []
    cache_clears = []

    class FakeEventsCollection:
        def count_documents(self, *_args, **_kwargs):
            return 25

    events_collection = FakeEventsCollection()

    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: events_collection)
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_item_stats_collection", lambda: sentinel)
    monkeypatch.setattr(
        routes_debug,
        "build_user_item_signals",
        lambda **kwargs: build_calls.append(kwargs) or {"ok": True},
    )
    monkeypatch.setattr(routes_debug, "clear_catalog_snapshot_cache", lambda: cache_clears.append(True))

    client = _admin_client(monkeypatch)
    response = client.post(
        "/api/debug/process-events?rebuild_item_stats=true&write=true&confirm=PROCESS_EVENTS_WRITE",
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert build_calls[0]["limit_events"] is None
    assert build_calls[0]["write"] is True
    assert build_calls[0]["item_stats_collection"] is sentinel
    assert cache_clears == [True]


def test_process_events_rejects_any_limited_write_before_building_derived_data(monkeypatch) -> None:
    import src.api.routes_debug as routes_debug

    build_calls = []

    class FakeEventsCollection:
        def count_documents(self, *_args, **_kwargs):
            return 26

    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: FakeEventsCollection())
    monkeypatch.setattr(
        routes_debug,
        "build_user_item_signals",
        lambda **kwargs: build_calls.append(kwargs) or {"ok": True},
    )

    client = _admin_client(monkeypatch)
    response = client.post(
        "/api/debug/process-events?limit=26&rebuild_item_stats=true&write=true&confirm=PROCESS_EVENTS_WRITE",
        headers=_admin_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "partial_signal_write_blocked"
    assert build_calls == []


def test_apply_pending_behavior_delegates_to_incremental_processor_and_clears_stats_cache(monkeypatch) -> None:
    import src.api.routes_debug as routes_debug

    sentinel = object()
    calls = []
    cache_clears = []

    monkeypatch.setattr(routes_debug, "get_clickstream_events_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_recommendation_logs_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_item_stats_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_user_profiles_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_item_hype_profiles_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_items_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_retrieval_units_collection", lambda: sentinel)
    monkeypatch.setattr(
        routes_debug,
        "process_pending_behavior",
        lambda **kwargs: calls.append(kwargs) or {
            "ok": True,
            "processing_mode": "incremental_pending",
            "cf_refresh_required": True,
        },
    )
    monkeypatch.setattr(routes_debug, "clear_catalog_snapshot_cache", lambda: cache_clears.append(True))

    client = _admin_client(monkeypatch)
    response = client.post(
        "/api/debug/apply-pending-behavior?max_events=40&rebuild_item_stats=true&write=true&confirm=APPLY_PENDING_BEHAVIOR_WRITE",
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    assert response.json()["processing_mode"] == "incremental_pending"
    assert calls[0]["max_events"] == 40
    assert calls[0]["write"] is True
    assert calls[0]["user_profiles_collection"] is sentinel
    assert cache_clears == [True]


def test_rebuild_cf_replaces_existing_edges_only_for_full_write(monkeypatch) -> None:
    import src.api.routes_debug as routes_debug

    sentinel = object()
    build_calls = []

    monkeypatch.setattr(routes_debug, "get_user_item_signals_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_items_collection", lambda: sentinel)
    monkeypatch.setattr(routes_debug, "get_item_item_cf_edges_collection", lambda: sentinel)
    monkeypatch.setattr(
        routes_debug,
        "build_item_item_cf_edges",
        lambda **kwargs: build_calls.append(kwargs) or {"ok": True},
    )

    client = _admin_client(monkeypatch)
    full_response = client.post("/api/debug/rebuild-cf?write=true&confirm=REBUILD_CF_WRITE", headers=_admin_headers())
    limited_response = client.post(
        "/api/debug/rebuild-cf?write=true&limit_users=5&confirm=REBUILD_CF_WRITE",
        headers=_admin_headers(),
    )

    assert full_response.status_code == 200
    assert limited_response.status_code == 400
    assert build_calls[0]["replace_existing"] is True
    assert len(build_calls) == 1
    assert limited_response.json()["detail"]["error"] == "partial_cf_write_blocked"


def test_rebuild_profiles_rejects_limited_write(monkeypatch) -> None:
    import src.api.routes_debug as routes_debug

    build_calls = []
    monkeypatch.setattr(
        routes_debug,
        "build_user_profiles",
        lambda **kwargs: build_calls.append(kwargs) or {"ok": True},
    )

    client = _admin_client(monkeypatch)
    response = client.post(
        "/api/debug/rebuild-profiles?write=true&limit_users=5&confirm=REBUILD_PROFILES_WRITE",
        headers=_admin_headers(),
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "partial_profile_write_blocked"
    assert build_calls == []
