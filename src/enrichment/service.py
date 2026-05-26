from __future__ import annotations

import uuid
from typing import Any

from src.config import Settings, get_settings
from src.enrichment.providers import ProviderConfigurationError, WebEnrichmentProvider
from src.enrichment.schemas import WebEnrichmentSuggestion, WebSearchResult
from src.enrichment.tavily_client import TavilyProvider
from src.seller.drafts import get_seller_draft, sanitize_seller_draft
from src.utils import utc_now_iso


COMPACT_RESULT_LIMIT = 10


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
        if isinstance(result, WebSearchResult):
            data = _result_to_dict(result)
        else:
            data = dict(result)
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
            reason="Derived only from provider snippets with source URLs; seller must review before applying.",
        ),
        "attributes.web_evidence_summary": WebEnrichmentSuggestion(
            value=evidence_summary[:500],
            confidence=confidence,
            source_urls=source_urls,
            reason="Stores an auditable evidence summary without changing catalog documents.",
        ),
    }
    suggestions = {field: _model_to_dict(suggestion) for field, suggestion in suggestions.items()}
    if not str(draft.get("brand") or "").strip():
        title = str(evidenced[0].get("title") or "").strip()
        if title:
            suggestions["brand"] = WebEnrichmentSuggestion(
                value=title.split(" - ")[0][:160],
                confidence=round(min(confidence, 0.5), 3),
                source_urls=[source_urls[0]],
                reason="Low-confidence brand hint from result title; review before applying.",
            )
            suggestions["brand"] = _model_to_dict(suggestions["brand"])
    return suggestions


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
        "query": query,
        "write_performed": False,
        "message": (
            "Preview only. Request enrichment explicitly to call the configured provider."
            if configured
            else "Web enrichment is enabled but TAVILY_API_KEY is not configured."
        ),
        "required_confirmation": active_settings.web_enrichment_apply_confirmation,
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
    active_settings = settings or get_settings()
    if not active_settings.enable_web_enrichment:
        return web_enrichment_disabled_response(active_settings)
    if provider is None and not _provider_configured(active_settings):
        return provider_not_configured_response(active_settings)

    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    query = build_enrichment_query_from_draft(draft)
    request_id = f"enrich_{uuid.uuid4().hex}"
    now = utc_now_iso()
    active_provider = provider or build_provider(active_settings)
    status = "completed"
    error = None
    results: list[dict[str, Any]] = []
    suggestions: dict[str, dict[str, Any]] = {}

    try:
        results = normalize_search_results(
            active_provider.search(query, max_results=active_settings.tavily_max_results)
        )
        suggestions = build_suggested_fields_from_results(results, draft)
    except Exception as exc:
        status = "failed"
        error = f"{exc.__class__.__name__}: {str(exc)[:180]}"

    request_doc = {
        "request_id": request_id,
        "draft_id": draft_id,
        "seller_id": draft.get("seller_id"),
        "provider": getattr(active_provider, "name", active_settings.web_enrichment_provider),
        "query": query,
        "status": status,
        "results": results,
        "suggested_fields": suggestions,
        "applied_fields": [],
        "created_at": now,
        "updated_at": now,
        "error": error,
    }

    if not dry_run:
        requests_collection.insert_one(dict(request_doc))
        drafts_collection.update_one(
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

    return {
        "ok": status != "failed",
        "enabled": True,
        "status": status,
        "request": sanitize_enrichment_request(request_doc),
        "write_scope": [] if dry_run else ["web_enrichment_requests", "seller_product_drafts"],
        "catalog_write_performed": False,
    }


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
    allowed_suggestions: dict[str, Any] = {}
    for field, suggestion in dict(sanitized.get("suggested_fields") or {}).items():
        if not isinstance(suggestion, dict):
            continue
        source_urls = [str(url) for url in suggestion.get("source_urls") or [] if str(url).strip()]
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
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
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
    source_urls = sorted({url for field in selected for url in suggestions[field].get("source_urls", [])})
    now = utc_now_iso()
    update_set: dict[str, Any] = {
        "enrichment.status": "applied",
        "enrichment.latest_request_id": request_id,
        "enrichment.applied_request_ids": sorted(
            set((draft.get("enrichment") or {}).get("applied_request_ids") or []) | {request_id}
        ),
        "enrichment.applied_fields": selected,
        "enrichment.source_urls": source_urls,
        "enrichment.updated_at": now,
        "updated_at": now,
    }
    original_fields: dict[str, Any] = {}
    for field in selected:
        update_path = _update_path_for_field(field)
        original_fields[field] = _field_value_from_draft(draft, field)
        update_set[update_path] = suggestions[field]["value"]
        update_set[f"enrichment.original_fields.{field.replace('.', '__')}"] = original_fields[field]

    drafts_collection.update_one({"draft_id": request_doc["draft_id"]}, {"$set": update_set})
    requests_collection.update_one(
        {"request_id": request_id},
        {
            "$set": {
                "status": "applied",
                "applied_fields": selected,
                "updated_at": now,
            }
        },
    )
    draft.update({field: suggestions[field]["value"] for field in selected if "." not in field})
    draft["enrichment"] = {
        **dict(draft.get("enrichment") or {}),
        "status": "applied",
        "latest_request_id": request_id,
        "applied_request_ids": update_set["enrichment.applied_request_ids"],
        "applied_fields": selected,
        "source_urls": source_urls,
        "updated_at": now,
    }
    return {
        "ok": True,
        "enabled": True,
        "status": "applied",
        "request_id": request_id,
        "draft_id": request_doc["draft_id"],
        "applied_fields": selected,
        "source_urls": source_urls,
        "draft": sanitize_seller_draft(draft),
        "write_scope": ["seller_product_drafts", "web_enrichment_requests"],
        "catalog_write_performed": False,
    }
