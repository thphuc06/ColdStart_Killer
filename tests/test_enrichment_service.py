from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.enrichment.schemas import WebSearchResult
from src.enrichment.service import (
    apply_enrichment_to_draft,
    build_enrichment_query_from_draft,
    build_product_context_from_draft,
    build_suggested_fields_from_results,
    request_web_enrichment,
    select_relevant_evidence,
    synthesize_enrichment,
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


class ConcurrentProvider:
    name = "concurrent_provider"

    def __init__(self):
        self.active = 0
        self.max_active = 0

    async def search(self, query: str, *, max_results: int):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        return [
            WebSearchResult(
                title=query,
                url="https://example.test/shared-source",
                snippet="Same sourced evidence.",
                score=0.7,
                source=self.name,
            )
        ]


def _settings(*, enabled=True, key="test-key"):
    return SimpleNamespace(
        enable_seller_tools=True,
        enable_web_enrichment=enabled,
        web_enrichment_provider="tavily",
        tavily_api_key=key,
        tavily_max_results=3,
        web_enrichment_max_queries=3,
        web_enrichment_timeout_seconds=10,
        web_enrichment_apply_confirmation="APPLY_WEB_ENRICHMENT",
        seller_index_confirmation="INDEX_SELLER_DRAFT",
        seller_draft_max_preview_units=20,
        ollama_model="qwen3:8b",
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
        "features": ["Oil-control finish", "SPF 50"],
    }


def _draft(drafts: FakeCollection):
    return create_seller_draft(_payload(), drafts_collection=drafts, settings=_settings())["draft"]


@pytest.fixture(autouse=True)
def _fake_qwen(monkeypatch):
    def reply(prompt, **_kwargs):
        if "plan web searches" in prompt:
            return '{"queries":[{"purpose":"identity","query":"DemoSun Seller Sunscreen"},{"purpose":"specifications","query":"DemoSun Seller Sunscreen SPF 50"}]}'
        return (
            '{"enriched_description":"Sourced sunscreen description.",'
            '"key_facts":[{"field":"spf","value":"50","confidence":0.8,'
            '"source_urls":["https://example.test/source"]}],'
            '"quality":"medium","unsupported_claims":[]}'
        )

    monkeypatch.setattr("src.enrichment.service.call_qwen", reply)


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


def test_product_context_contains_index_fields_and_omits_internal_fields() -> None:
    context = build_product_context_from_draft({**_payload(), "seller_id": "secret", "draft_id": "internal"})

    assert context["features"] == ["Oil-control finish", "SPF 50"]
    assert context["attributes"] == {"spf": "50"}
    assert "seller_id" not in context
    assert "draft_id" not in context


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


def test_invalid_synthesis_is_retried_and_nested_fact_value_is_normalized(monkeypatch) -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    synthesis_calls = []

    def reply(prompt, **_kwargs):
        if "plan web searches" in prompt:
            return '{"queries":[{"purpose":"identity","query":"DemoSun Seller Sunscreen"}]}'
        synthesis_calls.append(prompt)
        if len(synthesis_calls) == 1:
            return '{"enriched_description":"truncated output"'
        return (
            '{"enriched_description":"Compact sourced sunscreen description for seller review.",'
            '"key_facts":[{"field":"brand","value":{"brand":"DemoSun"},"confidence":0.8,'
            '"source_urls":["https://example.test/source"]}],'
            '"quality":"medium","unsupported_claims":[]}'
        )

    monkeypatch.setattr("src.enrichment.service.call_qwen", reply)

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )

    assert len(synthesis_calls) == 2
    assert result["request"]["synthesis"]["synthesis_source"] == "llm"
    assert result["request"]["synthesis"]["key_facts"][0]["value"] == "DemoSun"
    assert "description" in result["request"]["suggested_fields"]


def test_invalid_synthesis_fallback_is_evidence_only_not_description(monkeypatch) -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)

    def reply(prompt, **_kwargs):
        if "plan web searches" in prompt:
            return '{"queries":[{"purpose":"identity","query":"DemoSun Seller Sunscreen"}]}'
        return '{"quality":"low","key_facts":[],"unsupported_claims":[]}'

    monkeypatch.setattr("src.enrichment.service.call_qwen", reply)

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )

    synthesis = result["request"]["synthesis"]
    assert synthesis["synthesis_source"] == "fallback_snippet_summary"
    assert synthesis["enriched_description"] == ""
    assert "description" not in result["request"]["suggested_fields"]
    assert "attributes.web_evidence_summary" in result["request"]["suggested_fields"]
    assert any("attempts failed validation" in warning.lower() for warning in synthesis["warnings"])


def test_synthesis_retries_when_description_asserts_unsupported_claim(monkeypatch) -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    synthesis_calls = []

    def reply(prompt, **_kwargs):
        if "plan web searches" in prompt:
            return '{"queries":[{"purpose":"identity","query":"DemoSun Seller Sunscreen"}]}'
        synthesis_calls.append(prompt)
        if len(synthesis_calls) == 1:
            return (
                '{"enriched_description":"This product has SPF 90.",'
                '"key_facts":[],"quality":"low","unsupported_claims":["SPF 90"]}'
            )
        return (
            '{"enriched_description":"This sourced product is prepared for seller review.",'
            '"key_facts":[],"quality":"medium","unsupported_claims":["SPF 90"]}'
        )

    monkeypatch.setattr("src.enrichment.service.call_qwen", reply)

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )

    assert len(synthesis_calls) == 2
    assert result["request"]["synthesis"]["synthesis_source"] == "llm"
    assert "SPF 90" not in result["request"]["synthesis"]["enriched_description"]


def test_synthesis_retries_when_description_asserts_unevidenced_seller_feature(monkeypatch) -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    draft = _draft(drafts)
    synthesis_calls = []

    def reply(prompt, **_kwargs):
        if "plan web searches" in prompt:
            return '{"queries":[{"purpose":"identity","query":"DemoSun Seller Sunscreen"}]}'
        synthesis_calls.append(prompt)
        if len(synthesis_calls) == 1:
            return (
                '{"enriched_description":"This sunscreen provides SPF 50 protection.",'
                '"key_facts":[],"quality":"high","unsupported_claims":[]}'
            )
        return (
            '{"enriched_description":"This sourced sunscreen is available for seller review.",'
            '"key_facts":[],"quality":"low","unsupported_claims":["SPF 50"]}'
        )

    monkeypatch.setattr("src.enrichment.service.call_qwen", reply)

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )

    assert len(synthesis_calls) == 2
    assert "SPF 50" in synthesis_calls[1]
    assert result["request"]["synthesis"]["synthesis_source"] == "llm"
    assert "SPF 50 protection" not in result["request"]["synthesis"]["enriched_description"]


def test_synthesis_expands_short_grounded_description_with_two_verified_facts(monkeypatch) -> None:
    calls = []
    evidence = [
        {
            "title": "DemoSun Daily Shield SPF 50 50 ml",
            "url": "https://demosun.example.test/product",
            "snippet": "DemoSun Daily Shield sunscreen provides SPF 50 protection in a 50 ml bottle.",
            "score": 0.9,
            "source": "tavily",
        },
    ]
    facts = (
        '"key_facts":['
        '{"field":"brand","value":"DemoSun","confidence":0.9,"source_urls":["https://demosun.example.test/product"]},'
        '{"field":"feature","value":"SPF 50","confidence":0.9,"source_urls":["https://demosun.example.test/product"]}'
        ']'
    )
    longer = " ".join(
        [
            "DemoSun Daily Shield SPF 50 is a lightweight sunscreen supplied in a 50 ml bottle for daily facial use."
        ]
        * 12
    )

    def reply(prompt, **_kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return f'{{"enriched_description":"Short grounded description.",{facts},"quality":"high","unsupported_claims":[]}}'
        return f'{{"enriched_description":"{longer}",{facts},"quality":"high","unsupported_claims":[]}}'

    monkeypatch.setattr("src.enrichment.service.call_qwen", reply)

    synthesis, _suggestions = synthesize_enrichment(
        {**_payload(), "features": []},
        evidence,
        settings=_settings(),
    )

    assert len(calls) == 2
    assert "prior response was grounded but too brief" in calls[1]
    assert synthesis["enriched_description"] == longer
    assert synthesis["warnings"] == []


def test_synthesis_keeps_short_grounded_description_when_expansion_is_invalid(monkeypatch) -> None:
    evidence = [
        {
            "title": "DemoSun Daily Shield SPF 50 50 ml",
            "url": "https://demosun.example.test/product",
            "snippet": "DemoSun Daily Shield sunscreen provides SPF 50 protection in a 50 ml bottle.",
            "score": 0.9,
            "source": "tavily",
        },
        {
            "title": "DemoSun Daily Shield usage details",
            "url": "https://demosun.example.test/details",
            "snippet": "Daily Shield is a lightweight sunscreen intended for daily facial use.",
            "score": 0.8,
            "source": "tavily",
        },
    ]
    facts = (
        '"key_facts":['
        '{"field":"brand","value":"DemoSun","confidence":0.9,"source_urls":["https://demosun.example.test/product"]},'
        '{"field":"feature","value":"SPF 50","confidence":0.9,"source_urls":["https://demosun.example.test/product"]},'
        '{"field":"size","value":"50 ml","confidence":0.8,"source_urls":["https://demosun.example.test/product"]}'
        ']'
    )
    replies = iter(
        [
            f'{{"enriched_description":"Short grounded description.",{facts},"quality":"high","unsupported_claims":[]}}',
            '{"enriched_description":"truncated expansion"',
        ]
    )
    monkeypatch.setattr("src.enrichment.service.call_qwen", lambda *_args, **_kwargs: next(replies))

    synthesis, suggestions = synthesize_enrichment(
        {**_payload(), "features": []},
        evidence,
        settings=_settings(),
    )

    assert synthesis["synthesis_source"] == "llm"
    assert synthesis["enriched_description"] == "Short grounded description."
    assert "description" in suggestions
    assert any("longer grounded rewrite was rejected" in warning.lower() for warning in synthesis["warnings"])


def test_synthesis_can_expand_after_correcting_an_invalid_first_response(monkeypatch) -> None:
    calls = []
    evidence = [
        {
            "title": "DemoSun Daily Shield SPF 50 50 ml",
            "url": "https://demosun.example.test/product",
            "snippet": "DemoSun Daily Shield sunscreen provides SPF 50 protection in a 50 ml bottle.",
            "score": 0.9,
            "source": "tavily",
        },
    ]
    facts = (
        '"key_facts":['
        '{"field":"brand","value":"DemoSun","confidence":0.9,"source_urls":["https://demosun.example.test/product"]},'
        '{"field":"feature","value":"SPF 50","confidence":0.9,"source_urls":["https://demosun.example.test/product"]}'
        ']'
    )
    longer = " ".join(["DemoSun Daily Shield SPF 50 is supplied in a 50 ml bottle for seller review."] * 9)

    def reply(prompt, **_kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return (
                '{"enriched_description":"This product has a waterproof finish.",'
                '"key_facts":[],"quality":"high","unsupported_claims":["waterproof finish"]}'
            )
        if len(calls) == 2:
            return f'{{"enriched_description":"Short grounded description.",{facts},"quality":"high","unsupported_claims":[]}}'
        return f'{{"enriched_description":"{longer}",{facts},"quality":"high","unsupported_claims":[]}}'

    monkeypatch.setattr("src.enrichment.service.call_qwen", reply)

    synthesis, _suggestions = synthesize_enrichment(
        {**_payload(), "features": []},
        evidence,
        settings=_settings(),
    )

    assert len(calls) == 3
    assert "prior response was grounded but too brief" in calls[2]
    assert synthesis["enriched_description"] == longer


def test_search_queries_run_concurrently_and_deduplicate_evidence() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    provider = ConcurrentProvider()
    draft = _draft(drafts)

    result = request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=provider,
    )

    assert provider.max_active == 2
    assert len(result["request"]["search_runs"]) == 2
    assert len(result["request"]["evidence"]) == 1


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


def test_select_relevant_evidence_skips_blocked_domains_when_alternatives_exist(monkeypatch) -> None:
    monkeypatch.setenv("WEB_ENRICHMENT_BLOCKED_DOMAINS", "youtube.com")
    draft = _payload()
    evidence = [
        {
            "title": "Video review",
            "url": "https://www.youtube.com/watch?v=abc",
            "snippet": "Seller Sunscreen breakdown and unboxing.",
            "score": 0.99,
            "source": "tavily",
        },
        {
            "title": "Brand specs",
            "url": "https://www.demosun.com/products/seller-sunscreen",
            "snippet": "Seller Sunscreen SPF 50 details and ingredients.",
            "score": 0.80,
            "source": "tavily",
        },
    ]

    selected = select_relevant_evidence(draft, evidence)

    assert selected
    assert all("youtube.com" not in item["url"] for item in selected)


def test_select_relevant_evidence_keeps_blocked_domains_as_last_resort(monkeypatch) -> None:
    monkeypatch.setenv("WEB_ENRICHMENT_BLOCKED_DOMAINS", "youtube.com")
    draft = _payload()
    evidence = [
        {
            "title": "Only available source",
            "url": "https://www.youtube.com/watch?v=only-source",
            "snippet": "Seller Sunscreen overview.",
            "score": 0.70,
            "source": "tavily",
        }
    ]

    selected = select_relevant_evidence(draft, evidence)

    assert len(selected) == 1
    assert "youtube.com" in selected[0]["url"]


def test_select_relevant_evidence_retains_preferred_official_source_without_token_overlap(monkeypatch) -> None:
    monkeypatch.setenv("WEB_ENRICHMENT_PREFERRED_DOMAINS", "apple.com")
    draft = {
        **_payload(),
        "title": "iPhone 17 Pro 256GB Deep Blue",
        "brand": "Apple",
        "features": ["256GB storage"],
    }
    evidence = [
        {
            "title": "iPhone 17 Pro 256GB Deep Blue specifications",
            "url": "https://carrier.example.test/iphone-17-pro",
            "snippet": "iPhone 17 Pro Deep Blue with 256GB storage.",
            "score": 0.9,
            "source": "tavily",
        },
        {
            "title": "Official technical specifications",
            "url": "https://www.apple.com/iphone-17-pro/specs",
            "snippet": "Technical specifications and compatibility details.",
            "score": 0.8,
            "source": "tavily",
        },
    ]

    selected = select_relevant_evidence(draft, evidence)[:1]

    assert any("apple.com" in item["url"] for item in selected)


def test_default_blocked_marketplace_source_is_not_used_when_alternative_exists(monkeypatch) -> None:
    monkeypatch.delenv("WEB_ENRICHMENT_BLOCKED_DOMAINS", raising=False)
    draft = _payload()
    evidence = [
        {
            "title": "Seller Sunscreen SPF 50 claim",
            "url": "https://www.aliexpress.com/item/questionable",
            "snippet": "Seller Sunscreen SPF 50 miracle claims.",
            "score": 0.99,
            "source": "tavily",
        },
        {
            "title": "Brand product details",
            "url": "https://www.demosun.com/seller-sunscreen",
            "snippet": "Seller Sunscreen product details.",
            "score": 0.70,
            "source": "tavily",
        },
    ]

    selected = select_relevant_evidence(draft, evidence)

    assert selected
    assert all("aliexpress.com" not in item["url"] for item in selected)


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


def test_apply_invalidates_existing_indexing_preview() -> None:
    drafts = FakeCollection()
    requests = FakeCollection()
    previews = FakeCollection([{"preview_id": "preview_old", "status": "ready"}])
    draft = _draft(drafts)
    drafts.update_one(
        {"draft_id": draft["draft_id"]},
        {"$set": {"status": "previewed", "indexing_preview": {"preview_id": "preview_old"}}},
    )
    request_web_enrichment(
        draft["draft_id"],
        drafts_collection=drafts,
        requests_collection=requests,
        settings=_settings(),
        provider=FakeProvider(),
    )

    result = apply_enrichment_to_draft(
        requests.docs[-1]["request_id"],
        fields_to_apply=["description"],
        confirm="APPLY_WEB_ENRICHMENT",
        drafts_collection=drafts,
        requests_collection=requests,
        previews_collection=previews,
        settings=_settings(),
    )

    updated_draft = drafts.find_one({"draft_id": draft["draft_id"]})
    assert result["requires_repreview"] is True
    assert updated_draft["status"] == "validated"
    assert updated_draft["indexing_preview"] is None
    assert previews.find_one({"preview_id": "preview_old"})["status"] == "invalidated"


def test_apply_refuses_after_draft_is_already_indexed() -> None:
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
    drafts.update_one({"draft_id": draft["draft_id"]}, {"$set": {"status": "indexed"}})

    with pytest.raises(ValueError, match="before approve-index"):
        apply_enrichment_to_draft(
            requests.docs[-1]["request_id"],
            fields_to_apply=["description"],
            confirm="APPLY_WEB_ENRICHMENT",
            drafts_collection=drafts,
            requests_collection=requests,
            settings=_settings(),
        )


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

