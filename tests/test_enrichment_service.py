from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.enrichment.schemas import WebSearchResult
from src.enrichment.service import (
    apply_enrichment_to_draft,
    build_enrichment_query_from_draft,
    build_suggested_fields_from_results,
    request_web_enrichment,
)
from src.seller.drafts import create_seller_draft


class FakeInsertResult:
    inserted_id = "inserted"


class FakeCollection:
    def __init__(self, docs=None, *, fail_update: bool = False):
        self.docs = [dict(doc) for doc in (docs or [])]
        self.insert_one_calls = []
        self.update_one_calls = []
        self.insert_many_calls = []
        self.delete_many_calls = []
        self.delete_one_calls = []
        self.fail_update = fail_update

    def insert_one(self, doc):
        self.insert_one_calls.append(dict(doc))
        self.docs.append(dict(doc))
        return FakeInsertResult()

    def insert_many(self, *_args, **_kwargs):
        self.insert_many_calls.append((_args, _kwargs))
        raise AssertionError("enrichment must not insert catalog docs")

    def update_one(self, filter_doc, update_doc):
        self.update_one_calls.append((dict(filter_doc), dict(update_doc)))
        if self.fail_update:
            raise RuntimeError("update failed")
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                for key, value in update_doc.get("$set", {}).items():
                    _set_path(doc, key, value)
                for key in update_doc.get("$unset", {}).keys():
                    _unset_path(doc, key)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def find_one(self, filter_doc, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                return dict(doc)
        return None

    def delete_many(self, *_args, **_kwargs):
        self.delete_many_calls.append((_args, _kwargs))
        raise AssertionError("enrichment must not delete docs")

    def delete_one(self, filter_doc):
        self.delete_one_calls.append(dict(filter_doc))
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in filter_doc.items()):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


def _set_path(doc, key, value):
    parts = key.split(".")
    current = doc
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _unset_path(doc, key):
    parts = key.split(".")
    current = doc
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            return
        current = next_value
    current.pop(parts[-1], None)


class FakeProvider:
    name = "fake_provider"

    def __init__(self, *, error=False, results=None):
        self.error = error
        self.results = results or [
            WebSearchResult(
                title="DemoSun Seller Sunscreen",
                url="https://example.test/source",
                snippet="Lightweight sunscreen details with oily skin evidence.",
                score=0.7,
                source="fake_provider",
            )
        ]
        self.calls = []

    def search(self, query: str, *, max_results: int):
        self.calls.append((query, max_results))
        if self.error:
            raise RuntimeError("provider unavailable with sanitized message")
        return self.results


def _settings(*, enabled=True, key="test-key"):
    return SimpleNamespace(
        enable_seller_tools=True,
        enable_web_enrichment=enabled,
        web_enrichment_provider="tavily",
        tavily_api_key=key,
        tavily_max_results=3,
        web_enrichment_timeout_seconds=10,
        web_enrichment_apply_confirmation="APPLY_WEB_ENRICHMENT",
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


def _draft(drafts: FakeCollection):
    return create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]


def test_feature_disabled_does_not_call_provider_or_write() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    provider = FakeProvider()

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(enabled=False),
        provider=provider,
    )

    assert result["status"] == "disabled"
    assert provider.calls == []
    assert requests.insert_one_calls == []


def test_missing_api_key_returns_configured_error_without_write() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(key=""),
    )

    assert result["status"] == "provider_not_configured"
    assert requests.insert_one_calls == []


def test_build_query_uses_draft_fields_without_secret() -> None:
    query = build_enrichment_query_from_draft(_payload())

    assert "DemoSun" in query
    assert "Seller Sunscreen" in query
    assert "All Beauty" in query
    assert "API_KEY" not in query


def test_fake_provider_success_stores_request_without_catalog_writes() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    provider = FakeProvider()

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=provider,
    )

    assert result["status"] == "completed"
    assert result["request"]["suggested_fields"]["description"]["source_urls"] == ["https://example.test/source"]
    assert len(requests.insert_one_calls) == 1
    assert drafts.update_one_calls[-1][1]["$set"]["enrichment.status"] == "available"


def test_provider_error_is_stored_as_failed_without_crash() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(error=True),
    )

    assert result["status"] == "failed"
    assert result["request"]["error"].startswith("RuntimeError")
    assert len(requests.insert_one_calls) == 1


def test_suggested_fields_require_source_urls() -> None:
    suggestions = build_suggested_fields_from_results(
        [{"title": "No URL", "snippet": "Evidence but no provenance", "score": 0.8, "source": "fake"}],
        _payload(),
    )

    assert suggestions == {}


@pytest.mark.parametrize("confirm", [None, "", "WRONG"])
def test_apply_refuses_without_confirm(confirm) -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )
    request_id = requests.docs[-1]["request_id"]

    with pytest.raises(PermissionError):
        apply_enrichment_to_draft(
            request_id,
            fields_to_apply=["description"],
            confirm=confirm,
            drafts_collection=drafts,
            requests_collection=requests,
            settings=_settings(),
        )


def test_apply_with_confirm_updates_only_selected_draft_fields_and_request() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )
    request_id = requests.docs[-1]["request_id"]

    result = apply_enrichment_to_draft(
        request_id,
        fields_to_apply=["attributes.web_evidence_summary"],
        confirm="APPLY_WEB_ENRICHMENT",
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
    )

    assert result["catalog_write_performed"] is False
    assert result["applied_fields"] == ["attributes.web_evidence_summary"]
    updated_draft = drafts.find_one({"draft_id": draft["draft_id"]})
    assert updated_draft["attributes"]["web_evidence_summary"]
    assert updated_draft["enrichment"]["source_urls"] == ["https://example.test/source"]
    updated_request = requests.find_one({"request_id": request_id})
    assert updated_request["status"] == "applied"


def test_request_rolls_back_inserted_request_when_draft_update_fails() -> None:
    drafts = FakeCollection(fail_update=True)
    requests = FakeCollection()
    draft = _draft(drafts)

    with pytest.raises(RuntimeError, match="update failed"):
        request_web_enrichment(
            draft["draft_id"],
            drafts_collection=drafts,
            requests_collection=requests,
            settings=_settings(),
            provider=FakeProvider(),
        )

    assert requests.find_one({"draft_id": draft["draft_id"]}) is None
    assert requests.delete_one_calls == [{"request_id": requests.insert_one_calls[0]["request_id"]}]


def test_apply_rolls_back_draft_when_request_update_fails() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )
    request_id = requests.docs[-1]["request_id"]
    original_draft = drafts.find_one({"draft_id": draft["draft_id"]})
    requests.fail_update = True

    with pytest.raises(RuntimeError, match="update failed"):
        apply_enrichment_to_draft(
            request_id,
            fields_to_apply=["description"],
            confirm="APPLY_WEB_ENRICHMENT",
            drafts_collection=drafts,
            requests_collection=requests,
            settings=_settings(),
        )

    reverted_draft = drafts.find_one({"draft_id": draft["draft_id"]})
    assert reverted_draft["description"] == original_draft["description"]
    assert reverted_draft["enrichment"]["status"] == original_draft["enrichment"]["status"]
    assert requests.find_one({"request_id": request_id})["status"] == "completed"

