"""
Query processor for ColdStart Killer buyer search pipeline.

Transforms raw user queries (Vietnamese or English) into
search-ready fixture dicts consumable by search_pipeline.run_search().

Pipeline:
    raw query → language detection (Unicode codepoints)
             → translation to English (Qwen3 via Ollama, if Vietnamese)
             → price filter extraction (regex)
             → HyPE query construction (intent framing)
             → BM25 query construction (stop word removal)
             → embedding (BAAI/bge-m3 via src.embeddings)
             → fixture dict for run_search()
"""

from __future__ import annotations

import re
from typing import Any

from .embeddings import embed_one


ENGLISH_STOP_WORDS: frozenset[str] = frozenset(
    "a an and are at for in is of on or the to was were with".split()
)
_EXPECTED_EMBEDDING_DIM: int = 1024


def _require_non_empty_text(value: str, field_name: str) -> str:
    """Validate text is a non-empty string; raise ValueError if not."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def detect_language(text: str) -> str:
    """Detect Vietnamese vs English using Unicode codepoint ranges.

    Vietnamese characters occupy specific Unicode ranges:
    - U+1EA0-U+1EF9: Vietnamese-specific Latin Extended Additional
    - U+0110-U+0111: Đ/đ unique to Vietnamese

    Returns 'vi' if Vietnamese characters are detected, 'en' otherwise.
    """
    import unicodedata

    normalized = unicodedata.normalize("NFC", _require_non_empty_text(text, "text"))
    for char in normalized:
        cp = ord(char)
        if 0x1EA0 <= cp <= 0x1EF9 or cp in (0x0110, 0x0111):
            return "vi"

    vietnamese_combining_marks = {
        "COMBINING BREVE",
        "COMBINING CIRCUMFLEX ACCENT",
        "COMBINING HORN",
        "COMBINING GRAVE ACCENT",
        "COMBINING ACUTE ACCENT",
        "COMBINING TILDE",
        "COMBINING HOOK ABOVE",
        "COMBINING DOT BELOW",
    }
    for char in unicodedata.normalize("NFD", normalized):
        if unicodedata.combining(char) and unicodedata.name(char, "") in vietnamese_combining_marks:
            return "vi"
    return "en"


def translate_to_english(text: str) -> str:
    """Translate Vietnamese query to English using Qwen3 via Ollama; English text is returned unchanged."""
    normalized = _require_non_empty_text(text, "text")
    if detect_language(normalized) == "en":
        return normalized

    prompt = (
        "Translate this Vietnamese product search query into natural English for e-commerce search. "
        "Keep brand names, model names, product numbers, and prices unchanged. "
        "Return only the translated query, with no explanation and no quotes.\n\n"
        f"Query: {normalized}"
    )
    from .llm_client import call_qwen

    translated_raw = call_qwen(prompt, max_tokens=120, temperature=0.0)
    if not isinstance(translated_raw, str):
        raise RuntimeError("call_qwen must return a translated string")
    translated = translated_raw.strip()
    translated = translated.strip("` \n\t\"'")
    return translated or normalized


def _normalize_for_matching(text: str) -> str:
    """Normalize text for regex-based filter extraction."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _parse_amount_to_vnd(raw_amount: str, suffix: str | None = None) -> int:
    """Parse a user-written VND amount into an integer VND value."""
    cleaned = raw_amount.strip().lower().replace(" ", "")
    has_k_suffix = cleaned.endswith("k") or (suffix and suffix.lower() == "k")
    cleaned = cleaned.rstrip("k")
    cleaned = cleaned.replace(",", ".")

    if "." in cleaned:
        parts = cleaned.split(".")
        if len(parts[-1]) == 3 and all(part.isdigit() for part in parts):
            number = int("".join(parts))
        else:
            number = float(cleaned)
    else:
        number = int(cleaned)

    if has_k_suffix:
        number = float(number) * 1000
    return int(number)


def _set_price_range(filters: dict[str, Any], lower: int | None = None, upper: int | None = None) -> None:
    """Set price_min and/or price_max on the hard filter dictionary."""
    if lower is not None:
        filters["price_min"] = int(lower)
    if upper is not None:
        filters["price_max"] = int(upper)


def extract_hard_filters(text: str) -> dict:
    """Extract explicit price filters from the original query text."""
    normalized = _normalize_for_matching(_require_non_empty_text(text, "text"))
    filters: dict[str, Any] = {"in_stock": True}

    range_match = re.search(
        r"(?:trong\s+khoảng|khoảng|between|from)\s+(\d+(?:[.,]\d+)?)(k?)\s*(?:vnd|đ|dong)?\s*(?:-|đến|den|to|and)\s*(\d+(?:[.,]\d+)?)(k?)\s*(?:vnd|đ|dong)?",
        normalized,
    )
    if range_match:
        min_suffix = range_match.group(2) or range_match.group(4)
        max_suffix = range_match.group(4) or range_match.group(2)
        price_min = _parse_amount_to_vnd(range_match.group(1), min_suffix)
        price_max = _parse_amount_to_vnd(range_match.group(3), max_suffix)
        if price_min > price_max:
            price_min, price_max = price_max, price_min
        _set_price_range(filters, lower=price_min, upper=price_max)

    max_match = re.search(
        r"(?:dưới|duoi|under|below|less than|<=|tối đa|toi da)\s*(\d+(?:[.,]\d+)?k?)\s*(?:vnd|đ|dong)?",
        normalized,
    )
    if max_match:
        _set_price_range(filters, upper=_parse_amount_to_vnd(max_match.group(1)))

    min_match = re.search(
        r"(?:trên|tren|over|above|more than|>=|từ|tu)\s*(\d+(?:[.,]\d+)?k?)\s*(?:vnd|đ|dong)?",
        normalized,
    )
    if min_match and not range_match:
        _set_price_range(filters, lower=_parse_amount_to_vnd(min_match.group(1)))

    return filters


def build_hype_query(english_query: str) -> str:
    """Build a semantic HyPE-style English search query with intent/persona/function framing."""
    query = _require_non_empty_text(english_query, "english_query")
    return f"user looking for {query} for everyday use"


def build_bm25_query(english_query: str) -> str:
    """Build a keyword-optimized BM25 query by keeping product terms and removing stop words."""
    query = _require_non_empty_text(english_query, "english_query")
    tokens = re.findall(r"[a-zA-Z0-9+.#-]+", query.lower())
    kept = [token for token in tokens if token not in ENGLISH_STOP_WORDS and len(token) > 1]
    return " ".join(dict.fromkeys(kept)) or query


def process_query(raw_query: str) -> dict:
    """Convert a raw buyer query into an in-memory fixture directly usable by run_search()."""
    original = _require_non_empty_text(raw_query, "raw_query")

    language_detected = detect_language(original)
    english_query = translate_to_english(original)
    hard_filters = extract_hard_filters(original)
    hype_search_query_en = build_hype_query(english_query)
    bm25_search_query_en = build_bm25_query(english_query)
    query_embedding = embed_one(hype_search_query_en)
    if not isinstance(query_embedding, list) or len(query_embedding) != _EXPECTED_EMBEDDING_DIM:
        raise RuntimeError(f"embed_one must return a {_EXPECTED_EMBEDDING_DIM}-dimensional embedding list")
    import math

    try:
        finite_embedding = all(math.isfinite(float(value)) for value in query_embedding)
    except (TypeError, ValueError):
        finite_embedding = False
    if not finite_embedding:
        raise ValueError(
            "Embedding contains non-finite values (NaN or Inf). "
            "This indicates an embedding model error."
        )

    return {
        "original_query": original,
        "language_detected": language_detected,
        "english_query": english_query,
        "hype_search_query_en": hype_search_query_en,
        "bm25_search_query_en": bm25_search_query_en,
        "hard_filters": hard_filters,
        "query_embedding": query_embedding,
    }
