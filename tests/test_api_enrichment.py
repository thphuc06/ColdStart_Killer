from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.api import routes_enrichment
from src.api import routes_seller
from src.api.app import create_app
from src.enrichment.schemas import WebSearchResult
from src.seller.drafts import create_seller_draft


class FakeCursor(list):
    def sort(self, *_args):
        return self

    def limit(self, value):
        return FakeCursor(self[:value])


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.insert_one_calls = []
        self.update_one_calls = []
        self.insert_many_calls = []
        self.delete_many_calls = []

    def insert_one(self, doc):
        self.insert_one_calls.append(dict(doc))
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("request_id") or doc.get("draft_id"))

    def insert_many(self, *_args, **_kwargs):
        self.insert_many_calls.append((_args, _kwargs))
        raise AssertionError("enrichment API must not insert catalog docs")

    def update_one(self, filter_doc, update_doc):
        self.update_one_calls.append((dict(filter_doc), dict(update_doc)))
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                for key, value in update_doc.get("$set", {}).items():
                    _set_path(doc, key, value)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def find_one(self, filter_doc, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                return dict(doc)
        return None

    def find(self, filter_doc=None):
        filter_doc = filter_doc or {}
        return FakeCursor([dict(doc) for doc in self.docs if all(doc.get(key) == value for key, value in filter_doc.items())])

    def delete_many(self, *_args, **_kwargs):
        self.delete_many_calls.append((_args, _kwargs))
        raise AssertionError("enrichment API must not delete docs")


def _set_path(doc, key, value):
    current = doc
    parts = key.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


class FakeProvider:
    name = "fake_provider"

    def search(self, query: str, *, max_results: int):
        return [
            WebSearchResult(
                title="Demo enriched result",
                url="https://example.test/enrichment",
                snippet="External evidence snippet for the draft product.",
                score=0.7,
                source="fake_provider",
            )
        ]


def _settings(*, seller_enabled=True, enrichment_enabled=True, key="test-key"):
    return SimpleNamespace(
        enable_seller_tools=seller_enabled,
        enable_web_enrichment=enrichment_enabled,
        web_enrichment_provider="tavily",
        tavily_api_key=key,
        tavily_max_results=3,
        web_enrichment_max_queries=3,
        web_enrichment_timeout_seconds=10,
        web_enrichment_apply_confirmation="APPLY_WEB_ENRICHMENT",
        seller_index_confirmation="INDEX_SELLER_DRAFT",
        seller_draft_max_preview_units=20,
        ollama_model="qwen3:8b",
        cors_allow_origins="http://localhost:5173",
        algorithm_version="test_algo",
        ranking_version="test_rank",
    )


def _payload():
    return {
        "seller_id": "seller_demo_001",
        "title": "Seller Sunscreen",
        "description": "Lightweight daily sunscreen for oily skin with comfortable finish.",
        "brand": "DemoSun",
        "category_id": "All Beauty",
        "price_vnd": 299000,
        "price_bucket": "100k_300k",
        "image_url": "https://example.test/sunscreen.jpg",
        "attributes": {"spf": "50"},
        "features": ["SPF 50"],
    }


def _install(monkeypatch, *, seller_enabled=True, enrichment_enabled=True, key="test-key"):
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("ENABLE_SELLER_TOOLS", "true" if seller_enabled else "false")
    monkeypatch.setenv("ENABLE_WEB_ENRICHMENT", "true" if enrichment_enabled else "false")
    drafts = FakeCollection()
    requests = FakeCollection()
    previews = FakeCollection()
    settings = _settings(seller_enabled=seller_enabled, enrichment_enabled=enrichment_enabled, key=key)
    draft = create_seller_draft(_payload(), drafts_collection=drafts, settings=settings)["draft"]
    monkeypatch.setattr(routes_enrichment, "get_settings", lambda: settings)
    monkeypatch.setattr(routes_enrichment, "get_seller_product_drafts_collection", lambda: drafts)
    monkeypatch.setattr(routes_enrichment, "get_web_enrichment_requests_collection", lambda: requests)
    monkeypatch.setattr(routes_enrichment, "get_seller_indexing_previews_collection", lambda: previews)
    monkeypatch.setattr(
        "src.enrichment.service.call_qwen",
        lambda prompt, **_kwargs: (
            '{"queries":[{"purpose":"identity","query":"DemoSun Seller Sunscreen"}]}'
            if "plan web searches" in prompt
            else '{"enriched_description":"Sourced sunscreen description.","key_facts":[],'
            '"quality":"medium","unsupported_claims":[]}'
        ),
    )
    return drafts, requests, draft


def test_preview_disabled_returns_state_without_writes(monkeypatch) -> None:
    _drafts, requests, draft = _install(monkeypatch, enrichment_enabled=False)
    client = TestClient(create_app())

    response = client.post(f"/api/enrichment/seller-drafts/{draft['draft_id']}/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert requests.insert_one_calls == []


def test_missing_key_returns_provider_not_configured_without_crash(monkeypatch) -> None:
    _drafts, requests, draft = _install(monkeypatch, key="")
    client = TestClient(create_app())

    response = client.post(f"/api/enrichment/seller-drafts/{draft['draft_id']}/request?wait=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "provider_not_configured"
    assert requests.insert_one_calls == []


def test_request_stores_enrichment_request_not_catalog(monkeypatch) -> None:
    drafts, requests, draft = _install(monkeypatch)
    import src.enrichment.service as service

    monkeypatch.setattr(service, "build_provider", lambda _settings: FakeProvider())
    client = TestClient(create_app())

    response = client.post(f"/api/enrichment/seller-drafts/{draft['draft_id']}/request?wait=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["catalog_write_performed"] is False
    assert len(requests.insert_one_calls) == 1
    assert drafts.update_one_calls[-1][1]["$set"]["enrichment.status"] == "available"


def test_apply_requires_confirmation(monkeypatch) -> None:
    _drafts, requests, draft = _install(monkeypatch)
    import src.enrichment.service as service

    monkeypatch.setattr(service, "build_provider", lambda _settings: FakeProvider())
    client = TestClient(create_app())
    request = client.post(f"/api/enrichment/seller-drafts/{draft['draft_id']}/request?wait=true").json()["request"]

    response = client.post(
        f"/api/enrichment/requests/{request['request_id']}/apply?confirm=WRONG",
        json={"fields_to_apply": ["description"]},
    )

    assert response.status_code == 403


def test_apply_with_confirm_updates_only_draft_and_request(monkeypatch) -> None:
    drafts, requests, draft = _install(monkeypatch)
    import src.enrichment.service as service

    monkeypatch.setattr(service, "build_provider", lambda _settings: FakeProvider())
    client = TestClient(create_app())
    request = client.post(f"/api/enrichment/seller-drafts/{draft['draft_id']}/request?wait=true").json()["request"]

    response = client.post(
        f"/api/enrichment/requests/{request['request_id']}/apply?confirm=APPLY_WEB_ENRICHMENT",
        json={"fields_to_apply": ["description"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["catalog_write_performed"] is False
    assert body["applied_fields"] == ["description"]
    assert drafts.find_one({"draft_id": draft["draft_id"]})["description"] == request["suggested_fields"]["description"]["value"]
    assert requests.find_one({"request_id": request["request_id"]})["status"] == "applied"


def test_request_requires_token_when_seller_tools_enabled(monkeypatch) -> None:
    _drafts, requests, draft = _install(monkeypatch)
    import src.enrichment.service as service

    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("SELLER_TOKEN", "seller-token")
    monkeypatch.setattr(service, "build_provider", lambda _settings: FakeProvider())
    client = TestClient(create_app())

    unauthorized = client.post(f"/api/enrichment/seller-drafts/{draft['draft_id']}/request")
    authorized = client.post(
        f"/api/enrichment/seller-drafts/{draft['draft_id']}/request?wait=true",
        headers={"Authorization": "Bearer seller-token"},
    )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200
    assert len(requests.insert_one_calls) == 1


def test_apply_returns_disabled_when_web_enrichment_feature_is_off(monkeypatch) -> None:
    drafts, requests, draft = _install(monkeypatch, enrichment_enabled=False)
    requests.insert_one(
        {
            "request_id": "enrich_existing",
            "draft_id": draft["draft_id"],
            "seller_id": draft["seller_id"],
            "provider": "fake_provider",
            "query": "demo query",
            "status": "completed",
            "results": [{"title": "Result", "url": "https://example.test/enrichment", "snippet": "snippet", "score": 0.7, "source": "fake_provider"}],
            "suggested_fields": {
                "description": {
                    "value": "Updated description",
                    "confidence": 0.7,
                    "source_urls": ["https://example.test/enrichment"],
                    "reason": "demo",
                }
            },
            "applied_fields": [],
            "created_at": "2026-05-27T00:00:00+00:00",
            "updated_at": "2026-05-27T00:00:00+00:00",
            "error": None,
        }
    )
    client = TestClient(create_app())

    response = client.post(
        "/api/enrichment/requests/enrich_existing/apply?confirm=APPLY_WEB_ENRICHMENT",
        json={"fields_to_apply": ["description"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["status"] == "disabled"
    assert drafts.find_one({"draft_id": draft["draft_id"]})["description"] == draft["description"]


def test_seller_token_cannot_access_foreign_enrichment_request(monkeypatch) -> None:
    _drafts, requests, _draft = _install(monkeypatch)
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("SELLER_TOKEN", "seller-token")
    requests.insert_one(
        {
            "request_id": "enrich_foreign",
            "draft_id": "draft_foreign",
            "seller_id": "seller_other_999",
            "provider": "fake_provider",
            "query": "demo query",
            "status": "completed",
            "results": [],
            "suggested_fields": {},
            "applied_fields": [],
            "created_at": "2026-05-27T00:00:00+00:00",
            "updated_at": "2026-05-27T00:00:00+00:00",
            "error": None,
        }
    )
    client = TestClient(create_app())

    response = client.get(
        "/api/enrichment/requests/enrich_foreign",
        headers={"Authorization": "Bearer seller-token"},
    )

    assert response.status_code == 403


def test_protected_full_seller_enrichment_flow_with_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("SELLER_TOKEN", "seller-token")
    monkeypatch.setenv("ENABLE_SELLER_TOOLS", "true")
    monkeypatch.setenv("ENABLE_WEB_ENRICHMENT", "true")

    drafts = FakeCollection()
    requests = FakeCollection()
    items = FakeCollection()
    retrieval_units = FakeCollection()
    settings = _settings(seller_enabled=True, enrichment_enabled=True, key="test-key")

    monkeypatch.setattr(routes_enrichment, "get_settings", lambda: settings)
    monkeypatch.setattr(routes_enrichment, "get_seller_product_drafts_collection", lambda: drafts)
    monkeypatch.setattr(routes_enrichment, "get_web_enrichment_requests_collection", lambda: requests)
    monkeypatch.setattr(routes_enrichment, "get_seller_indexing_previews_collection", lambda: FakeCollection())
    monkeypatch.setattr(routes_seller, "get_settings", lambda: settings)
    monkeypatch.setattr(routes_seller, "get_seller_product_drafts_collection", lambda: drafts)
    monkeypatch.setattr(routes_seller, "get_items_collection", lambda: items)
    monkeypatch.setattr(routes_seller, "get_retrieval_units_collection", lambda: retrieval_units)

    import src.enrichment.service as service

    monkeypatch.setattr(service, "build_provider", lambda _settings: FakeProvider())
    monkeypatch.setattr(
        service,
        "call_qwen",
        lambda prompt, **_kwargs: (
            '{"queries":[{"purpose":"identity","query":"DemoSun Seller Sunscreen"}]}'
            if "plan web searches" in prompt
            else '{"enriched_description":"Sourced sunscreen description.","key_facts":[],'
            '"quality":"medium","unsupported_claims":[]}'
        ),
    )
    client = TestClient(create_app())
    headers = {"Authorization": "Bearer seller-token"}

    create_response = client.post("/api/seller/drafts", json=_payload(), headers=headers)
    assert create_response.status_code == 200
    draft_id = create_response.json()["draft"]["draft_id"]

    preview_response = client.post(f"/api/enrichment/seller-drafts/{draft_id}/preview", headers=headers)
    assert preview_response.status_code == 200
    assert preview_response.json()["status"] in {"ready", "provider_not_configured"}

    request_response = client.post(f"/api/enrichment/seller-drafts/{draft_id}/request?wait=true", headers=headers)
    assert request_response.status_code == 200
    request_payload = request_response.json()
    assert request_payload["status"] == "completed"
    request_id = request_payload["request"]["request_id"]

    apply_response = client.post(
        f"/api/enrichment/requests/{request_id}/apply?confirm=APPLY_WEB_ENRICHMENT",
        json={"fields_to_apply": ["description"]},
        headers=headers,
    )

    assert apply_response.status_code == 200
    body = apply_response.json()
    assert body["status"] == "applied"
    assert body["catalog_write_performed"] is False
    assert requests.find_one({"request_id": request_id})["status"] == "applied"
    assert drafts.find_one({"draft_id": draft_id})["enrichment"]["status"] == "applied"
    assert items.insert_one_calls == []
    assert retrieval_units.insert_many_calls == []
