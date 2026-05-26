from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.api import routes_seller
from src.api.app import app


class FakeCursor(list):
    def sort(self, *_args):
        return self

    def limit(self, value):
        return FakeCursor(self[:value])


class FakeCollection:
    def __init__(self, docs=None, *, fail_insert_many: bool = False):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.insert_one_calls = []
        self.insert_many_calls = []
        self.update_one_calls = []
        self.delete_one_calls = []
        self.delete_many_calls = []
        self.fail_insert_many = fail_insert_many

    def insert_one(self, doc):
        self.insert_one_calls.append(dict(doc))
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("_id") or doc.get("draft_id"))

    def insert_many(self, docs, ordered=True):
        docs = [dict(doc) for doc in docs]
        self.insert_many_calls.append((docs, ordered))
        if self.fail_insert_many:
            raise RuntimeError("insert_many failed")
        self.docs.extend(docs)
        return SimpleNamespace(inserted_ids=[doc.get("_id") for doc in docs])

    def update_one(self, filter_doc, update_doc):
        self.update_one_calls.append((dict(filter_doc), dict(update_doc)))
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                for key, value in update_doc.get("$set", {}).items():
                    if "." in key:
                        root, leaf = key.split(".", 1)
                        doc.setdefault(root, {})[leaf] = value
                    else:
                        doc[key] = value
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

    def count_documents(self, filter_doc):
        return sum(1 for doc in self.docs if all(doc.get(key) == value for key, value in filter_doc.items()))

    def delete_one(self, filter_doc):
        self.delete_one_calls.append(dict(filter_doc))
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def delete_many(self, filter_doc):
        self.delete_many_calls.append(dict(filter_doc))
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not all(doc.get(key) == value for key, value in filter_doc.items())]
        return SimpleNamespace(deleted_count=before - len(self.docs))


def _settings(enabled=True):
    return SimpleNamespace(
        enable_seller_tools=enabled,
        seller_index_confirmation="INDEX_SELLER_DRAFT",
        seller_draft_max_preview_units=20,
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
    }


def _install(monkeypatch, *, enabled=True):
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("ENABLE_SELLER_TOOLS", "true" if enabled else "false")
    drafts = FakeCollection()
    items = FakeCollection()
    retrieval_units = FakeCollection()
    monkeypatch.setattr(routes_seller, "get_settings", lambda: _settings(enabled))
    monkeypatch.setattr(routes_seller, "get_seller_product_drafts_collection", lambda: drafts)
    monkeypatch.setattr(routes_seller, "get_items_collection", lambda: items)
    monkeypatch.setattr(routes_seller, "get_retrieval_units_collection", lambda: retrieval_units)
    return drafts, items, retrieval_units


def test_seller_tools_disabled_returns_readable_state(monkeypatch) -> None:
    _install(monkeypatch, enabled=False)
    client = TestClient(app)

    response = client.get("/api/seller/drafts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["drafts"] == []


def test_create_validate_preview_write_only_staging(monkeypatch) -> None:
    drafts, items, retrieval_units = _install(monkeypatch, enabled=True)
    client = TestClient(app)

    create_response = client.post("/api/seller/drafts", json=_payload())
    assert create_response.status_code == 200
    draft = create_response.json()["draft"]
    validate_response = client.post(f"/api/seller/drafts/{draft['draft_id']}/validate")
    preview_response = client.post(f"/api/seller/drafts/{draft['draft_id']}/index-preview")

    assert validate_response.status_code == 200
    assert preview_response.status_code == 200
    assert preview_response.json()["catalog_write_performed"] is False
    assert len(drafts.insert_one_calls) == 1
    assert drafts.update_one_calls
    assert items.insert_one_calls == []
    assert retrieval_units.insert_many_calls == []


def test_approve_index_requires_write_and_confirm(monkeypatch) -> None:
    drafts, items, retrieval_units = _install(monkeypatch, enabled=True)
    client = TestClient(app)
    draft = client.post("/api/seller/drafts", json=_payload()).json()["draft"]
    client.post(f"/api/seller/drafts/{draft['draft_id']}/index-preview")

    missing_write = client.post(f"/api/seller/drafts/{draft['draft_id']}/approve-index")
    wrong_confirm = client.post(f"/api/seller/drafts/{draft['draft_id']}/approve-index?write=true&confirm=WRONG")

    assert missing_write.status_code == 403
    assert wrong_confirm.status_code == 403
    assert items.insert_one_calls == []
    assert retrieval_units.insert_many_calls == []


def test_approve_index_requires_persisted_preview_before_catalog_write(monkeypatch) -> None:
    drafts, items, retrieval_units = _install(monkeypatch, enabled=True)
    client = TestClient(app)
    draft = client.post("/api/seller/drafts", json=_payload()).json()["draft"]

    response = client.post(
        f"/api/seller/drafts/{draft['draft_id']}/approve-index?write=true&confirm=INDEX_SELLER_DRAFT"
    )

    assert response.status_code == 400
    assert "previewed before approve-index" in response.text
    assert items.insert_one_calls == []
    assert retrieval_units.insert_many_calls == []


def test_approve_index_with_confirm_additively_writes_catalog(monkeypatch) -> None:
    drafts, items, retrieval_units = _install(monkeypatch, enabled=True)
    client = TestClient(app)
    draft = client.post("/api/seller/drafts", json=_payload()).json()["draft"]
    client.post(f"/api/seller/drafts/{draft['draft_id']}/index-preview")

    response = client.post(
        f"/api/seller/drafts/{draft['draft_id']}/approve-index?write=true&confirm=INDEX_SELLER_DRAFT"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["write_performed"] is True
    assert body["inserted_items"] == 1
    assert body["inserted_retrieval_units"] >= 2
    assert len(items.insert_one_calls) == 1
    assert len(retrieval_units.insert_many_calls) == 1
    assert drafts.delete_many_calls == []
    assert items.delete_many_calls == []
    assert retrieval_units.delete_many_calls == []


def test_approve_index_refuses_existing_item_collision(monkeypatch) -> None:
    drafts, items, retrieval_units = _install(monkeypatch, enabled=True)
    client = TestClient(app)
    draft = client.post("/api/seller/drafts", json=_payload()).json()["draft"]
    client.post(f"/api/seller/drafts/{draft['draft_id']}/index-preview")
    items.docs.append({"_id": draft["proposed_item_id"]})

    response = client.post(
        f"/api/seller/drafts/{draft['draft_id']}/approve-index?write=true&confirm=INDEX_SELLER_DRAFT"
    )

    assert response.status_code == 400
    assert "item already exists" in response.text
    assert retrieval_units.insert_many_calls == []


def test_seller_routes_require_token_when_tools_enabled(monkeypatch) -> None:
    _install(monkeypatch, enabled=True)
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("SELLER_TOKEN", "seller-token")
    client = TestClient(app)

    unauthorized = client.post("/api/seller/drafts", json=_payload())
    authorized = client.post(
        "/api/seller/drafts",
        json=_payload(),
        headers={"Authorization": "Bearer seller-token"},
    )

    assert unauthorized.status_code == 403
    assert authorized.status_code == 200


def test_seller_token_is_scoped_to_demo_seller_id(monkeypatch) -> None:
    drafts, _items, _retrieval_units = _install(monkeypatch, enabled=True)
    drafts.insert_one({
        "draft_id": "draft_foreign",
        "seller_id": "seller_other_999",
        "title": "Foreign draft",
        "description": "Foreign seller draft for isolation testing.",
        "status": "validated",
        "validation_errors": [],
        "validation_warnings": [],
        "proposed_item_id": "seller_other_foreign_item",
        "indexing_preview": None,
        "enrichment": {"status": "none", "latest_request_id": None, "applied_request_ids": [], "applied_fields": [], "source_urls": []},
    })
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("SELLER_TOKEN", "seller-token")
    client = TestClient(app)

    create_for_other = client.post(
        "/api/seller/drafts",
        json={**_payload(), "seller_id": "seller_other_999"},
        headers={"Authorization": "Bearer seller-token"},
    )
    foreign_get = client.get("/api/seller/drafts/draft_foreign", headers={"Authorization": "Bearer seller-token"})
    scoped_list = client.get("/api/seller/drafts", headers={"Authorization": "Bearer seller-token"})

    assert create_for_other.status_code == 403
    assert foreign_get.status_code == 403
    assert all(draft["seller_id"] == "seller_demo_001" for draft in scoped_list.json()["drafts"])


def test_approve_index_rolls_back_item_when_retrieval_insert_fails(monkeypatch) -> None:
    drafts, items, _retrieval_units = _install(monkeypatch, enabled=True)
    failing_retrieval_units = FakeCollection(fail_insert_many=True)
    monkeypatch.setattr(routes_seller, "get_retrieval_units_collection", lambda: failing_retrieval_units)
    client = TestClient(app, raise_server_exceptions=False)
    draft = client.post("/api/seller/drafts", json=_payload()).json()["draft"]
    client.post(f"/api/seller/drafts/{draft['draft_id']}/index-preview")

    response = client.post(
        f"/api/seller/drafts/{draft['draft_id']}/approve-index?write=true&confirm=INDEX_SELLER_DRAFT"
    )

    assert response.status_code == 500
    assert items.find_one({"_id": draft["proposed_item_id"]}) is None
    assert items.delete_one_calls == [{"_id": draft["proposed_item_id"]}]
    assert drafts.find_one({"draft_id": draft["draft_id"]})["status"] == "failed"
