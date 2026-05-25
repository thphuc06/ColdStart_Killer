from __future__ import annotations

from typing import Any


REQUIRED_OUTPUT_FIELDS = [
    "item_id",
    "title",
    "score",
    "matched_intent",
    "matched_fact",
    "cold_start_note",
    "rank_vector",
    "rank_bm25",
    "fusion_score",
    "debug",
]


def _number(value: Any, default: float = 0.0) -> float:
    """Coerce value to float, returning default if not numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any) -> int | None:
    """Coerce value to int or return None if absent/invalid."""
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    """Coerce value to string, returning empty if absent."""
    return "" if value is None else str(value)


def cold_start_note(result: dict[str, Any]) -> str:
    """Spec line ~339: emit a cold-start explanation flag for cold items."""
    if not isinstance(result, dict):
        raise ValueError("result must be a dictionary")
    if not result.get("is_cold_item"):
        return ""
    interaction_count = result.get("interaction_count")
    if interaction_count in (None, 0):
        return "Cold-start item with no interaction history."
    return "Cold-start item with limited interaction history."


def build_explainable_result(result: dict[str, Any]) -> dict[str, Any]:
    """Spec line ~339: build the explainable buyer result object."""
    if not isinstance(result, dict):
        raise ValueError("result must be a dictionary")
    debug = dict(result.get("debug") or {})
    debug.setdefault("brand", result.get("brand"))
    debug.setdefault("category_id", result.get("category_id"))
    debug.setdefault("price_vnd", result.get("price_vnd"))
    debug.setdefault("price_bucket", result.get("price_bucket"))
    debug.setdefault("seller_confirmed", result.get("seller_confirmed"))

    return {
        "item_id": _text(result.get("item_id")),
        "title": _text(result.get("title") or result.get("title_en")),
        "score": _number(result.get("score") if result.get("score") is not None else result.get("fusion_score")),
        "matched_intent": _text(result.get("matched_intent")),
        "matched_fact": _text(result.get("matched_fact")),
        "cold_start_note": cold_start_note(result),
        "rank_vector": _optional_int(result.get("rank_vector")),
        "rank_bm25": _optional_int(result.get("rank_bm25")),
        "fusion_score": _number(result.get("fusion_score")),
        "debug": debug,
    }


def build_explainable_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format every aggregation result as the spec's explainable output object."""
    if not isinstance(results, list):
        raise ValueError("results must be a list of dictionaries")
    return [build_explainable_result(result) for result in results]
