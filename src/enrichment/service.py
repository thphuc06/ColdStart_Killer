from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from typing import Any

from src.config import PROJECT_ROOT, Settings, get_settings
from src.enrichment.providers import ProviderConfigurationError, WebEnrichmentProvider
from src.enrichment.schemas import WebEnrichmentSuggestion, WebSearchResult
from src.enrichment.tavily_client import TavilyProvider
from src.llm_client import call_qwen, extract_json_from_text
from src.seller.drafts import get_seller_draft, sanitize_seller_draft
from src.utils import utc_now_iso


COMPACT_RESULT_LIMIT = 10
PRODUCT_CONTEXT_MAX_CHARS = 9_000
QUERY_PROMPT_VERSION = "seller_web_query_plan_v1"
SYNTHESIS_PROMPT_VERSION = "seller_web_synthesis_v1"
QUERY_PROMPT_PATH = PROJECT_ROOT / "prompts" / "plan_enrichment_queries.txt"
SYNTHESIS_PROMPT_PATH = PROJECT_ROOT / "prompts" / "synthesize_web_enrichment.txt"
_MISSING = object()
_INDEXABLE_ENRICHMENT_FIELDS = {"description", "brand", "features", "attributes.web_evidence_summary"}
_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "purpose": {"enum": ["identity", "specifications", "claim_verification"]},
                    "query": {"type": "string"},
                },
                "required": ["purpose", "query"],
            },
        }
    },
    "required": ["queries"],
}
_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "enriched_description": {"type": "string"},
        "key_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {},
                    "confidence": {"type": "number"},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["field", "value", "confidence", "source_urls"],
            },
        },
        "quality": {"enum": ["high", "medium", "low"]},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["enriched_description", "key_facts", "quality", "unsupported_claims"],
}


def _path_state(doc: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = doc
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _safe_delete_one(collection: Any, filter_doc: dict[str, Any]) -> None:
    if hasattr(collection, "delete_one"):
        collection.delete_one(filter_doc)
        return
    if hasattr(collection, "delete_many"):
        collection.delete_many(filter_doc)
        return
    raise RuntimeError("collection does not support delete rollback")


def _matched_count(result: Any) -> int:
    try:
        return int(getattr(result, "matched_count", 1))
    except (TypeError, ValueError):
        return 1


def _restore_draft_state(
    drafts_collection: Any,
    draft_id: str,
    *,
    original_paths: dict[str, Any],
) -> None:
    rollback_set: dict[str, Any] = {}
    rollback_unset: dict[str, str] = {}
    for path, value in original_paths.items():
        if value is _MISSING:
            rollback_unset[path] = ""
        else:
            rollback_set[path] = value
    update_doc: dict[str, Any] = {}
    if rollback_set:
        update_doc["$set"] = rollback_set
    if rollback_unset:
        update_doc["$unset"] = rollback_unset
    if update_doc:
        drafts_collection.update_one({"draft_id": draft_id}, update_doc)


def web_enrichment_disabled_response(settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    return {
        "ok": True,
        "enabled": False,
        "status": "disabled",
        "message": "Web enrichment is disabled by ENABLE_WEB_ENRICHMENT=false.",
        "provider": getattr(active_settings, "web_enrichment_provider", "tavily"),
        "required_confirmation": getattr(active_settings, "web_enrichment_apply_confirmation", "APPLY_WEB_ENRICHMENT"),
    }


def provider_not_configured_response(settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    return {
        "ok": True,
        "enabled": True,
        "status": "provider_not_configured",
        "provider": getattr(active_settings, "web_enrichment_provider", "tavily"),
        "message": "Web enrichment provider is enabled but not configured.",
        "required_confirmation": getattr(active_settings, "web_enrichment_apply_confirmation", "APPLY_WEB_ENRICHMENT"),
    }


def build_provider(settings: Settings | None = None) -> WebEnrichmentProvider:
    active_settings = settings or get_settings()
    provider_name = active_settings.web_enrichment_provider.strip().lower()
    if provider_name != "tavily":
        raise ProviderConfigurationError(f"Unsupported web enrichment provider: {provider_name}")
    return TavilyProvider(
        api_key=active_settings.tavily_api_key,
        timeout_seconds=active_settings.web_enrichment_timeout_seconds,
    )


def _provider_configured(settings: Settings) -> bool:
    if settings.web_enrichment_provider.strip().lower() == "tavily":
        return bool(settings.tavily_api_key.strip())
    return False


def build_product_context_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    context = {
        "trust_level": "unverified_seller_input",
        "title": str(draft.get("title") or "").strip(),
        "brand": str(draft.get("brand") or "").strip(),
        "category_id": str(draft.get("category_id") or "").strip(),
        "features": [str(feature).strip() for feature in draft.get("features") or [] if str(feature).strip()],
        "attributes": draft.get("attributes") if isinstance(draft.get("attributes"), dict) else {},
        "description": str(draft.get("description") or "").strip(),
    }
    encoded = json.dumps(context, ensure_ascii=True, sort_keys=True)
    if len(encoded) > PRODUCT_CONTEXT_MAX_CHARS:
        overflow = len(encoded) - PRODUCT_CONTEXT_MAX_CHARS
        description = context["description"]
        context["description"] = description[: max(0, len(description) - overflow)]
    return context


def build_enrichment_query_from_draft(draft: dict[str, Any]) -> str:
    parts = [
        str(draft.get("brand") or "").strip(),
        str(draft.get("title") or "").strip(),
        str(draft.get("category_id") or "").strip(),
    ]
    description = str(draft.get("description") or "").strip()
    if description:
        parts.append(" ".join(description.split()[:18]))
    return " ".join(part for part in parts if part).strip()


def _result_to_dict(result: WebSearchResult) -> dict[str, Any]:
    return result.model_dump() if hasattr(result, "model_dump") else result.dict()


def _model_to_dict(model: Any) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


def normalize_search_results(results: list[WebSearchResult | dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for result in results[:COMPACT_RESULT_LIMIT]:
        data = _result_to_dict(result) if isinstance(result, WebSearchResult) else dict(result)
        url = str(data.get("url") or "").strip()
        if not url:
            continue
        score = data.get("score")
        try:
            normalized_score = float(score) if score is not None else None
        except (TypeError, ValueError):
            normalized_score = None
        normalized.append(
            {
                "title": str(data.get("title") or "").strip(),
                "url": url,
                "snippet": str(data.get("snippet") or data.get("content") or "").strip(),
                "score": normalized_score,
                "source": str(data.get("source") or "tavily"),
            }
        )
    return normalized


def build_suggested_fields_from_results(results: list[dict[str, Any]], draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidenced = [result for result in results if result.get("url") and result.get("snippet")]
    if not evidenced:
        return {}
    source_urls = [str(result["url"]) for result in evidenced[:3]]
    snippets = [str(result["snippet"]).strip() for result in evidenced[:2] if str(result.get("snippet") or "").strip()]
    if not snippets:
        return {}
    scores = [float(result["score"]) for result in evidenced if isinstance(result.get("score"), (int, float))]
    confidence = round(max(0.35, min(0.85, sum(scores) / len(scores) if scores else 0.55)), 3)
    evidence_summary = " ".join(snippets)[:900]
    suggestions = {
        "description": WebEnrichmentSuggestion(
            value=evidence_summary,
            confidence=confidence,
            source_urls=source_urls,
            reason="Fallback summary derived only from sourced web snippets; seller review is required.",
        ),
        "attributes.web_evidence_summary": WebEnrichmentSuggestion(
            value=evidence_summary[:500],
            confidence=confidence,
            source_urls=source_urls,
            reason="Stores an auditable evidence summary without changing catalog documents.",
        ),
    }
    normalized = {field: _model_to_dict(suggestion) for field, suggestion in suggestions.items()}
    if not str(draft.get("brand") or "").strip():
        title = str(evidenced[0].get("title") or "").strip()
        if title:
            normalized["brand"] = _model_to_dict(
                WebEnrichmentSuggestion(
                    value=title.split(" - ")[0][:160],
                    confidence=round(min(confidence, 0.5), 3),
                    source_urls=[source_urls[0]],
                    reason="Low-confidence brand hint from sourced result title; seller review is required.",
                )
            )
    return normalized


def _read_prompt(path: Any) -> str:
    return path.read_text(encoding="utf-8")


def _fallback_query_plan(draft: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {
        "model": getattr(settings, "ollama_model", "qwen3:8b"),
        "prompt_version": QUERY_PROMPT_VERSION,
        "planner_source": "fallback_template",
        "queries": [{"purpose": "identity", "query": build_enrichment_query_from_draft(draft)}],
    }


def plan_enrichment_queries(draft: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    context = build_product_context_from_draft(draft)
    prompt = _read_prompt(QUERY_PROMPT_PATH).replace(
        "{product_context}",
        json.dumps(context, ensure_ascii=True, sort_keys=True),
    )
    try:
        raw = call_qwen(prompt, max_tokens=500, temperature=0.1, format_schema=_QUERY_SCHEMA)
        payload = extract_json_from_text(raw)
        raw_queries = payload.get("queries") if isinstance(payload, dict) else None
        if not isinstance(raw_queries, list):
            raise ValueError("query planner did not return queries")
        queries: list[dict[str, str]] = []
        for record in raw_queries[: max(1, min(3, int(getattr(settings, "web_enrichment_max_queries", 3))))]:
            if not isinstance(record, dict):
                continue
            purpose = str(record.get("purpose") or "").strip()
            query = str(record.get("query") or "").strip()
            if purpose not in {"identity", "specifications", "claim_verification"} or not query:
                continue
            if not any(existing["purpose"] == purpose for existing in queries):
                queries.append({"purpose": purpose, "query": query[:300]})
        if not queries or not any(query["purpose"] == "identity" for query in queries):
            raise ValueError("query planner did not include identity query")
        return {
            "model": getattr(settings, "ollama_model", "qwen3:8b"),
            "prompt_version": QUERY_PROMPT_VERSION,
            "planner_source": "llm",
            "queries": queries,
        }
    except Exception:
        return _fallback_query_plan(draft, settings)


async def _run_searches(
    provider: WebEnrichmentProvider,
    query_plan: dict[str, Any],
    *,
    max_results: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    async def run_one(query_item: dict[str, str]) -> dict[str, Any]:
        try:
            response = provider.search(query_item["query"], max_results=max_results)
            results = await response if inspect.isawaitable(response) else response
            return {**query_item, "status": "completed", "results": normalize_search_results(results), "error": None}
        except Exception as exc:
            return {
                **query_item,
                "status": "failed",
                "results": [],
                "error": f"{exc.__class__.__name__}: {str(exc)[:180]}",
            }

    search_runs = await asyncio.gather(*(run_one(query) for query in query_plan["queries"]))
    merged: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    errors: list[str] = []
    for search_run in search_runs:
        if search_run["error"]:
            errors.append(search_run["error"])
        for result in search_run["results"]:
            if result["url"] not in seen_urls:
                seen_urls.add(result["url"])
                merged.append(result)
    return list(search_runs), merged[:COMPACT_RESULT_LIMIT], errors


def synthesize_enrichment(
    draft: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    settings: Settings,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fallback_suggestions = build_suggested_fields_from_results(evidence, draft)
    fallback = {
        "model": getattr(settings, "ollama_model", "qwen3:8b"),
        "prompt_version": SYNTHESIS_PROMPT_VERSION,
        "synthesis_source": "fallback_snippet_summary",
        "quality": "low",
        "enriched_description": fallback_suggestions.get("description", {}).get("value", ""),
        "key_facts": [],
        "unsupported_claims": [],
        "warnings": ["LLM synthesis unavailable or invalid; review snippet-derived suggestions carefully."],
    }
    if not evidence:
        return fallback, {}
    context = build_product_context_from_draft(draft)
    prompt = (
        _read_prompt(SYNTHESIS_PROMPT_PATH)
        .replace("{product_context}", json.dumps(context, ensure_ascii=True, sort_keys=True))
        .replace("{evidence}", json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    )
    allowed_urls = {str(result["url"]) for result in evidence if result.get("url")}
    try:
        raw = call_qwen(prompt, max_tokens=900, temperature=0.1, format_schema=_SYNTHESIS_SCHEMA)
        payload = extract_json_from_text(raw)
        if not isinstance(payload, dict):
            raise ValueError("synthesis output is not an object")
        quality = str(payload.get("quality") or "low").lower()
        if quality not in {"high", "medium", "low"}:
            quality = "low"
        key_facts: list[dict[str, Any]] = []
        for fact in payload.get("key_facts") or []:
            if not isinstance(fact, dict):
                continue
            source_urls = [str(url) for url in fact.get("source_urls") or [] if str(url) in allowed_urls]
            if not source_urls:
                continue
            confidence = fact.get("confidence", 0.0)
            try:
                confidence = round(max(0.0, min(1.0, float(confidence))), 3)
            except (TypeError, ValueError):
                confidence = 0.0
            key_facts.append(
                {
                    "field": str(fact.get("field") or "").strip(),
                    "value": fact.get("value"),
                    "confidence": confidence,
                    "source_urls": source_urls,
                }
            )
        description = str(payload.get("enriched_description") or "").strip()
        if not description:
            raise ValueError("synthesis did not return enriched_description")
        all_urls = sorted({url for fact in key_facts for url in fact["source_urls"]}) or sorted(allowed_urls)
        description_confidence = max((fact["confidence"] for fact in key_facts), default=0.55)
        suggestions: dict[str, dict[str, Any]] = {
            "description": _model_to_dict(
                WebEnrichmentSuggestion(
                    value=description,
                    confidence=description_confidence,
                    source_urls=all_urls,
                    reason="Grounded Qwen synthesis from sourced web evidence; seller review is required.",
                )
            ),
            "attributes.web_evidence_summary": _model_to_dict(
                WebEnrichmentSuggestion(
                    value=description[:500],
                    confidence=description_confidence,
                    source_urls=all_urls,
                    reason="Stores the sourced synthesis summary used during seller review.",
                )
            ),
        }
        if not str(draft.get("brand") or "").strip():
            brand_fact = next((fact for fact in key_facts if fact["field"].lower() == "brand" and fact["value"]), None)
            if brand_fact:
                suggestions["brand"] = _model_to_dict(
                    WebEnrichmentSuggestion(
                        value=str(brand_fact["value"])[:160],
                        confidence=brand_fact["confidence"],
                        source_urls=brand_fact["source_urls"],
                        reason="Grounded brand fact from sourced web evidence; seller review is required.",
                    )
                )
        synthesis = {
            "model": getattr(settings, "ollama_model", "qwen3:8b"),
            "prompt_version": SYNTHESIS_PROMPT_VERSION,
            "synthesis_source": "llm",
            "quality": quality,
            "enriched_description": description,
            "key_facts": key_facts,
            "unsupported_claims": [
                str(claim)[:300] for claim in payload.get("unsupported_claims") or [] if str(claim).strip()
            ],
            "warnings": [],
        }
        return synthesis, suggestions
    except Exception:
        return fallback, fallback_suggestions


def preview_seller_draft_enrichment(
    draft_id: str,
    *,
    drafts_collection: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.enable_web_enrichment:
        return web_enrichment_disabled_response(active_settings)
    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    query = build_enrichment_query_from_draft(draft)
    configured = _provider_configured(active_settings)
    return {
        "ok": True,
        "enabled": True,
        "status": "ready" if configured else "provider_not_configured",
        "draft_id": draft_id,
        "provider": active_settings.web_enrichment_provider,
        "provider_configured": configured,
        "product_context": build_product_context_from_draft(draft),
        "query": query,
        "write_performed": False,
        "message": (
            "Preview only. Request enrichment to run Qwen query planning, parallel web search, and grounded synthesis."
            if configured
            else "Web enrichment is enabled but TAVILY_API_KEY is not configured."
        ),
        "required_confirmation": active_settings.web_enrichment_apply_confirmation,
    }


async def request_web_enrichment_async(
    draft_id: str,
    *,
    drafts_collection: Any,
    requests_collection: Any,
    settings: Settings | None = None,
    provider: WebEnrichmentProvider | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.enable_web_enrichment:
        return web_enrichment_disabled_response(active_settings)
    if provider is None and not _provider_configured(active_settings):
        return provider_not_configured_response(active_settings)
    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    request_id = f"enrich_{uuid.uuid4().hex}"
    now = utc_now_iso()
    active_provider = provider or build_provider(active_settings)
    query_plan = await asyncio.to_thread(plan_enrichment_queries, draft, settings=active_settings)
    search_runs, evidence, search_errors = await _run_searches(
        active_provider,
        query_plan,
        max_results=active_settings.tavily_max_results,
    )
    status = "completed" if evidence else "failed"
    synthesis, suggestions = await asyncio.to_thread(synthesize_enrichment, draft, evidence, settings=active_settings)
    error = "; ".join(search_errors) if status == "failed" and search_errors else None
    request_doc = {
        "request_id": request_id,
        "draft_id": draft_id,
        "seller_id": draft.get("seller_id"),
        "provider": getattr(active_provider, "name", active_settings.web_enrichment_provider),
        "query": query_plan["queries"][0]["query"],
        "query_plan": query_plan,
        "search_runs": search_runs,
        "evidence": evidence,
        "synthesis": synthesis,
        "status": status,
        "results": evidence,
        "suggested_fields": suggestions if status == "completed" else {},
        "applied_fields": [],
        "created_at": now,
        "updated_at": now,
        "error": error,
    }
    if not dry_run:
        inserted_request = False
        try:
            requests_collection.insert_one(dict(request_doc))
            inserted_request = True
            draft_update_result = drafts_collection.update_one(
                {"draft_id": draft_id},
                {
                    "$set": {
                        "enrichment.latest_request_id": request_id,
                        "enrichment.status": "available" if status == "completed" and suggestions else status,
                        "enrichment.provider": request_doc["provider"],
                        "enrichment.updated_at": now,
                        "updated_at": now,
                    }
                },
            )
            if _matched_count(draft_update_result) <= 0:
                raise RuntimeError("seller draft update failed during enrichment request")
        except Exception:
            if inserted_request:
                _safe_delete_one(requests_collection, {"request_id": request_id})
            raise
    return {
        "ok": status != "failed",
        "enabled": True,
        "status": status,
        "request": sanitize_enrichment_request(request_doc),
        "write_scope": [] if dry_run else ["web_enrichment_requests", "seller_product_drafts"],
        "catalog_write_performed": False,
    }


def request_web_enrichment(
    draft_id: str,
    *,
    drafts_collection: Any,
    requests_collection: Any,
    settings: Settings | None = None,
    provider: WebEnrichmentProvider | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        request_web_enrichment_async(
            draft_id,
            drafts_collection=drafts_collection,
            requests_collection=requests_collection,
            settings=settings,
            provider=provider,
            dry_run=dry_run,
        )
    )


def get_enrichment_request(request_id: str, *, requests_collection: Any) -> dict[str, Any]:
    doc = requests_collection.find_one({"request_id": request_id})
    if not doc:
        raise LookupError(f"enrichment request not found: {request_id}")
    return sanitize_enrichment_request(dict(doc))


def sanitize_enrichment_request(doc: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(doc)
    if "_id" in sanitized:
        sanitized["id"] = str(sanitized.pop("_id"))
    sanitized["results"] = normalize_search_results(sanitized.get("results") or [])
    sanitized["evidence"] = normalize_search_results(sanitized.get("evidence") or sanitized["results"])
    allowed_urls = {result["url"] for result in sanitized["evidence"]}
    synthesis = dict(sanitized.get("synthesis") or {})
    synthesis["key_facts"] = [
        fact
        for fact in synthesis.get("key_facts") or []
        if isinstance(fact, dict)
        and any(str(url) in allowed_urls for url in fact.get("source_urls") or [])
    ]
    sanitized["synthesis"] = synthesis
    allowed_suggestions: dict[str, Any] = {}
    for field, suggestion in dict(sanitized.get("suggested_fields") or {}).items():
        if not isinstance(suggestion, dict):
            continue
        source_urls = [str(url) for url in suggestion.get("source_urls") or [] if str(url) in allowed_urls]
        if not source_urls:
            continue
        allowed_suggestions[str(field)] = {
            "value": suggestion.get("value"),
            "confidence": suggestion.get("confidence"),
            "source_urls": source_urls,
            "reason": str(suggestion.get("reason") or ""),
        }
    sanitized["suggested_fields"] = allowed_suggestions
    return sanitized


def _field_value_from_draft(draft: dict[str, Any], field: str) -> Any:
    if field.startswith("attributes."):
        key = field.split(".", 1)[1]
        attributes = draft.get("attributes") if isinstance(draft.get("attributes"), dict) else {}
        return attributes.get(key)
    return draft.get(field)


def _update_path_for_field(field: str) -> str:
    if field.startswith("attributes."):
        return field
    if field in {"description", "brand"}:
        return field
    raise ValueError(f"field is not allowed for web enrichment apply: {field}")


def apply_enrichment_to_draft(
    request_id: str,
    *,
    fields_to_apply: list[str],
    confirm: str | None,
    drafts_collection: Any,
    requests_collection: Any,
    previews_collection: Any | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.enable_web_enrichment:
        return web_enrichment_disabled_response(active_settings)
    if confirm != active_settings.web_enrichment_apply_confirmation:
        raise PermissionError(f"apply enrichment requires confirm={active_settings.web_enrichment_apply_confirmation}")
    request_doc = get_enrichment_request(request_id, requests_collection=requests_collection)
    if request_doc.get("status") != "completed":
        raise ValueError("enrichment request must be completed before apply")
    suggestions = dict(request_doc.get("suggested_fields") or {})
    selected = [field for field in fields_to_apply if field in suggestions]
    if not selected:
        raise ValueError("no valid suggested fields selected")
    draft = get_seller_draft(str(request_doc["draft_id"]), drafts_collection=drafts_collection)
    if draft.get("status") == "indexed":
        raise ValueError("enrichment must be applied before approve-index commits the seller draft")
    source_urls = sorted({url for field in selected for url in suggestions[field].get("source_urls", [])})
    now = utc_now_iso()
    preview = draft.get("indexing_preview") if isinstance(draft.get("indexing_preview"), dict) else None
    invalidates_preview = bool(preview) and any(field in _INDEXABLE_ENRICHMENT_FIELDS or field.startswith("attributes.") for field in selected)
    original_paths: dict[str, Any] = {}
    for path in [
        "status",
        "indexing_preview",
        "enrichment.status",
        "enrichment.latest_request_id",
        "enrichment.applied_request_ids",
        "enrichment.applied_fields",
        "enrichment.source_urls",
        "enrichment.quality",
        "enrichment.model",
        "enrichment.key_facts",
        "enrichment.requires_repreview",
        "enrichment.updated_at",
        "enrichment.original_fields",
        "updated_at",
    ]:
        present, value = _path_state(draft, path)
        original_paths[path] = value if present else _MISSING
    synthesis = dict(request_doc.get("synthesis") or {})
    update_set: dict[str, Any] = {
        "enrichment.status": "applied",
        "enrichment.latest_request_id": request_id,
        "enrichment.applied_request_ids": sorted(
            set((draft.get("enrichment") or {}).get("applied_request_ids") or []) | {request_id}
        ),
        "enrichment.applied_fields": selected,
        "enrichment.source_urls": source_urls,
        "enrichment.quality": synthesis.get("quality", "low"),
        "enrichment.model": synthesis.get("model"),
        "enrichment.key_facts": synthesis.get("key_facts") or [],
        "enrichment.requires_repreview": invalidates_preview,
        "enrichment.updated_at": now,
        "updated_at": now,
    }
    if invalidates_preview:
        update_set["indexing_preview"] = None
        update_set["status"] = "validated"
    for field in selected:
        update_path = _update_path_for_field(field)
        present, current_value = _path_state(draft, update_path)
        original_paths[update_path] = current_value if present else _MISSING
        update_set[update_path] = suggestions[field]["value"]
        update_set[f"enrichment.original_fields.{field.replace('.', '__')}"] = _field_value_from_draft(draft, field)
    draft_update_result = drafts_collection.update_one({"draft_id": request_doc["draft_id"]}, {"$set": update_set})
    if _matched_count(draft_update_result) <= 0:
        raise RuntimeError("seller draft update failed during enrichment apply")
    try:
        request_update_result = requests_collection.update_one(
            {"request_id": request_id},
            {"$set": {"status": "applied", "applied_fields": selected, "updated_at": now}},
        )
        if _matched_count(request_update_result) <= 0:
            raise RuntimeError("enrichment request update failed during apply")
    except Exception:
        _restore_draft_state(drafts_collection, str(request_doc["draft_id"]), original_paths=original_paths)
        raise
    if invalidates_preview and previews_collection is not None and preview and preview.get("preview_id"):
        previews_collection.update_one(
            {"preview_id": preview["preview_id"], "status": "ready"},
            {"$set": {"status": "invalidated", "updated_at": now, "invalidated_by_request_id": request_id}},
        )
    updated_draft = get_seller_draft(str(request_doc["draft_id"]), drafts_collection=drafts_collection)
    return {
        "ok": True,
        "enabled": True,
        "status": "applied",
        "request_id": request_id,
        "draft_id": request_doc["draft_id"],
        "applied_fields": selected,
        "source_urls": source_urls,
        "requires_repreview": invalidates_preview,
        "draft": sanitize_seller_draft(updated_draft),
        "write_scope": ["seller_product_drafts", "web_enrichment_requests"]
        + (["seller_indexing_previews"] if invalidates_preview and previews_collection is not None else []),
        "catalog_write_performed": False,
    }
