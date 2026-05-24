from __future__ import annotations

import math
import re
from typing import Any, Literal


QueryType = Literal["specific", "constraint_rich", "normal", "broad", "exploratory"]


SEARCH_DEFAULT_WEIGHTS: dict[str, float] = {
    "query_hybrid": 0.70,
    "profile": 0.12,
    "cf": 0.08,
    "metadata": 0.05,
    "cold_explore": 0.05,
}

SEARCH_DYNAMIC_WEIGHTS: dict[QueryType, dict[str, float]] = {
    "specific": {
        "query_hybrid": 0.82,
        "profile": 0.06,
        "cf": 0.04,
        "metadata": 0.05,
        "cold_explore": 0.03,
    },
    "constraint_rich": {
        "query_hybrid": 0.76,
        "profile": 0.08,
        "cf": 0.05,
        "metadata": 0.07,
        "cold_explore": 0.04,
    },
    "normal": dict(SEARCH_DEFAULT_WEIGHTS),
    "broad": {
        "query_hybrid": 0.58,
        "profile": 0.20,
        "cf": 0.10,
        "metadata": 0.07,
        "cold_explore": 0.05,
    },
    "exploratory": {
        "query_hybrid": 0.50,
        "profile": 0.25,
        "cf": 0.10,
        "metadata": 0.05,
        "cold_explore": 0.10,
    },
}

HOMEPAGE_DEFAULT_WEIGHTS: dict[str, float] = {
    "profile": 0.40,
    "semantic_neighbor": 0.20,
    "cf": 0.15,
    "metadata": 0.10,
    "cold_explore": 0.10,
    "quality": 0.05,
}

SIMILAR_DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic_neighbor": 0.50,
    "cf": 0.25,
    "profile": 0.10,
    "metadata": 0.05,
    "quality": 0.10,
}

_EXPLORATORY_PHRASES = {
    "gift ideas",
    "gift idea",
    "something nice",
    "something useful",
    "recommend me",
    "recommend",
    "surprise me",
    "explore",
    "browse",
    "discovery",
}

_EXPLORATORY_TOKENS = {
    "gift",
    "ideas",
    "idea",
    "explore",
    "browse",
    "discover",
    "interesting",
    "recommend",
    "recommendation",
}

_CONSTRAINT_TERMS = {
    "under",
    "below",
    "over",
    "above",
    "between",
    "from",
    "budget",
    "cheap",
    "premium",
    "compatible",
    "compatibility",
    "for",
    "without",
    "with",
}

_SPECIFIC_BRANDS = {
    "iphone",
    "samsung",
    "xiaomi",
    "anker",
    "apple",
    "sony",
    "bose",
    "cerave",
    "cetaphil",
    "nivea",
}

_BROAD_CATEGORY_TOKENS = {
    "skincare",
    "beauty",
    "makeup",
    "gift",
    "charger",
    "cable",
    "earbuds",
    "audio",
    "accessories",
    "accessory",
    "phone",
    "case",
    "cream",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.-]+", text.lower())


def rank_normalize(scores: list[float]) -> list[float]:
    if not scores:
        return []

    normalized_scores = [_safe_float(score, 0.0) for score in scores]
    if max(normalized_scores, default=0.0) <= 0:
        return [0.0] * len(scores)

    indexed = sorted(
        enumerate(normalized_scores),
        key=lambda item: (item[1], -item[0]),
        reverse=True,
    )
    normalized = [0.0] * len(scores)
    for rank, (index, _score) in enumerate(indexed, start=1):
        normalized[index] = round(1.0 / rank, 6)
    return normalized


def cosine_to_score(raw_cosine: Any) -> float:
    cosine = _safe_float(raw_cosine, -1.0)
    return round(_clamp01((cosine + 1.0) / 2.0), 6)


def classify_query_type(raw_query: str, hard_filters: dict[str, Any] | None = None) -> QueryType:
    text = str(raw_query or "").strip().lower()
    if not text:
        return "broad"

    hard_filters = hard_filters or {}
    tokens = _tokenize(text)
    token_set = set(tokens)
    has_price_filter = any(
        hard_filters.get(field_name) is not None
        for field_name in ("price_min", "price_max", "min_price_vnd", "max_price_vnd", "price_bucket")
    )
    has_constraint_token = any(token in _CONSTRAINT_TERMS for token in token_set)
    has_specific_brand = any(token in _SPECIFIC_BRANDS for token in token_set)
    has_model_token = any(bool(re.search(r"\d", token)) or "-" in token for token in tokens)
    exploratory_phrase = any(phrase in text for phrase in _EXPLORATORY_PHRASES)
    exploratory_token = any(token in _EXPLORATORY_TOKENS for token in token_set)
    broad_token_count = sum(1 for token in token_set if token in _BROAD_CATEGORY_TOKENS)

    if exploratory_phrase or (exploratory_token and len(tokens) <= 4):
        return "exploratory"
    if has_price_filter or has_constraint_token:
        return "constraint_rich"
    if has_model_token or has_specific_brand:
        return "specific"
    if len(tokens) <= 2 or broad_token_count >= max(1, len(tokens) - 1):
        return "broad"
    return "normal"


def get_search_weights(query_type: str) -> dict[str, float]:
    if query_type not in SEARCH_DYNAMIC_WEIGHTS:
        return dict(SEARCH_DEFAULT_WEIGHTS)
    return dict(SEARCH_DYNAMIC_WEIGHTS[query_type])


def _normalized_input(candidates: list[dict[str, Any]], raw_field: str) -> list[float]:
    return [_safe_float(candidate.get(raw_field), 0.0) for candidate in candidates]


def score_candidate_batch(
    candidates: list[dict[str, Any]],
    weights: dict[str, float],
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    query_norm = rank_normalize(_normalized_input(candidates, "query_hybrid_score_raw"))
    semantic_norm = rank_normalize(_normalized_input(candidates, "semantic_neighbor_score_raw"))
    cf_norm = rank_normalize(_normalized_input(candidates, "item_item_cf_score_raw"))

    scored: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        profile_raw = _safe_float(candidate.get("profile_score_raw"), -1.0)
        metadata_raw = _safe_float(candidate.get("metadata_score_raw"), 0.0)
        cold_start_raw = _safe_float(candidate.get("cold_start_boost_raw"), 0.0)
        exploration_raw = _safe_float(candidate.get("exploration_score_raw"), 0.0)
        quality_raw = _safe_float(candidate.get("quality_score_raw"), 0.0)
        seen_penalty = _clamp01(_safe_float(candidate.get("seen_penalty"), 0.0))
        negative_penalty = _clamp01(_safe_float(candidate.get("negative_penalty"), 0.0))

        profile_score = cosine_to_score(profile_raw)
        metadata_score = round(_clamp01(metadata_raw), 6)
        cold_start_score = round(_clamp01(cold_start_raw), 6)
        exploration_score = round(_clamp01(exploration_raw), 6)
        quality_score = round(_clamp01(quality_raw), 6)

        final_score = (
            (_safe_float(weights.get("query_hybrid"), 0.0) * query_norm[index])
            + (_safe_float(weights.get("profile"), 0.0) * profile_score)
            + (_safe_float(weights.get("semantic_neighbor"), 0.0) * semantic_norm[index])
            + (_safe_float(weights.get("cf"), 0.0) * cf_norm[index])
            + (_safe_float(weights.get("metadata"), 0.0) * metadata_score)
            + (_safe_float(weights.get("cold_explore"), 0.0) * max(cold_start_score, exploration_score))
            + (_safe_float(weights.get("quality"), 0.0) * quality_score)
            - seen_penalty
            - negative_penalty
        )

        score_breakdown = {
            "query_hybrid_score": round(query_norm[index], 6),
            "query_hybrid_score_raw": round(_safe_float(candidate.get("query_hybrid_score_raw"), 0.0), 6),
            "profile_score": profile_score,
            "profile_score_raw": round(profile_raw, 6),
            "semantic_neighbor_score": round(semantic_norm[index], 6),
            "semantic_neighbor_score_raw": round(
                _safe_float(candidate.get("semantic_neighbor_score_raw"), 0.0), 6
            ),
            "item_item_cf_score": round(cf_norm[index], 6),
            "item_item_cf_score_raw": round(_safe_float(candidate.get("item_item_cf_score_raw"), 0.0), 6),
            "metadata_score": metadata_score,
            "metadata_score_raw": round(metadata_raw, 6),
            "cold_start_boost": cold_start_score,
            "cold_start_boost_raw": round(cold_start_raw, 6),
            "exploration_score": exploration_score,
            "exploration_score_raw": round(exploration_raw, 6),
            "quality_score": quality_score,
            "quality_score_raw": round(quality_raw, 6),
            "seen_penalty": round(seen_penalty, 6),
            "negative_penalty": round(negative_penalty, 6),
            "final_score": round(final_score, 6),
        }

        enriched = dict(candidate)
        enriched["scores"] = score_breakdown
        enriched["score_breakdown"] = dict(score_breakdown)
        enriched["final_score"] = round(final_score, 6)
        scored.append(enriched)

    return sorted(
        scored,
        key=lambda candidate: (
            _safe_float(candidate.get("final_score"), 0.0),
            _safe_float(candidate.get("query_hybrid_score_raw"), 0.0),
            _safe_float(candidate.get("quality_score_raw"), 0.0),
            str(candidate.get("item_id") or ""),
        ),
        reverse=True,
    )