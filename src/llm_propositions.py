from __future__ import annotations

import logging
import re
from typing import Any

from .config import PROJECT_ROOT, get_settings
from .llm_client import call_qwen, expect_list_json, extract_json_from_text
from .normalize_amazon import clean_string, listify_text
from .utils import read_text_file


logger = logging.getLogger(__name__)

PROMPT_PATH = PROJECT_ROOT / "prompts" / "extract_propositions.txt"
ALLOWED_TYPES = {
    "spec",
    "benefit",
    "target_user",
    "usage",
    "constraint",
    "package",
    "compatibility",
    "material",
    "ingredient",
}


def _prompt(item: dict[str, Any]) -> str:
    template = read_text_file(PROMPT_PATH)
    return template.format(
        title=item.get("title_en") or item.get("title") or "",
        brand=item.get("brand") or item.get("brand_candidate") or "",
        category=item.get("raw_main_category") or item.get("main_category") or item.get("category_id") or "",
        product_text_for_llm=item.get("product_text_for_llm", ""),
    )


def _source_text_value(item: dict[str, Any], key: str) -> str:
    source_text = item.get("source_text")
    if isinstance(source_text, dict):
        value = source_text.get(key)
        if value:
            return clean_string(value)
    return clean_string(item.get(key))


def _section_from_product_text(product_text: str, section_name: str) -> str:
    pattern = rf"{re.escape(section_name)}:\s*(.*?)(?:\n\n[A-Z][A-Za-z ]+:\s*|\Z)"
    match = re.search(pattern, product_text, flags=re.DOTALL)
    return clean_string(match.group(1)) if match else ""


def _sentence_candidates(text: str, source_field: str, proposition_type: str) -> list[dict]:
    candidates = []
    for line in re.split(r"[\n.;]+", text):
        cleaned = clean_string(line)
        if not cleaned or len(cleaned.split()) < 3:
            continue
        candidates.append(
            {
                "proposition_type": proposition_type,
                "raw_text": cleaned,
                "source_field": source_field,
            }
        )
    return candidates


def _fallback_propositions(item: dict[str, Any]) -> list[dict]:
    title = clean_string(item.get("title_en") or item.get("title"))
    category = clean_string(item.get("raw_main_category") or item.get("main_category") or item.get("category_id"))
    product_text = str(item.get("product_text_for_llm") or "")
    features_text = _source_text_value(item, "features_text") or _section_from_product_text(product_text, "Features")
    description_text = _source_text_value(item, "description_text") or _section_from_product_text(
        product_text, "Description"
    )
    details_text = _source_text_value(item, "details_text") or _section_from_product_text(product_text, "Details")
    features = listify_text(features_text or item.get("features"))
    facts = []
    if title:
        facts.append({"proposition_type": "spec", "raw_text": f"The product is {title}.", "source_field": "title"})
    if category:
        facts.append(
            {
                "proposition_type": "usage",
                "raw_text": f"The product belongs to the {category} category.",
                "source_field": "mixed",
            }
        )
    for feature in features[:6]:
        facts.append({"proposition_type": "benefit", "raw_text": feature, "source_field": "features"})
    facts.extend(_sentence_candidates(description_text, source_field="description", proposition_type="benefit"))
    facts.extend(_sentence_candidates(details_text, source_field="details", proposition_type="spec"))
    fallback = []
    seen: set[str] = set()
    for fact in facts:
        text = clean_string(fact["raw_text"])
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        fallback.append(
            {
                "proposition_type": fact["proposition_type"],
                "raw_text": text,
                "confidence": 0.60,
                "source": "fallback_template",
                "source_field": fact["source_field"],
            }
        )
        if len(fallback) >= 8:
            break
    return fallback[:8]


def _validate_propositions(items: list[Any]) -> list[dict]:
    seen: set[str] = set()
    cleaned: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = clean_string(item.get("raw_text") or item.get("text") or item.get("proposition"))
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.60:
            continue
        proposition_type = clean_string(item.get("proposition_type") or item.get("type") or "spec")
        if proposition_type not in ALLOWED_TYPES:
            proposition_type = "spec"
        cleaned.append(
            {
                "proposition_type": proposition_type,
                "raw_text": text,
                "confidence": confidence,
                "source": clean_string(item.get("source")) or "llm",
                "source_field": clean_string(item.get("source_field")) or "mixed",
            }
        )
        if len(cleaned) >= 8:
            break
    return cleaned


def extract_propositions_llm(item: dict) -> list[dict]:
    prompt = _prompt(item)
    output = call_qwen(prompt, max_tokens=900, temperature=0.1)
    parsed = extract_json_from_text(output)
    propositions = _validate_propositions(expect_list_json(parsed))
    if len(propositions) < 3:
        logger.warning("Using fallback propositions for item %s", item.get("_id") or item.get("parent_asin"))
        fallback = _fallback_propositions(item)
        existing = {prop["raw_text"].lower() for prop in propositions}
        for prop in fallback:
            if prop["raw_text"].lower() not in existing:
                propositions.append(prop)
                existing.add(prop["raw_text"].lower())
            if len(propositions) >= 3:
                break
    if len(propositions) < 3:
        raise ValueError(
            f"Could not produce at least 3 grounded propositions for item {item.get('_id') or item.get('parent_asin')}"
        )
    return propositions[:8]


def generation_model_name() -> str:
    return get_settings().ollama_model
