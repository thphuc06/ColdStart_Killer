from __future__ import annotations

from typing import Any

from src.config import get_settings
from src.retrieval_output import cold_start_note


_CHANNEL_RAW_FIELDS = {
    "query_hybrid": "query_hybrid_score_raw",
    "profile": "profile_score_raw",
    "semantic_neighbor": "semantic_neighbor_score_raw",
    "cf": "item_item_cf_score_raw",
    "cold_explore": "exploration_score_raw",
}
_REASON_TIE_ORDER = {
    "query_hybrid": 0,
    "profile": 1,
    "cf": 2,
    "semantic_neighbor": 3,
    "cold_explore": 4,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _channel_contribution(candidate: dict[str, Any], channel: str) -> float:
    contributions = candidate.get("contributions")
    if isinstance(contributions, dict):
        return _safe_float(contributions.get(channel), 0.0)
    return _safe_float(candidate.get(_CHANNEL_RAW_FIELDS[channel]), 0.0)


def _matched_channels(candidate: dict[str, Any]) -> set[str]:
    return {str(value) for value in candidate.get("matched_channels", [])}


def _candidate_sources(candidate: dict[str, Any]) -> set[str]:
    return {str(value) for value in candidate.get("candidate_sources", [])}


def _has_cf_evidence(candidate: dict[str, Any]) -> bool:
    evidence = candidate.get("cf_evidence")
    return isinstance(evidence, dict) and int(evidence.get("support") or 0) > 0


def _is_material_channel(
    candidate: dict[str, Any],
    channel: str,
    *,
    reason_min_contribution: float,
    profile_reason_min_contribution: float,
) -> bool:
    contribution = _channel_contribution(candidate, channel)
    threshold = (
        max(reason_min_contribution, profile_reason_min_contribution)
        if channel == "profile"
        else reason_min_contribution
    )
    if contribution < threshold:
        return False

    channels = _matched_channels(candidate)
    sources = _candidate_sources(candidate)
    if channel == "query_hybrid":
        return bool(
            str(candidate.get("matched_intent") or "").strip()
            or str(candidate.get("matched_fact") or "").strip()
            or channels & {"vector", "bm25"}
        )
    if channel == "profile":
        return bool(str(candidate.get("profile_interest_label") or "").strip())
    if channel == "cf":
        return _has_cf_evidence(candidate)
    if channel == "semantic_neighbor":
        return bool(
            channels & {"semantic_neighbor"}
            or sources & {"semantic_neighbor"}
            or candidate.get("matched_aspects")
        )
    if channel == "cold_explore":
        return bool(
            candidate.get("is_cold_item")
            or channels & {"exploration"}
            or sources & {"exploration"}
        )
    return False


def _material_reason_channels(
    candidate: dict[str, Any],
    *,
    reason_min_contribution: float,
    profile_reason_min_contribution: float,
) -> list[str]:
    material = [
        channel
        for channel in _REASON_TIE_ORDER
        if _is_material_channel(
            candidate,
            channel,
            reason_min_contribution=reason_min_contribution,
            profile_reason_min_contribution=profile_reason_min_contribution,
        )
    ]
    if bool(candidate.get("forced_cold_insertion")) and "cold_explore" not in material:
        material.append("cold_explore")
    return sorted(
        material,
        key=lambda channel: (-_channel_contribution(candidate, channel), _REASON_TIE_ORDER[channel]),
    )


def _primary_reason_channel(candidate: dict[str, Any], material_channels: list[str]) -> str:
    if bool(candidate.get("forced_cold_insertion")):
        return "cold_explore"
    return material_channels[0] if material_channels else "generic"


def _channel_explanations(candidate: dict[str, Any], channel: str, *, surface: str) -> list[str]:
    if channel == "query_hybrid":
        reasons: list[str] = []
        matched_intent = str(candidate.get("matched_intent") or "").strip()
        matched_fact = str(candidate.get("matched_fact") or "").strip()
        if matched_intent:
            reasons.append(f"Matched HyPE intent: {matched_intent}.")
        if matched_fact:
            reasons.append(f"Matched product fact: {matched_fact}.")
        return reasons or ["Matched your search query."]

    if channel == "profile":
        label = str(candidate.get("profile_interest_label") or "").strip()
        return [f"Boosted because it matches your {label} interest."] if label else []

    if channel == "cf":
        evidence = candidate.get("cf_evidence") if isinstance(candidate.get("cf_evidence"), dict) else {}
        return [
            "Users who interacted with this item also interacted with this product "
            f"(support={int(evidence.get('support') or 0)}, cf_score={_safe_float(evidence.get('cf_score'), 0.0):.3f})."
        ]

    if channel == "semantic_neighbor":
        aspects = candidate.get("matched_aspects") if isinstance(candidate.get("matched_aspects"), list) else []
        if aspects:
            return [f"Similar intent: matched HyPE aspects {', '.join(str(value) for value in aspects[:3])}."]
        return ["Recommended because it is semantically similar to a related product."]

    if channel == "cold_explore":
        if bool(candidate.get("forced_cold_insertion")):
            return ["Included to ensure newer items receive exploration exposure in this feed."]
        if surface == "home":
            return ["Surfaced through cold-start exploration to keep the feed diverse."]
        return ["Included to balance relevance with discovery of a newer item."]

    return []


def build_reason_badges(
    candidate: dict[str, Any],
    *,
    reason_min_contribution: float = 0.0,
    profile_reason_min_contribution: float = 0.0,
) -> list[str]:
    material = _material_reason_channels(
        candidate,
        reason_min_contribution=reason_min_contribution,
        profile_reason_min_contribution=profile_reason_min_contribution,
    )
    badges: list[str] = []
    channels = _matched_channels(candidate)

    def add_badge(label: str) -> None:
        if label not in badges:
            badges.append(label)

    primary_channel = _primary_reason_channel(candidate, material)
    ordered_channels = [primary_channel] + [channel for channel in material if channel != primary_channel]
    for channel in ordered_channels:
        if channel == "query_hybrid":
            if candidate.get("matched_intent") or "vector" in channels:
                add_badge("HyPE semantic")
            if candidate.get("matched_fact") or "bm25" in channels:
                add_badge("BM25 fact")
        elif channel == "profile":
            add_badge("Profile")
        elif channel == "cf":
            add_badge("Collaborative Filtering")
        elif channel == "semantic_neighbor":
            add_badge("Semantic similar")
        elif channel == "cold_explore":
            add_badge("Exploration")
    if bool(candidate.get("is_cold_item")):
        add_badge("Cold-start")
    return badges


def build_explanations(
    candidate: dict[str, Any],
    *,
    surface: str,
    reason_min_contribution: float = 0.0,
    profile_reason_min_contribution: float = 0.0,
) -> list[str]:
    material = _material_reason_channels(
        candidate,
        reason_min_contribution=reason_min_contribution,
        profile_reason_min_contribution=profile_reason_min_contribution,
    )
    primary_channel = _primary_reason_channel(candidate, material)
    ordered_channels = [primary_channel] + [channel for channel in material if channel != primary_channel]
    explanations: list[str] = []

    if primary_channel == "generic":
        explanations.append("Recommended from the current ranking blend.")
    else:
        for channel in ordered_channels:
            explanations.extend(_channel_explanations(candidate, channel, surface=surface))

    note = cold_start_note(candidate)
    if note and note not in explanations:
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
    settings = get_settings()
    reason_min_contribution = max(0.0, settings.reason_min_contribution)
    profile_reason_min_contribution = max(0.0, settings.profile_reason_min_contribution)
    material_channels = _material_reason_channels(
        candidate,
        reason_min_contribution=reason_min_contribution,
        profile_reason_min_contribution=profile_reason_min_contribution,
    )
    primary_channel = _primary_reason_channel(candidate, material_channels)
    primary_contribution = (
        _channel_contribution(candidate, primary_channel) if primary_channel != "generic" else 0.0
    )
    explanations = build_explanations(
        candidate,
        surface=surface,
        reason_min_contribution=reason_min_contribution,
        profile_reason_min_contribution=profile_reason_min_contribution,
    )
    matched_channels = list(candidate.get("matched_channels", []))
    candidate_sources = list(candidate.get("candidate_sources", []))
    matched_intent = str(candidate.get("matched_intent") or "")
    matched_fact = str(candidate.get("matched_fact") or "")
    profile_contributes = "profile" in material_channels

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
        "contributions": dict(candidate.get("contributions") or {}),
        "reason_badges": build_reason_badges(
            candidate,
            reason_min_contribution=reason_min_contribution,
            profile_reason_min_contribution=profile_reason_min_contribution,
        ),
        "explanations": explanations,
        "candidate_sources": candidate_sources,
        "attribution": {
            "matched_unit_ids": list(candidate.get("matched_unit_ids", [])),
            "matched_intents": [matched_intent] if matched_intent else [],
            "matched_facts": [matched_fact] if matched_fact else [],
            "matched_channels": matched_channels,
            "candidate_sources": candidate_sources,
            "matched_profile_interest_ids": (
                list(candidate.get("matched_profile_interest_ids", [])) if profile_contributes else []
            ),
            "matched_interest_embedding": candidate.get("matched_interest_embedding"),
            "matched_neighbor_embedding": candidate.get("matched_neighbor_embedding"),
            "cf_evidence": candidate.get("cf_evidence"),
            "primary_reason_channel": primary_channel,
            "primary_reason_contribution": round(primary_contribution, 6),
            "material_reason_channels": material_channels,
            "forced_cold_insertion": bool(candidate.get("forced_cold_insertion")),
            "explanation": explanations[0] if explanations else "",
        },
        "debug": {
            "matched_channels": matched_channels,
            "matched_aspects": list(candidate.get("matched_aspects", [])),
            "matched_unit_ids": list(candidate.get("matched_unit_ids", [])),
            "candidate_sources": candidate_sources,
            "profile_interest_label": candidate.get("profile_interest_label", "") if profile_contributes else "",
            "cf_evidence": candidate.get("cf_evidence"),
        },
    }
