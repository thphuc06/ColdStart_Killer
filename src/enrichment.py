from __future__ import annotations

import logging
from typing import Any

import requests

from .config import PROJECT_ROOT, get_settings
from .llm_client import call_qwen, extract_json_from_text
from .normalize_amazon import clean_string
from .utils import read_text_file


logger = logging.getLogger(__name__)

PROMPT_PATH = PROJECT_ROOT / "prompts" / "enrich_description.txt"
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _low_quality(note: str) -> dict:
    return {
        "enrichment_quality": "low",
        "enriched_description": "",
        "key_facts": [],
        "enrichment_note": note,
    }


def build_enrichment_queries(item: dict) -> list[str]:
    title = clean_string(item.get("title_en") or item.get("title"))
    brand = clean_string(item.get("brand") or item.get("brand_candidate"))
    category = clean_string(item.get("raw_main_category") or item.get("main_category") or item.get("category_id"))
    queries = []
    if title and brand:
        queries.append(f"{brand} {title} product details")
    if title:
        queries.append(f"{title} specifications")
    if title and category:
        queries.append(f"{title} {category} features")
    return queries[:3]


def brave_search(query: str, max_results: int = 3) -> list[dict]:
    settings = get_settings()
    if not settings.brave_api_key:
        return []
    try:
        response = requests.get(
            BRAVE_ENDPOINT,
            headers={"Accept": "application/json", "X-Subscription-Token": settings.brave_api_key},
            params={"q": query, "count": max_results},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("web", {}).get("results", [])
        return [
            {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "description": result.get("description", ""),
            }
            for result in results[:max_results]
        ]
    except Exception as exc:
        logger.warning("Brave Search failed for query %r: %s", query, exc)
        return []


def format_search_results(results: list[dict]) -> str:
    lines = []
    for idx, result in enumerate(results, start=1):
        lines.append(
            f"[{idx}] {result.get('title', '')}\nURL: {result.get('url', '')}\nSnippet: {result.get('description', '')}"
        )
    return "\n\n".join(lines)


def agentic_web_enrich(item: dict) -> dict:
    settings = get_settings()
    if not settings.brave_api_key:
        return _low_quality("BRAVE_API_KEY missing. Web enrichment skipped.")

    queries = build_enrichment_queries(item)
    results: list[dict] = []
    for query in queries:
        results.extend(brave_search(query, max_results=3))
    if not results:
        return _low_quality("Brave Search returned no usable results. Web enrichment skipped.")

    prompt = read_text_file(PROMPT_PATH).format(
        title=item.get("title_en") or item.get("title") or "",
        brand=item.get("brand") or item.get("brand_candidate") or "",
        category=item.get("raw_main_category") or item.get("main_category") or item.get("category_id") or "",
        search_results=format_search_results(results),
    )
    try:
        payload = extract_json_from_text(call_qwen(prompt, max_tokens=700, temperature=0.1))
    except Exception as exc:
        logger.warning("LLM enrichment failed: %s", exc)
        return _low_quality("LLM enrichment failed. Product insertion can continue without web enrichment.")

    if not isinstance(payload, dict):
        return _low_quality("LLM enrichment did not return valid JSON.")
    quality = clean_string(payload.get("enrichment_quality")).lower()
    if quality not in {"low", "medium", "high"}:
        quality = "low"
    return {
        "enrichment_quality": quality,
        "enriched_description": clean_string(payload.get("enriched_description")),
        "key_facts": payload.get("key_facts") if isinstance(payload.get("key_facts"), list) else [],
        "enrichment_note": clean_string(payload.get("enrichment_note")) or "Generated from Brave Search snippets.",
    }

