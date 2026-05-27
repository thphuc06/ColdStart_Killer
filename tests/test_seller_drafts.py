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

    def update_one(self, filter_doc, update_doc, upsert=False):
        self.update_one_calls.append((dict(filter_doc), dict(update_doc)))
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                for key, value in update_doc.get("$set", {}).items():
                    _set_path(doc, key, value)
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            doc = dict(filter_doc)
            for key, value in update_doc.get("$setOnInsert", {}).items():
                _set_path(doc, key, value)
            for key, value in update_doc.get("$set", {}).items():
                _set_path(doc, key, value)
            self.docs.append(doc)
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=doc.get("_id"))
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


def _set_path(doc, key, value):
    current = doc
    parts = key.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _settings(enabled=True):
    return SimpleNamespace(
        enable_seller_tools=enabled,
        seller_index_confirmation="INDEX_SELLER_DRAFT",
        seller_draft_max_preview_units=20,
        ollama_model="qwen3:8b",
        embedding_model="BAAI/bge-m3",
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
        "features": ["Alcohol free", "Hydrating finish"],
    }


@pytest.fixture(autouse=True)
def _fake_full_index_pipeline(monkeypatch):
    monkeypatch.setattr(
        "src.seller.indexing_preview.extract_propositions_llm",
        lambda _item: [{"raw_text": "Gentle hydrating toner.", "proposition_type": "spec", "confidence": 0.9}],
    )
    monkeypatch.setattr(
        "src.seller.indexing_preview.generate_hype_queries_llm",
        lambda _item, _props: [{"raw_text": "What toner hydrates sensitive skin?", "aspect": "benefit", "confidence": 0.9}],
    )
    monkeypatch.setattr(
        "src.seller.indexing_preview.embed_texts",
        lambda texts: [[1.0] + [0.0] * 1023 for _text in texts],
    )


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
    previews = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]

    result = preview_seller_draft_indexing(
        created["draft_id"], drafts_collection=drafts, previews_collection=previews, settings=_settings()
    )

    assert result["catalog_write_performed"] is False
    assert result["preview"]["preview_only"] is True
    assert result["preview"]["estimated_retrieval_units"] >= 2
    assert result["preview"]["vector_units_generated"] == 1
    assert previews.docs[0]["retrieval_units"][1]["embedding"]
    assert drafts.update_one_calls


@pytest.mark.parametrize("write,confirm", [(False, "INDEX_SELLER_DRAFT"), (True, ""), (True, "WRONG")])
def test_approve_index_refuses_without_write_and_confirm(write, confirm) -> None:
    drafts = FakeCollection()
    previews = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]
    preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, previews_collection=previews, settings=_settings())
    items = FakeCollection()
    retrieval_units = FakeCollection()

    with pytest.raises(PermissionError):
        approve_and_index_seller_draft(
            created["draft_id"],
            write=write,
            confirm=confirm,
            drafts_collection=drafts,
            previews_collection=previews,
            items_collection=items,
            retrieval_units_collection=retrieval_units,
            settings=_settings(),
        )

    assert items.insert_one_calls == []
    assert retrieval_units.insert_many_calls == []


def test_approve_index_inserts_additively_and_no_forbidden_writes(monkeypatch) -> None:
    drafts = FakeCollection()
    previews = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]
    preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, previews_collection=previews, settings=_settings())
    items = FakeCollection()
    retrieval_units = FakeCollection()
    profiles = FakeCollection()
    monkeypatch.setattr(
        "src.seller.indexing_preview.extract_propositions_llm",
        lambda _item: (_ for _ in ()).throw(AssertionError("approve must not regenerate propositions")),
    )

    result = approve_and_index_seller_draft(
        created["draft_id"],
        write=True,
        confirm="INDEX_SELLER_DRAFT",
        drafts_collection=drafts,
        previews_collection=previews,
        items_collection=items,
        retrieval_units_collection=retrieval_units,
        item_hype_profiles_collection=profiles,
        settings=_settings(),
    )

    assert result["inserted_items"] == 1
    assert result["inserted_retrieval_units"] >= 2
    assert items.insert_one_calls[0]["_id"] == result["item_id"]
    assert all(unit["item_id"] == result["item_id"] for unit in retrieval_units.insert_many_calls[0][0])
    assert result["forbidden_writes_performed"] == []
    assert result["post_index_status"]["item_hype_profile"] == "ready"
    assert previews.docs[0]["status"] == "committed"
    assert items.delete_calls == []
    assert retrieval_units.delete_calls == []


def test_regenerating_preview_invalidates_previous_bundle() -> None:
    drafts = FakeCollection()
    previews = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]

    first = preview_seller_draft_indexing(
        created["draft_id"], drafts_collection=drafts, previews_collection=previews, settings=_settings()
    )
    second = preview_seller_draft_indexing(
        created["draft_id"], drafts_collection=drafts, previews_collection=previews, settings=_settings()
    )

    assert previews.find_one({"preview_id": first["preview"]["preview_id"]})["status"] == "invalidated"
    assert previews.find_one({"preview_id": second["preview"]["preview_id"]})["status"] == "ready"


def test_approve_index_refuses_existing_item_collision() -> None:
    drafts = FakeCollection()
    previews = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]
    preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, previews_collection=previews, settings=_settings())
    items = FakeCollection([{"_id": created["proposed_item_id"]}])
    retrieval_units = FakeCollection()

    with pytest.raises(ValueError, match="item already exists"):
        approve_and_index_seller_draft(
            created["draft_id"],
            write=True,
            confirm="INDEX_SELLER_DRAFT",
            drafts_collection=drafts,
            previews_collection=previews,
            items_collection=items,
            retrieval_units_collection=retrieval_units,
            settings=_settings(),
        )

    assert retrieval_units.insert_many_calls == []


def test_approve_index_rejects_stale_preview_content_hash() -> None:
    drafts = FakeCollection()
    previews = FakeCollection()
    created = create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]
    preview_seller_draft_indexing(created["draft_id"], drafts_collection=drafts, previews_collection=previews, settings=_settings())
    drafts.update_one({"draft_id": created["draft_id"]}, {"$set": {"description": "Changed after preview for stale hash rejection."}})

    with pytest.raises(ValueError, match="stale"):
        approve_and_index_seller_draft(
            created["draft_id"],
            write=True,
            confirm="INDEX_SELLER_DRAFT",
            drafts_collection=drafts,
            previews_collection=previews,
            items_collection=FakeCollection(),
            retrieval_units_collection=FakeCollection(),
            settings=_settings(),
        )

