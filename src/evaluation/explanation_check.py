"""Explanation readiness checks for evaluation results.

Import safety: no side effects.
"""

from __future__ import annotations

from typing import Any


def check_explanation_quality(results: list[dict[str, Any]]) -> dict[str, int | float | None]:
    """Compute coverage stats for matched_intent and matched_fact fields."""
    total = len(results)
    has_intent = sum(1 for r in results if r.get("matched_intent"))
    has_fact = sum(1 for r in results if r.get("matched_fact"))
    has_both = sum(1 for r in results if r.get("matched_intent") and r.get("matched_fact"))
    has_neither = total - has_intent - has_fact + has_both
    missing_intent = total - has_intent
    missing_fact = total - has_fact
    full_coverage = round(has_both / total, 4) if total else None
    both_missing_rate = round(has_neither / total, 4) if total else None
    if full_coverage is None:
        quality = "no_results"
    elif full_coverage >= 0.8 and both_missing_rate is not None and both_missing_rate <= 0.1:
        quality = "strong"
    elif full_coverage >= 0.5:
        quality = "partial"
    else:
        quality = "weak"

    return {
        "total_results": total,
        "has_matched_intent": has_intent,
        "has_matched_fact": has_fact,
        "has_both_explanations": has_both,
        "has_no_explanation": has_neither,
        "missing_intent_count": missing_intent,
        "missing_fact_count": missing_fact,
        "intent_coverage": round(has_intent / total, 4) if total else None,
        "fact_coverage": round(has_fact / total, 4) if total else None,
        "full_explanation_coverage": full_coverage,
        "both_missing_rate": both_missing_rate,
        "explanation_quality": quality,
    }
