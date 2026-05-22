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

    return {
        "total_results": total,
        "has_matched_intent": has_intent,
        "has_matched_fact": has_fact,
        "has_both_explanations": has_both,
        "has_no_explanation": has_neither,
        "intent_coverage": round(has_intent / total, 4) if total else None,
        "fact_coverage": round(has_fact / total, 4) if total else None,
        "full_explanation_coverage": round(has_both / total, 4) if total else None,
    }
