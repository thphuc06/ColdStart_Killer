from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.seller.drafts import build_proposed_item_id, create_seller_draft, validate_seller_draft
from src.seller.indexing_preview import approve_and_index_seller_draft, preview_seller_draft_indexing


class FakeInsertResult:
    inserted_id = "inserted"


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.insert_one_calls = []
        self.insert_many_calls = []
        self.update_one_calls = []
        self.delete_calls = []

    def insert_one(self, doc):
        self.insert_one_calls.append(dict(doc))
        self.docs.append(dict(doc))
        return FakeInsertResult()

    def insert_many(self, docs, ordered=True):
        self.insert_many_calls.append((list(docs), ordered))
        self.docs.extend(dict(doc) for doc in docs)
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
        return [dict(doc) for doc in self.docs if all(doc.get(key) == value for key, value in filter_doc.items())]

    def count_documents(self, filter_doc):
        return sum(1 for doc in self.docs if all(doc.get(key) == value for key, value in filter_doc.items()))

    def delete_many(self, *_args, **_kwargs):
        self.delete_calls.append((_args, _kwargs))
        raise AssertionError("seller flow must not delete catalog docs")


def _settings(enabled=True):
    return SimpleNamespace(
        enable_seller_tools=enabled,
        seller_index_confirmation="INDEX_SELLER_DRAFT",
        seller_draft_max_preview_units=20,
    )


def _payload():
    return {
        "seller_id": "seller_demo_001",
        "title": "Gentle Hydrating Toner",
        "description": "A gentle alcohol-free toner for daily skincare hydration and soothing.",
        "brand": "DemoBeauty",
        "category_id": "All Beauty",
        "price_vnd": 199000,
        "price_bucket": "100k_300k",
        "image_url": "https://example.test/toner.jpg",
        "attributes": {"skin_type": "sensitive"},
    }


def test_create_draft_writes_only_staging_collection() -> None:
    drafts = FakeCollection()
    items = FakeCollection()
    retrieval_units = FakeCollection()

    result = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())

    assert result["draft"]["status"] == "validated"
    assert result["draft"]["proposed_item_id"].startswith("seller_")
    assert len(drafts.insert_one_calls) == 1
    assert items.insert_one_calls == []
    assert retrieval_units.insert_many_calls == []


def test_validation_stores_errors_for_invalid_draft() -> None:
    drafts = FakeCollection()
    created = create_seller_draft(
        {"title": "x", "description": "too short", "category_id": ""},
        drafts_collection=drafts,
        settings=_settings(),
    )["draft"]

    result = validate_seller_draft(created["draft_id"], drafts_collection=drafts)

    assert result["draft"]["status"] == "draft"
    assert "title must be at least 3 characters" in result["draft"]["validation_errors"]


def test_proposed_item_id_is_deterministic_and_seller_prefixed() -> None:
    first = build_proposed_item_id(_payload())
    second = build_proposed_item_id(_payload())

    assert first == second
    assert first.startswith("seller_seller_demo_001_")


def test_index_preview_updates_staging_only_and_returns_units() -> None:
    drafts = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]

    result = preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, settings=_settings())

    assert result["catalog_write_performed"] is False
    assert result["preview"]["preview_only"] is True
    assert result["preview"]["estimated_retrieval_units"] >= 2
    assert drafts.update_one_calls


@pytest.mark.parametrize("write,confirm", [(False, "INDEX_SELLER_DRAFT"), (True, ""), (True, "WRONG")])
def test_approve_index_refuses_without_write_and_confirm(write, confirm) -> None:
    drafts = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]
    preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, settings=_settings())
    items = FakeCollection()
    retrieval_units = FakeCollection()

    with pytest.raises(PermissionError):
        approve_and_index_seller_draft(
            created["draft_id"],
            write=write,
            confirm=confirm,
            drafts_collection=drafts,
            items_collection=items,
            retrieval_units_collection=retrieval_units,
            settings=_settings(),
        )

    assert items.insert_one_calls == []
    assert retrieval_units.insert_many_calls == []


def test_approve_index_inserts_additively_and_no_forbidden_writes() -> None:
    drafts = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]
    preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, settings=_settings())
    items = FakeCollection()
    retrieval_units = FakeCollection()

    result = approve_and_index_seller_draft(
        created["draft_id"],
        write=True,
        confirm="INDEX_SELLER_DRAFT",
        drafts_collection=drafts,
        items_collection=items,
        retrieval_units_collection=retrieval_units,
        settings=_settings(),
    )

    assert result["inserted_items"] == 1
    assert result["inserted_retrieval_units"] >= 2
    assert items.insert_one_calls[0]["_id"] == result["item_id"]
    assert all(unit["item_id"] == result["item_id"] for unit in retrieval_units.insert_many_calls[0][0])
    assert result["forbidden_writes_performed"] == []
    assert items.delete_calls == []
    assert retrieval_units.delete_calls == []


def test_approve_index_refuses_existing_item_collision() -> None:
    drafts = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]
    preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, settings=_settings())
    items = FakeCollection([{"_id": created["proposed_item_id"]}])
    retrieval_units = FakeCollection()

    with pytest.raises(ValueError, match="item already exists"):
        approve_and_index_seller_draft(
            created["draft_id"],
            write=True,
            confirm="INDEX_SELLER_DRAFT",
            drafts_collection=drafts,
            items_collection=items,
            retrieval_units_collection=retrieval_units,
            settings=_settings(),
        )

    assert retrieval_units.insert_many_calls == []

