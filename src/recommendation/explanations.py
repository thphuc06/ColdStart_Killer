from __future__ import annotations

from typing import Any

from src.retrieval_output import cold_start_note


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_reason_badges(candidate: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    matched_channels = {str(value) for value in candidate.get("matched_channels", [])}
    if candidate.get("matched_intent") or "vector" in matched_channels or "semantic_neighbor" in matched_channels:
        badges.append("HyPE semantic")
    if candidate.get("matched_fact") or "bm25" in matched_channels:
        badges.append("BM25 fact")
    if _safe_float(candidate.get("profile_score_raw"), -1.0) > 0:
        badges.append("Profile")
    if _safe_float(candidate.get("item_item_cf_score_raw"), 0.0) > 0:
        badges.append("Collaborative Filtering")
    if bool(candidate.get("is_cold_item")):
        badges.append("Cold-start")
    if _safe_float(candidate.get("exploration_score_raw"), 0.0) > 0:
        badges.append("Exploration")
    return badges


def build_explanations(candidate: dict[str, Any], *, surface: str) -> list[str]:
    explanations: list[str] = []

    cf_evidence = candidate.get("cf_evidence") if isinstance(candidate.get("cf_evidence"), dict) else None
    if cf_evidence:
        explanations.append(
            "Users who interacted with this item also interacted with this product "
            f"(support={int(cf_evidence.get('support') or 0)}, cf_score={_safe_float(cf_evidence.get('cf_score'), 0.0):.3f})."
        )

    matched_aspects = candidate.get("matched_aspects") if isinstance(candidate.get("matched_aspects"), list) else []
    if _safe_float(candidate.get("semantic_neighbor_score_raw"), 0.0) > 0 and matched_aspects:
        explanations.append(f"Similar intent: matched HyPE aspects {', '.join(matched_aspects[:3])}.")

    matched_intent = str(candidate.get("matched_intent") or "").strip()
    if matched_intent:
        explanations.append(f"Matched HyPE intent: {matched_intent}.")

    matched_fact = str(candidate.get("matched_fact") or "").strip()
    if matched_fact:
        explanations.append(f"Matched product fact: {matched_fact}.")

    profile_label = str(candidate.get("profile_interest_label") or "").strip()
    if _safe_float(candidate.get("profile_score_raw"), -1.0) > 0 and profile_label:
        explanations.append(f"Boosted because it matches your {profile_label} interest.")

    if _safe_float(candidate.get("exploration_score_raw"), 0.0) > 0 and surface == "home":
        explanations.append("Surfaced through cold-start exploration to keep the feed diverse.")

    note = cold_start_note(candidate)
    if note:
        explanations.append(note)

    return explanations


def build_result_card(
    candidate: dict[str, Any],
    *,
    request_id: str,
    rank_position: int,
    surface: str,
    algorithm_version: str,
    ranking_version: str,
) -> dict[str, Any]:
    explanations = build_explanations(candidate, surface=surface)
    matched_channels = list(candidate.get("matched_channels", []))
    candidate_sources = list(candidate.get("candidate_sources", []))
    matched_intent = str(candidate.get("matched_intent") or "")
    matched_fact = str(candidate.get("matched_fact") or "")

    return {
        "request_id": request_id,
        "surface": surface,
        "rank_position": rank_position,
        "algorithm_version": algorithm_version,
        "ranking_version": ranking_version,
        "item_id": str(candidate.get("item_id") or ""),
        "title": str(candidate.get("title") or ""),
        "brand": str(candidate.get("brand") or ""),
        "category_id": str(candidate.get("category_id") or ""),
        "price_bucket": str(candidate.get("price_bucket") or "unknown"),
        "price_vnd": candidate.get("price_vnd"),
        "image_url": candidate.get("image_url"),
        "image_fallback_url": candidate.get("image_fallback_url"),
        "is_cold_item": bool(candidate.get("is_cold_item")),
        "interaction_count": candidate.get("interaction_count", 0),
        "score": candidate.get("final_score", 0.0),
        "final_score": candidate.get("final_score", 0.0),
        "matched_intent": matched_intent,
        "matched_fact": matched_fact,
        "cold_start_note": cold_start_note(candidate),
        "scores": dict(candidate.get("scores") or candidate.get("score_breakdown") or {}),
        "score_breakdown": dict(candidate.get("score_breakdown") or candidate.get("scores") or {}),
        "reason_badges": build_reason_badges(candidate),
        "explanations": explanations,
        "candidate_sources": candidate_sources,
        "attribution": {
            "matched_unit_ids": list(candidate.get("matched_unit_ids", [])),
            "matched_intents": [matched_intent] if matched_intent else [],
            "matched_facts": [matched_fact] if matched_fact else [],
            "matched_channels": matched_channels,
            "candidate_sources": candidate_sources,
            "matched_profile_interest_ids": list(candidate.get("matched_profile_interest_ids", [])),
            "matched_interest_embedding": candidate.get("matched_interest_embedding"),
            "matched_neighbor_embedding": candidate.get("matched_neighbor_embedding"),
            "cf_evidence": candidate.get("cf_evidence"),
            "explanation": explanations[0] if explanations else "",
        },
        "debug": {
            "matched_channels": matched_channels,
            "matched_aspects": list(candidate.get("matched_aspects", [])),
            "matched_unit_ids": list(candidate.get("matched_unit_ids", [])),
            "candidate_sources": candidate_sources,
            "profile_interest_label": candidate.get("profile_interest_label", ""),
            "cf_evidence": candidate.get("cf_evidence"),
        },
    }
