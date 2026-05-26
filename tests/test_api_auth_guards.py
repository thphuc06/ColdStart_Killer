from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app


class FakeItemsCollection:
    def find_one(self, *_args, **_kwargs):
        return {
            "_id": "item_1",
            "title_en": "Demo Item",
            "brand": "DemoBrand",
            "category_id": "All Beauty",
            "source_category": "All Beauty",
            "category_path": ["All Beauty"],
            "price_vnd": 100000,
            "price_bucket": "budget",
            "cold_start": {"is_cold_item": True, "interaction_count": 0},
        }


def _public_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    return TestClient(create_app())


def test_public_search_feed_and_item_detail_do_not_require_token(monkeypatch) -> None:
    import src.api.routes_feed as routes_feed
    import src.api.routes_items as routes_items
    import src.api.routes_search as routes_search

    monkeypatch.setattr(routes_search, "personalization_enabled_for_user", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(routes_search, "personalized_search", lambda **_kwargs: {"ok": True, "results": []})
    monkeypatch.setattr(routes_feed, "personalization_enabled_for_user", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(routes_feed, "get_homepage_feed", lambda **_kwargs: {"ok": True, "items": []})
    monkeypatch.setattr(routes_items, "get_items_collection", lambda: FakeItemsCollection())
    client = _public_client(monkeypatch)

    search = client.get("/api/search?user_id_hash=u_1&session_id=s_1&q=sunscreen")
    feed = client.get("/api/feed/home?user_id_hash=u_1&session_id=s_1")
    item = client.get("/api/items/item_1")

    assert search.status_code == 200
    assert feed.status_code == 200
    assert item.status_code == 200


def test_debug_routes_require_admin_token_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    client = TestClient(create_app())

    response = client.get("/api/demo/status")

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "admin_token_required"


def test_debug_routes_return_config_error_when_admin_token_missing(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "")
    client = TestClient(create_app())

    response = client.get("/api/demo/status")

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "admin_token_not_configured"


def test_seller_approve_index_requires_auth_before_write(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("ENABLE_SELLER_TOOLS", "true")
    client = TestClient(create_app())

    response = client.post("/api/seller/drafts/draft_1/approve-index?write=true&confirm=INDEX_SELLER_DRAFT")

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "seller_or_admin_token_required"


def test_enrichment_request_and_apply_require_auth(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("ENABLE_SELLER_TOOLS", "true")
    monkeypatch.setenv("ENABLE_WEB_ENRICHMENT", "true")
    client = TestClient(create_app())

    request_response = client.post("/api/enrichment/seller-drafts/draft_1/request")
    apply_response = client.post(
        "/api/enrichment/requests/enrich_1/apply?confirm=APPLY_WEB_ENRICHMENT",
        json={"fields_to_apply": ["description"]},
    )

    assert request_response.status_code == 403
    assert request_response.json()["detail"]["error"] == "seller_or_admin_token_required"
    assert apply_response.status_code == 403
    assert apply_response.json()["detail"]["error"] == "seller_or_admin_token_required"


def test_job_trigger_requires_admin_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("ENABLE_JOB_TRIGGER_API", "true")
    client = TestClient(create_app())

    response = client.post(
        "/api/jobs/run",
        json={"job_type": "fusion_comparison_dry_run", "dry_run": True, "params": {}},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "admin_token_required"

