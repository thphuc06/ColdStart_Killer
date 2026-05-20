from __future__ import annotations

import re
from typing import Any

from .embeddings import embed_one
from .llm_client import call_qwen


VIETNAMESE_DIACRITICS = set(
    "ăâđêôơư"
    "áàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệ"
    "íìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
    "ĂÂĐÊÔƠƯ"
    "ÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆ"
    "ÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
)

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "best",
    "by",
    "for",
    "from",
    "good",
    "great",
    "i",
    "in",
    "is",
    "it",
    "looking",
    "me",
    "my",
    "need",
    "of",
    "on",
    "or",
    "please",
    "product",
    "products",
    "the",
    "to",
    "under",
    "use",
    "user",
    "want",
    "with",
}

CATEGORY_KEYWORDS = [
    (
        "all_beauty",
        (
            "beauty",
            "làm đẹp",
            "lam dep",
            "kem",
            "mỹ phẩm",
            "my pham",
            "skincare",
            "skin care",
            "moisturizer",
            "cream",
            "serum",
            "toner",
            "sunscreen",
        ),
    ),
    (
        "cell_phones_and_accessories",
        (
            "phone",
            "điện thoại",
            "dien thoai",
            "samsung",
            "iphone",
            "galaxy",
            "pixel",
            "case",
            "ốp",
            "op lung",
        ),
    ),
    (
        "all_electronics",
        (
            "electronics",
            "điện tử",
            "dien tu",
            "tai nghe",
            "headphone",
            "earbud",
            "earbuds",
            "charger",
            "sạc",
            "sac",
            "wireless",
            "bluetooth",
            "speaker",
        ),
    ),
    (
        "amazon_fashion",
        (
            "fashion",
            "thời trang",
            "thoi trang",
            "váy",
            "vay",
            "đầm",
            "dam",
            "áo",
            "ao",
            "giày",
            "giay",
            "dress",
            "shirt",
            "shoes",
            "watch",
        ),
    ),
]

SYNONYM_KEYWORDS = {
    "noise cancelling": ["noise cancellation", "anc", "quiet listening"],
    "chống ồn": ["noise cancelling", "noise cancellation", "anc"],
    "tai nghe": ["earbuds", "headphones", "bluetooth audio"],
    "wireless": ["cordless", "bluetooth"],
    "charger": ["charging", "adapter", "power"],
    "sạc": ["charger", "charging", "adapter"],
    "dry skin": ["hydrating", "moisturizing"],
    "da khô": ["dry skin", "hydrating", "moisturizing"],
    "oily skin": ["oil control", "non greasy"],
    "da dầu": ["oily skin", "oil control", "non greasy"],
    "gift": ["present", "birthday"],
    "quà": ["gift", "present", "birthday"],
}


def detect_language(text: str) -> str:
    """Detect if query is Vietnamese or English using Vietnamese diacritic heuristics."""
    return "vi" if any(char in VIETNAMESE_DIACRITICS for char in text) else "en"


def translate_to_english(text: str) -> str:
    """Translate Vietnamese query to English using Qwen3 via Ollama; English text is returned unchanged."""
    normalized = text.strip()
    if not normalized:
        return ""
    if detect_language(normalized) == "en":
        return normalized

    prompt = (
        "Translate this Vietnamese product search query into natural English for e-commerce search. "
        "Keep brand names, model names, product numbers, and prices unchanged. "
        "Return only the translated query, with no explanation and no quotes.\n\n"
        f"Query: {normalized}"
    )
    translated = call_qwen(prompt, max_tokens=120, temperature=0.0).strip()
    translated = translated.strip("` \n\t\"'")
    return translated or normalized


def _normalize_for_matching(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _parse_amount_to_vnd(raw_amount: str, suffix: str | None = None) -> int:
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
    if lower is not None:
        filters["price_min"] = int(lower)
        filters["min_price_vnd"] = int(lower)
    if upper is not None:
        filters["price_max"] = int(upper)
        filters["max_price_vnd"] = int(upper)


def extract_hard_filters(text: str) -> dict:
    """Extract price/category filters from the original query text."""
    normalized = _normalize_for_matching(text)
    filters: dict[str, Any] = {"in_stock": True}

    range_match = re.search(
        r"(?:trong\s+khoảng|khoảng|between|from)\s+(\d+(?:[.,]\d+)?)(k?)\s*(?:-|đến|den|to|and)\s*(\d+(?:[.,]\d+)?)(k?)",
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
        r"(?:dưới|duoi|under|below|less than|<=|tối đa|toi da)\s*(\d+(?:[.,]\d+)?k?)",
        normalized,
    )
    if max_match:
        _set_price_range(filters, upper=_parse_amount_to_vnd(max_match.group(1)))

    min_match = re.search(
        r"(?:trên|tren|over|above|more than|>=|từ|tu)\s*(\d+(?:[.,]\d+)?k?)",
        normalized,
    )
    if min_match and not range_match:
        _set_price_range(filters, lower=_parse_amount_to_vnd(min_match.group(1)))

    for category_id, keywords in CATEGORY_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            filters["category_id"] = category_id
            break

    return filters


def build_hype_query(english_query: str) -> str:
    """Build a semantic HyPE-style English search query with intent/persona/function framing."""
    query = english_query.strip()
    if not query:
        return ""

    normalized = _normalize_for_matching(query)
    expansions: list[str] = []
    for keyword, synonyms in SYNONYM_KEYWORDS.items():
        if keyword in normalized:
            expansions.extend(synonym for synonym in synonyms if synonym not in normalized)

    intent_bits = ["user looking for", query, "with reliable quality for everyday use"]
    if any(word in normalized for word in ("gift", "birthday", "present")):
        intent_bits.append("as a thoughtful gift")
    if any(word in normalized for word in ("under", "below", "cheap", "budget", "affordable")):
        intent_bits.append("within a budget")
    if expansions:
        intent_bits.append("related needs: " + ", ".join(dict.fromkeys(expansions)))

    return " ".join(part for part in intent_bits if part).strip()


def build_bm25_query(english_query: str) -> str:
    """Build a keyword-optimized BM25 query by keeping product terms and removing stop words."""
    tokens = re.findall(r"[a-zA-Z0-9+.#-]+", english_query.lower())
    kept = [token for token in tokens if token not in STOP_WORDS and len(token) > 1]
    return " ".join(dict.fromkeys(kept)) or english_query.strip()


def process_query(raw_query: str) -> dict:
    """Convert a raw buyer query into an in-memory fixture directly usable by run_search()."""
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ValueError("raw_query must be a non-empty string")
    original = raw_query.strip()

    language_detected = detect_language(original)
    english_query = translate_to_english(original)
    hard_filters = extract_hard_filters(original)
    hype_search_query_en = build_hype_query(english_query)
    bm25_search_query_en = build_bm25_query(english_query)
    query_embedding = embed_one(hype_search_query_en)

    return {
        "original_query": original,
        "language_detected": language_detected,
        "english_query": english_query,
        "hype_search_query_en": hype_search_query_en,
        "bm25_search_query_en": bm25_search_query_en,
        "hard_filters": hard_filters,
        "query_embedding": query_embedding,
    }
