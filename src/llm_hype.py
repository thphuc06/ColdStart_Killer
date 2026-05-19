from __future__ import annotations

import logging
from typing import Any

from .config import PROJECT_ROOT, get_settings
from .llm_client import call_qwen, expect_list_json, extract_json_from_text
from .normalize_amazon import clean_string
from .utils import read_text_file


logger = logging.getLogger(__name__)

PROMPT_PATH = PROJECT_ROOT / "prompts" / "generate_hype.txt"
REQUIRED_ASPECTS = ["function", "persona", "occasion"]
OPTIONAL_ASPECTS = {"constraint", "compatibility", "style", "gift", "spec", "problem"}
ALLOWED_ASPECTS = set(REQUIRED_ASPECTS) | OPTIONAL_ASPECTS


def _prompt(item: dict[str, Any], propositions: list[dict]) -> str:
    template = read_text_file(PROMPT_PATH)
    facts = "\n".join(f"- {prop.get('raw_text', '')}" for prop in propositions)
    return template.format(
        title=item.get("title_en") or item.get("title") or "",
        brand=item.get("brand") or item.get("brand_candidate") or "",
        category=item.get("raw_main_category") or item.get("main_category") or item.get("category_id") or "",
        price_bucket=item.get("price_bucket") or "unknown",
        propositions=facts,
        product_text_for_llm=item.get("product_text_for_llm", ""),
    )


def _fallback_for_aspect(aspect: str, item: dict[str, Any]) -> dict:
    title = clean_string(item.get("title_en") or item.get("title")) or "product"
    category = clean_string(item.get("raw_main_category") or item.get("main_category") or item.get("category_id")) or "category"
    templates = {
        "function": "{title} for {category} use",
        "persona": "{title} for users who need {category} products",
        "occasion": "{title} for everyday {category} use",
    }
    return {
        "aspect": aspect,
        "raw_text": templates[aspect].format(title=title, category=category),
        "confidence": 0.60,
        "source": "fallback_template",
    }


def _validate_queries(items: list[Any]) -> list[dict]:
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        text = clean_string(item.get("raw_text") or item.get("query") or item.get("text"))
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        aspect = clean_string(item.get("aspect") or "function")
        if aspect not in ALLOWED_ASPECTS:
            aspect = "function"
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        cleaned.append(
            {
                "aspect": aspect,
                "raw_text": text,
                "confidence": confidence,
                "source": clean_string(item.get("source")) or "llm",
            }
        )
        if len(cleaned) >= 6:
            break
    return cleaned


def generate_hype_queries_llm(item: dict, propositions: list[dict]) -> list[dict]:
    prompt = _prompt(item, propositions)
    output = call_qwen(prompt, max_tokens=700, temperature=0.2)
    parsed = extract_json_from_text(output)
    queries = _validate_queries(expect_list_json(parsed))

    present = {query["aspect"] for query in queries}
    for aspect in REQUIRED_ASPECTS:
        if aspect not in present:
            logger.warning("Adding fallback HyPE %s query for item %s", aspect, item.get("_id") or item.get("parent_asin"))
            queries.append(_fallback_for_aspect(aspect, item))
            present.add(aspect)

    required = [query for query in queries if query["aspect"] in REQUIRED_ASPECTS]
    optional = [query for query in queries if query["aspect"] not in REQUIRED_ASPECTS]
    return (required + optional)[:6]


def generation_model_name() -> str:
    return get_settings().ollama_model

