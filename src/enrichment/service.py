from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import uuid
from typing import Any
from urllib.parse import urlparse

from src.config import PROJECT_ROOT, Settings, get_settings
from src.enrichment.providers import ProviderConfigurationError, WebEnrichmentProvider
from src.enrichment.schemas import WebEnrichmentSuggestion, WebSearchResult
from src.enrichment.tavily_client import TavilyProvider
from src.llm_client import call_qwen, extract_json_from_text
from src.seller.drafts import get_seller_draft, sanitize_seller_draft
from src.utils import utc_now_iso


COMPACT_RESULT_LIMIT = 10
PRODUCT_CONTEXT_MAX_CHARS = 9_000
MIN_EXPANSION_EVIDENCE_WORDS = 40
DEFAULT_QUERY_LLM_TIMEOUT_SECONDS = 30
DEFAULT_SYNTHESIS_LLM_TIMEOUT_SECONDS = 180
DEFAULT_MAX_EVIDENCE_FOR_SYNTHESIS = 3
DEFAULT_QUERY_MAX_TOKENS = 500
DEFAULT_SYNTHESIS_MAX_TOKENS = 900
DEFAULT_REQUEST_HARD_TIMEOUT_SECONDS = 240
DEFAULT_BLOCKED_EVIDENCE_DOMAINS = (
    "youtube.com,youtu.be,tiktok.com,facebook.com,instagram.com,"
    "aliexpress.com,ebay.com,reddit.com"
)
QUERY_PROMPT_VERSION = "seller_web_query_plan_v1"
SYNTHESIS_PROMPT_VERSION = "seller_web_synthesis_v3"
QUERY_PROMPT_PATH = PROJECT_ROOT / "prompts" / "plan_enrichment_queries.txt"
SYNTHESIS_PROMPT_PATH = PROJECT_ROOT / "prompts" / "synthesize_web_enrichment.txt"
_MISSING = object()
_INDEXABLE_ENRICHMENT_FIELDS = {"description", "brand", "features", "attributes.web_evidence_summary"}
_BACKGROUND_ENRICHMENT_TASKS: set[asyncio.Task[Any]] = set()
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
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
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
        search_depth=getattr(active_settings, "web_enrichment_search_depth", "basic"),
        include_raw_content=bool(getattr(active_settings, "web_enrichment_include_raw_content", False)),
        snippet_char_limit=int(getattr(active_settings, "web_enrichment_snippet_char_limit", 1200) or 1200),
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


def _tokenize(value: str) -> set[str]:
    return {token for token in re.findall(r"\w+", value.lower()) if len(token) >= 3}


def _normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"\w+", str(value or "").lower()))


def _evidence_text_for_urls(evidence: list[dict[str, Any]], source_urls: list[str]) -> str:
    allowed_urls = set(source_urls)
    return " ".join(
        " ".join(
            [
                str(result.get("title") or ""),
                str(result.get("snippet") or ""),
                str(result.get("url") or ""),
            ]
        )
        for result in evidence
        if str(result.get("url") or "") in allowed_urls
    )


def _asserted_unverified_seller_features(
    draft: dict[str, Any],
    description: str,
    evidence: list[dict[str, Any]],
) -> list[str]:
    normalized_description = _normalized_phrase(description)
    evidence_tokens = _tokenize(_evidence_text_for_urls(evidence, [str(item.get("url") or "") for item in evidence]))
    assertions: list[str] = []
    for feature in draft.get("features") or []:
        claim = str(feature or "").strip()
        normalized_claim = _normalized_phrase(claim)
        claim_tokens = _tokenize(claim)
        if (
            normalized_claim
            and normalized_claim in normalized_description
            and claim_tokens
            and not claim_tokens.issubset(evidence_tokens)
        ):
            assertions.append(claim)
    return assertions


def _env_domain_suffixes(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    if raw is None:
        return ()
    domains: list[str] = []
    for value in str(raw).replace(";", ",").split(","):
        normalized = value.strip().lower().lstrip("*.")
        if normalized:
            domains.append(normalized)
    return tuple(dict.fromkeys(domains))


def _url_hostname(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return str(parsed.hostname or "").lower()


def _host_matches_suffixes(hostname: str, suffixes: tuple[str, ...]) -> bool:
    if not hostname or not suffixes:
        return False
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in suffixes)


def select_relevant_evidence(draft: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchor_tokens: set[str] = set()
    anchor_tokens.update(_tokenize(str(draft.get("title") or "")))
    anchor_tokens.update(_tokenize(str(draft.get("brand") or "")))
    anchor_tokens.update(_tokenize(str(draft.get("category_id") or "")))
    for feature in draft.get("features") or []:
        anchor_tokens.update(_tokenize(str(feature)))

    blocked_domains = _env_domain_suffixes("WEB_ENRICHMENT_BLOCKED_DOMAINS", DEFAULT_BLOCKED_EVIDENCE_DOMAINS)
    preferred_domains = _env_domain_suffixes("WEB_ENRICHMENT_PREFERRED_DOMAINS", "")

    scored: list[tuple[float, dict[str, Any], int, bool, bool]] = []
    for result in evidence:
        text = " ".join(
            [
                str(result.get("title") or ""),
                str(result.get("snippet") or ""),
                str(result.get("url") or ""),
            ]
        )
        tokens = _tokenize(text)
        overlap = len(tokens & anchor_tokens) if anchor_tokens else 0
        base_score = result.get("score")
        try:
            numeric_score = float(base_score) if base_score is not None else 0.0
        except (TypeError, ValueError):
            numeric_score = 0.0
        hostname = _url_hostname(str(result.get("url") or ""))
        is_blocked = _host_matches_suffixes(hostname, blocked_domains)
        is_preferred = _host_matches_suffixes(hostname, preferred_domains)
        score = overlap * 1.5 + numeric_score
        if is_preferred:
            score += 1.5
        if is_blocked:
            score -= 2.0
        scored.append((score, result, overlap, is_blocked, is_preferred))

    scored.sort(key=lambda item: item[0], reverse=True)
    non_blocked = [item for item in scored if not item[3]]
    candidates = non_blocked if non_blocked else scored
    preferred = [item[1] for item in candidates if item[4]]
    relevant = preferred + [item[1] for item in candidates if item[2] > 0 and not item[4]]
    if relevant:
        return relevant[:COMPACT_RESULT_LIMIT]
    return [item[1] for item in candidates[:COMPACT_RESULT_LIMIT]]


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


def _review_only_fallback_suggestions(results: list[dict[str, Any]], draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
    suggestions = build_suggested_fields_from_results(results, draft)
    evidence_summary = suggestions.get("attributes.web_evidence_summary")
    return {"attributes.web_evidence_summary": evidence_summary} if evidence_summary else {}


def _read_prompt(path: Any) -> str:
    return path.read_text(encoding="utf-8")


def _env_bounded_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


def _query_llm_timeout_seconds() -> int:
    return _env_bounded_int(
        "WEB_ENRICHMENT_QUERY_LLM_TIMEOUT_SECONDS",
        DEFAULT_QUERY_LLM_TIMEOUT_SECONDS,
        min_value=5,
        max_value=600,
    )


def _synthesis_llm_timeout_seconds() -> int:
    return _env_bounded_int(
        "WEB_ENRICHMENT_SYNTHESIS_LLM_TIMEOUT_SECONDS",
        DEFAULT_SYNTHESIS_LLM_TIMEOUT_SECONDS,
        min_value=10,
        max_value=1200,
    )


def _max_evidence_for_synthesis() -> int:
    return _env_bounded_int(
        "WEB_ENRICHMENT_MAX_EVIDENCE",
        DEFAULT_MAX_EVIDENCE_FOR_SYNTHESIS,
        min_value=1,
        max_value=COMPACT_RESULT_LIMIT,
    )


def _query_llm_max_tokens() -> int:
    return _env_bounded_int(
        "WEB_ENRICHMENT_QUERY_MAX_TOKENS",
        DEFAULT_QUERY_MAX_TOKENS,
        min_value=100,
        max_value=4000,
    )


def _synthesis_llm_max_tokens() -> int:
    return _env_bounded_int(
        "WEB_ENRICHMENT_SYNTHESIS_MAX_TOKENS",
        DEFAULT_SYNTHESIS_MAX_TOKENS,
        min_value=200,
        max_value=6000,
    )


def _request_hard_timeout_seconds() -> int:
    return _env_bounded_int(
        "WEB_ENRICHMENT_REQUEST_HARD_TIMEOUT_SECONDS",
        DEFAULT_REQUEST_HARD_TIMEOUT_SECONDS,
        min_value=60,
        max_value=3600,
    )


def _build_synthesis_fallback(
    draft: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    settings: Settings,
    warning: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    suggestions = _review_only_fallback_suggestions(evidence, draft)
    return (
        {
            "model": getattr(settings, "ollama_model", "qwen3:8b"),
            "prompt_version": SYNTHESIS_PROMPT_VERSION,
            "synthesis_source": "fallback_snippet_summary",
            "quality": "low",
            "enriched_description": "",
            "key_facts": [],
            "unsupported_claims": [],
            "warnings": [warning, "Fallback evidence is review-only and cannot replace the seller description."],
        },
        suggestions,
    )


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
        raw = call_qwen(prompt, max_tokens=_query_llm_max_tokens(), temperature=0.1, format_schema=_QUERY_SCHEMA)
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
    search_callable = getattr(provider, "search", None)
    search_is_async = bool(search_callable) and inspect.iscoroutinefunction(search_callable)

    async def run_one(query_item: dict[str, str]) -> dict[str, Any]:
        try:
            if search_is_async:
                response = provider.search(query_item["query"], max_results=max_results)
            else:
                response = await asyncio.to_thread(provider.search, query_item["query"], max_results=max_results)
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
    fallback_suggestions = _review_only_fallback_suggestions(evidence, draft)
    fallback = {
        "model": getattr(settings, "ollama_model", "qwen3:8b"),
        "prompt_version": SYNTHESIS_PROMPT_VERSION,
        "synthesis_source": "fallback_snippet_summary",
        "quality": "low",
        "enriched_description": "",
        "key_facts": [],
        "unsupported_claims": [],
        "warnings": [
            "LLM synthesis unavailable or invalid; review snippet-derived evidence carefully.",
            "Fallback evidence is review-only and cannot replace the seller description.",
        ],
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
    base_max_tokens = _synthesis_llm_max_tokens()
    compact_retry_prompt = (
        prompt
        + "\n\nRETRY REQUIREMENTS:\n"
        + "- Correct validation issues or expand a grounded short response as instructed below.\n"
        + "- Use a single paragraph targeting 120-180 words when EVIDENCE has enough supported detail; never pad with guesses.\n"
        + "- Return at most 4 key_facts.\n"
        + "- Each key_fact.value must be a short plain string, never an object or array.\n"
        + "- Never assert a claim in the description if you list it as unsupported.\n"
        + "- Do not assert seller-supplied features unless the evidence text explicitly supports them.\n"
        + "- Return valid JSON only and do not copy navigation text or markdown headings from evidence.\n"
    )
    failures: list[str] = []
    retry_feedback = ""
    valid_short_candidate: tuple[dict[str, Any], dict[str, dict[str, Any]]] | None = None
    for attempt_index in range(3):
        attempt_prompt = prompt if attempt_index == 0 else compact_retry_prompt + retry_feedback
        max_tokens = base_max_tokens if attempt_index == 0 else max(base_max_tokens, 1800)
        try:
            raw = call_qwen(
                attempt_prompt,
                max_tokens=max_tokens,
                temperature=0.1,
                format_schema=_SYNTHESIS_SCHEMA,
            )
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
                value = fact.get("value")
                if isinstance(value, dict) and len(value) == 1:
                    value = next(iter(value.values()))
                if isinstance(value, (dict, list)) or not str(value or "").strip():
                    continue
                value_tokens = _tokenize(str(value))
                cited_evidence_tokens = _tokenize(_evidence_text_for_urls(evidence, source_urls))
                if value_tokens and not value_tokens.issubset(cited_evidence_tokens):
                    continue
                key_facts.append(
                    {
                        "field": str(fact.get("field") or "").strip(),
                        "value": str(value).strip()[:240],
                        "confidence": confidence,
                        "source_urls": source_urls,
                    }
                )
            description = str(payload.get("enriched_description") or "").strip()
            if not description:
                raise ValueError("synthesis did not return enriched_description")
            normalized_description = description.lower()
            if "your cart is empty" in normalized_description or "# specifications" in normalized_description:
                raise ValueError("synthesis contains page-navigation text")
            warnings: list[str] = []
            unverified_features = _asserted_unverified_seller_features(draft, description, evidence)
            if unverified_features:
                warnings.append(
                    "Some seller features were not fully supported by evidence text: " + "; ".join(unverified_features)
                )
            unsupported_claims = [
                str(claim)[:300] for claim in payload.get("unsupported_claims") or [] if str(claim).strip()
            ]
            contradicted_claims = [
                claim for claim in unsupported_claims if claim.lower() in normalized_description
            ]
            if contradicted_claims:
                warnings.append("Description still includes unsupported claims: " + "; ".join(contradicted_claims))
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
                "unsupported_claims": unsupported_claims,
                "warnings": warnings,
            }
            description_word_count = len(description.split())
            evidence_word_count = len(_evidence_text_for_urls(evidence, sorted(allowed_urls)).split())
            has_expansion_material = (
                len(key_facts) >= 2 or evidence_word_count >= MIN_EXPANSION_EVIDENCE_WORDS
            )
            should_attempt_expansion = (
                attempt_index < 2
                and valid_short_candidate is None
                and has_expansion_material
                and quality in {"high", "medium"}
                and description_word_count < 120
            )
            if should_attempt_expansion:
                valid_short_candidate = (synthesis, suggestions)
                retry_feedback = (
                    "\n- The prior response was grounded but too brief for the available evidence. "
                    "Rewrite it as one fuller paragraph of 120-180 words, expanding only concrete details "
                    "supported by EVIDENCE. Do not add marketing filler or unsupported claims.\n"
                )
                continue
            if valid_short_candidate is not None and description_word_count < 120:
                synthesis["warnings"] = [
                    "Expanded synthesis remained shorter than preferred; retained only grounded details."
                ]
            return synthesis, suggestions
        except Exception as exc:
            failures.append(f"{exc.__class__.__name__}: {str(exc)[:120]}")
            if attempt_index >= 1 or valid_short_candidate is not None:
                break
    if valid_short_candidate is not None:
        synthesis, suggestions = valid_short_candidate
        synthesis["warnings"] = [
            "A longer grounded rewrite was rejected; retained the shorter validated description."
        ]
        return synthesis, suggestions
    fallback["warnings"].append("Synthesis attempts failed validation: " + "; ".join(failures))
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


def _track_background_task(task: asyncio.Task[Any]) -> None:
    _BACKGROUND_ENRICHMENT_TASKS.add(task)

    def _cleanup(done_task: asyncio.Task[Any]) -> None:
        _BACKGROUND_ENRICHMENT_TASKS.discard(done_task)
        try:
            done_task.result()
        except Exception:
            # The request record already captures failures; avoid bubbling task errors.
            return

    task.add_done_callback(_cleanup)


def _build_queued_request_doc(
    *,
    request_id: str,
    draft: dict[str, Any],
    provider_name: str,
    settings: Settings,
) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "request_id": request_id,
        "draft_id": str(draft.get("draft_id") or ""),
        "seller_id": draft.get("seller_id"),
        "provider": provider_name,
        "query": build_enrichment_query_from_draft(draft),
        "query_plan": {
            "model": getattr(settings, "ollama_model", "qwen3:8b"),
            "prompt_version": QUERY_PROMPT_VERSION,
            "planner_source": "pending",
            "queries": [],
        },
        "search_runs": [],
        "evidence": [],
        "synthesis": {
            "model": getattr(settings, "ollama_model", "qwen3:8b"),
            "prompt_version": SYNTHESIS_PROMPT_VERSION,
            "synthesis_source": "pending",
            "quality": "low",
            "enriched_description": "",
            "key_facts": [],
            "unsupported_claims": [],
            "warnings": [],
        },
        "status": "queued",
        "results": [],
        "suggested_fields": {},
        "applied_fields": [],
        "created_at": now,
        "updated_at": now,
        "error": None,
    }


async def _complete_request_web_enrichment(
    request_doc: dict[str, Any],
    *,
    draft: dict[str, Any],
    drafts_collection: Any,
    requests_collection: Any,
    settings: Settings,
    provider: WebEnrichmentProvider,
) -> dict[str, Any]:
    request_id = str(request_doc["request_id"])
    draft_id = str(request_doc["draft_id"])
    running_at = utc_now_iso()
    requests_collection.update_one(
        {"request_id": request_id},
        {"$set": {"status": "running", "updated_at": running_at}},
    )
    drafts_collection.update_one(
        {"draft_id": draft_id},
        {
            "$set": {
                "enrichment.latest_request_id": request_id,
                "enrichment.status": "running",
                "enrichment.provider": request_doc.get("provider"),
                "enrichment.updated_at": running_at,
                "updated_at": running_at,
            }
        },
    )

    try:
        enrichment_warnings: list[str] = []
        try:
            query_plan = await asyncio.wait_for(
                asyncio.to_thread(plan_enrichment_queries, draft, settings=settings),
                timeout=_query_llm_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            query_plan = _fallback_query_plan(draft, settings)
            enrichment_warnings.append("Query planner timed out; fallback template query was used.")

        search_runs, evidence, search_errors = await _run_searches(
            provider,
            query_plan,
            max_results=settings.tavily_max_results,
        )
        evidence = select_relevant_evidence(draft, evidence)[: _max_evidence_for_synthesis()]
        status = "completed" if evidence else "failed"

        try:
            synthesis, suggestions = await asyncio.wait_for(
                asyncio.to_thread(synthesize_enrichment, draft, evidence, settings=settings),
                timeout=_synthesis_llm_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            synthesis, suggestions = _build_synthesis_fallback(
                draft,
                evidence,
                settings=settings,
                warning="LLM synthesis timed out; fallback snippet-derived summary was used.",
            )
            enrichment_warnings.append("LLM synthesis timed out; fallback suggestions were used.")

        error = "; ".join(search_errors) if status == "failed" and search_errors else None
        if enrichment_warnings:
            error = "; ".join(part for part in [error, *enrichment_warnings] if part)

        finished_at = utc_now_iso()
        query_value = query_plan["queries"][0]["query"] if query_plan.get("queries") else request_doc.get("query", "")
        final_request_doc = {
            **request_doc,
            "query": query_value,
            "query_plan": query_plan,
            "search_runs": search_runs,
            "evidence": evidence,
            "synthesis": synthesis,
            "status": status,
            "results": evidence,
            "suggested_fields": suggestions if status == "completed" else {},
            "updated_at": finished_at,
            "error": error,
        }
        requests_collection.update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "query": final_request_doc["query"],
                    "query_plan": final_request_doc["query_plan"],
                    "search_runs": final_request_doc["search_runs"],
                    "evidence": final_request_doc["evidence"],
                    "synthesis": final_request_doc["synthesis"],
                    "status": final_request_doc["status"],
                    "results": final_request_doc["results"],
                    "suggested_fields": final_request_doc["suggested_fields"],
                    "error": final_request_doc["error"],
                    "updated_at": final_request_doc["updated_at"],
                }
            },
        )
        drafts_collection.update_one(
            {"draft_id": draft_id},
            {
                "$set": {
                    "enrichment.latest_request_id": request_id,
                    "enrichment.status": "available" if status == "completed" and suggestions else status,
                    "enrichment.provider": final_request_doc["provider"],
                    "enrichment.updated_at": finished_at,
                    "updated_at": finished_at,
                }
            },
        )
        return final_request_doc
    except Exception as exc:
        failed_at = utc_now_iso()
        failure_error = f"{exc.__class__.__name__}: {str(exc)[:240]}"
        requests_collection.update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "status": "failed",
                    "error": failure_error,
                    "updated_at": failed_at,
                }
            },
        )
        drafts_collection.update_one(
            {"draft_id": draft_id},
            {
                "$set": {
                    "enrichment.latest_request_id": request_id,
                    "enrichment.status": "failed",
                    "enrichment.updated_at": failed_at,
                    "updated_at": failed_at,
                }
            },
        )
        raise


async def request_web_enrichment_async(
    draft_id: str,
    *,
    drafts_collection: Any,
    requests_collection: Any,
    settings: Settings | None = None,
    provider: WebEnrichmentProvider | None = None,
    dry_run: bool = False,
    wait_for_completion: bool = False,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.enable_web_enrichment:
        return web_enrichment_disabled_response(active_settings)
    if provider is None and not _provider_configured(active_settings):
        return provider_not_configured_response(active_settings)
    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    request_id = f"enrich_{uuid.uuid4().hex}"
    active_provider = provider or build_provider(active_settings)
    request_doc = _build_queued_request_doc(
        request_id=request_id,
        draft=draft,
        provider_name=getattr(active_provider, "name", active_settings.web_enrichment_provider),
        settings=active_settings,
    )
    if dry_run:
        enrichment_warnings: list[str] = []
        try:
            query_plan = await asyncio.wait_for(
                asyncio.to_thread(plan_enrichment_queries, draft, settings=active_settings),
                timeout=_query_llm_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            query_plan = _fallback_query_plan(draft, active_settings)
            enrichment_warnings.append("Query planner timed out; fallback template query was used.")
        search_runs, evidence, search_errors = await _run_searches(
            active_provider,
            query_plan,
            max_results=active_settings.tavily_max_results,
        )
        evidence = select_relevant_evidence(draft, evidence)[: _max_evidence_for_synthesis()]
        status = "completed" if evidence else "failed"
        try:
            synthesis, suggestions = await asyncio.wait_for(
                asyncio.to_thread(synthesize_enrichment, draft, evidence, settings=active_settings),
                timeout=_synthesis_llm_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            synthesis, suggestions = _build_synthesis_fallback(
                draft,
                evidence,
                settings=active_settings,
                warning="LLM synthesis timed out; fallback snippet-derived summary was used.",
            )
            enrichment_warnings.append("LLM synthesis timed out; fallback suggestions were used.")
        error = "; ".join(search_errors) if status == "failed" and search_errors else None
        if enrichment_warnings:
            error = "; ".join(part for part in [error, *enrichment_warnings] if part)
        final_doc = {
            **request_doc,
            "query": query_plan["queries"][0]["query"] if query_plan.get("queries") else request_doc.get("query", ""),
            "query_plan": query_plan,
            "search_runs": search_runs,
            "evidence": evidence,
            "synthesis": synthesis,
            "status": status,
            "results": evidence,
            "suggested_fields": suggestions if status == "completed" else {},
            "updated_at": utc_now_iso(),
            "error": error,
        }
        return {
            "ok": final_doc.get("status") != "failed",
            "enabled": True,
            "status": final_doc.get("status"),
            "request": sanitize_enrichment_request(final_doc),
            "write_scope": [],
            "catalog_write_performed": False,
        }

    if not dry_run:
        inserted_request = False
        try:
            requests_collection.insert_one(dict(request_doc))
            inserted_request = True
            drafts_collection.update_one(
                {"draft_id": draft_id},
                {
                    "$set": {
                        "enrichment.latest_request_id": request_id,
                        "enrichment.status": "queued",
                        "enrichment.provider": request_doc["provider"],
                        "enrichment.updated_at": request_doc["updated_at"],
                        "updated_at": request_doc["updated_at"],
                    }
                },
            )
        except Exception:
            if inserted_request:
                _safe_delete_one(requests_collection, {"request_id": request_id})
            raise

    if wait_for_completion:
        try:
            final_doc = await asyncio.wait_for(
                _complete_request_web_enrichment(
                    request_doc,
                    draft=draft,
                    drafts_collection=drafts_collection,
                    requests_collection=requests_collection,
                    settings=active_settings,
                    provider=active_provider,
                ),
                timeout=_request_hard_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            failed_at = utc_now_iso()
            timeout_error = "Enrichment job timed out before completion."
            requests_collection.update_one(
                {"request_id": request_id},
                {"$set": {"status": "failed", "error": timeout_error, "updated_at": failed_at}},
            )
            drafts_collection.update_one(
                {"draft_id": draft_id},
                {
                    "$set": {
                        "enrichment.latest_request_id": request_id,
                        "enrichment.status": "failed",
                        "enrichment.updated_at": failed_at,
                        "updated_at": failed_at,
                    }
                },
            )
            failed_doc = dict(request_doc)
            failed_doc.update({"status": "failed", "error": timeout_error, "updated_at": failed_at})
            return {
                "ok": False,
                "enabled": True,
                "status": "failed",
                "request": sanitize_enrichment_request(failed_doc),
                "write_scope": ["web_enrichment_requests", "seller_product_drafts"],
                "catalog_write_performed": False,
            }
        return {
            "ok": final_doc.get("status") != "failed",
            "enabled": True,
            "status": final_doc.get("status"),
            "request": sanitize_enrichment_request(final_doc),
            "write_scope": [] if dry_run else ["web_enrichment_requests", "seller_product_drafts"],
            "catalog_write_performed": False,
        }

    async def _background_job() -> None:
        try:
            await asyncio.wait_for(
                _complete_request_web_enrichment(
                    request_doc,
                    draft=draft,
                    drafts_collection=drafts_collection,
                    requests_collection=requests_collection,
                    settings=active_settings,
                    provider=active_provider,
                ),
                timeout=_request_hard_timeout_seconds(),
            )
        except asyncio.TimeoutError:
            failed_at = utc_now_iso()
            timeout_error = "Enrichment job timed out before completion."
            requests_collection.update_one(
                {"request_id": request_id},
                {"$set": {"status": "failed", "error": timeout_error, "updated_at": failed_at}},
            )
            drafts_collection.update_one(
                {"draft_id": draft_id},
                {
                    "$set": {
                        "enrichment.latest_request_id": request_id,
                        "enrichment.status": "failed",
                        "enrichment.updated_at": failed_at,
                        "updated_at": failed_at,
                    }
                },
            )

    _track_background_task(asyncio.create_task(_background_job()))
    return {
        "ok": True,
        "enabled": True,
        "status": "queued",
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
            wait_for_completion=True,
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
