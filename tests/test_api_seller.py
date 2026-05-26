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
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.insert_one_calls = []
        self.insert_many_calls = []
        self.update_one_calls = []
        self.delete_many_calls = []

    def insert_one(self, doc):
        self.insert_one_calls.append(dict(doc))
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("_id") or doc.get("draft_id"))

    def insert_many(self, docs, ordered=True):
        docs = [dict(doc) for doc in docs]
        self.insert_many_calls.append((docs, ordered))
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

    def delete_many(self, *_args, **_kwargs):
        self.delete_many_calls.append((_args, _kwargs))
        raise AssertionError("delete_many is forbidden for seller API")


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
