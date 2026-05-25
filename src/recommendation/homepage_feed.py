from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.behavior.event_logger import log_recommendation_snapshot
from src.config import get_settings
from src.mongodb import (
    get_item_hype_profiles_collection,
    get_item_item_cf_edges_collection,
    get_item_semantic_neighbors_collection,
    get_item_stats_collection,
    get_items_collection,
    get_recommendation_logs_collection,
    get_user_item_signals_collection,
    get_user_profiles_collection,
)
from src.recommendation.candidate_sources import (
    build_cf_candidates,
    build_cold_exploration_candidates,
    build_profile_candidates,
    build_quality_candidates,
    build_semantic_neighbor_candidates,
    enrich_with_profile_context,
    exact_suppressed_item_ids,
    load_catalog_snapshot,
    load_user_profile,
    load_user_signals,
    merge_candidate_rows,
)
from src.recommendation.diversity import apply_diversity_rerank
from src.recommendation.explanations import build_result_card
from src.recommendation.scoring import HOMEPAGE_DEFAULT_WEIGHTS, score_candidate_batch


HOMEPAGE_QUOTAS = {
    "new": {"profile": 0, "semantic": 2, "cf": 0, "quality": 6, "exploration": 8},
    "warming": {"profile": 5, "semantic": 4, "cf": 2, "quality": 2, "exploration": 5},
    "warm": {"profile": 7, "semantic": 4, "cf": 4, "quality": 1, "exploration": 3},
}

HOMEPAGE_STATE_WEIGHTS = {
    "new": {
        "profile": 0.0,
        "semantic_neighbor": 0.10,
        "cf": 0.0,
        "metadata": 0.20,
        "cold_explore": 0.45,
        "quality": 0.25,
    },
    "warming": {
        "profile": 0.25,
        "semantic_neighbor": 0.25,
        "cf": 0.10,
        "metadata": 0.10,
        "cold_explore": 0.20,
        "quality": 0.10,
    },
    "warm": dict(HOMEPAGE_DEFAULT_WEIGHTS),
}


def _request_id() -> str:
    return f"req_home_{uuid4().hex[:16]}"


def _user_state(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "new"
    profile_quality = profile.get("profile_quality") if isinstance(profile.get("profile_quality"), dict) else {}
    confidence = float(profile_quality.get("confidence") or 0.0)
    status = str(profile.get("profile_status") or "new").strip().lower()
    if status == "warm" and confidence >= 0.35:
        return "warm"
    if status in {"warming", "warm"} or confidence >= 0.15:
        return "warming"
    return "new"


def _seed_signal_score(signal: dict[str, Any]) -> float:
    contributions = signal.get("contributions") if isinstance(signal.get("contributions"), dict) else {}
    return float(contributions.get("engaged") or 0.0) + float(contributions.get("conversion") or 0.0)


def _source_item_ids(signals: list[dict[str, Any]]) -> list[str]:
    ordered = [
        signal
        for signal in sorted(
            signals,
            key=lambda signal: (
                bool(signal.get("seed_eligible")),
                _seed_signal_score(signal),
                float(signal.get("positive_score") or 0.0),
                str(signal.get("last_interaction_at") or ""),
            ),
            reverse=True,
        )
        if bool(signal.get("seed_eligible"))
    ]

    result: list[str] = []
    seen: set[str] = set()
    for signal in ordered:
        item_id = signal.get("item_id")
        normalized = str(item_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= 5:
            break
    return result


def _filter_homepage_candidates(
    rows: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    excluded_item_ids = exact_suppressed_item_ids(profile, include_purchased=True)
    return [
        row
        for row in rows
        if str(row.get("item_id") or "") not in excluded_item_ids
    ]


def get_homepage_feed(
    user_id_hash: str,
    session_id: str,
    top_k: int = 20,
    personalized: bool = True,
    *,
    user_profiles_collection: Any | None = None,
    user_item_signals_collection: Any | None = None,
    items_collection: Any | None = None,
    item_stats_collection: Any | None = None,
    item_hype_profiles_collection: Any | None = None,
    item_semantic_neighbors_collection: Any | None = None,
    item_item_cf_edges_collection: Any | None = None,
    recommendation_logs_collection: Any | None = None,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    settings = get_settings()
    use_catalog_cache = (
        items_collection is None
        and item_stats_collection is None
        and item_hype_profiles_collection is None
    )
    if user_profiles_collection is None:
        user_profiles_collection = get_user_profiles_collection()
    if user_item_signals_collection is None:
        user_item_signals_collection = get_user_item_signals_collection()
    if items_collection is None:
        items_collection = get_items_collection()
    if item_stats_collection is None:
        item_stats_collection = get_item_stats_collection()
    if item_hype_profiles_collection is None:
        item_hype_profiles_collection = get_item_hype_profiles_collection()
    if item_semantic_neighbors_collection is None:
        item_semantic_neighbors_collection = get_item_semantic_neighbors_collection()
    if item_item_cf_edges_collection is None:
        item_item_cf_edges_collection = get_item_item_cf_edges_collection()
    if recommendation_logs_collection is None:
        recommendation_logs_collection = get_recommendation_logs_collection()

    effective_personalized = bool(personalized and settings.enable_personalization)
    profile = load_user_profile(user_id_hash, user_profiles_collection=user_profiles_collection) if effective_personalized else None
    signals = load_user_signals(
        user_id_hash,
        user_item_signals_collection=user_item_signals_collection,
        limit=5,
    ) if effective_personalized else []

    state = _user_state(profile) if effective_personalized else "new"
    quotas = HOMEPAGE_QUOTAS[state]
    weights = HOMEPAGE_STATE_WEIGHTS[state]
    items_by_id, item_stats_by_id, item_profiles_by_id = load_catalog_snapshot(
        items_collection=items_collection,
        item_stats_collection=item_stats_collection,
        item_hype_profiles_collection=item_hype_profiles_collection,
        use_cache=use_catalog_cache,
    )
    seed_item_ids = _source_item_ids(signals)
    excluded_item_ids = exact_suppressed_item_ids(profile, include_purchased=True)

    profile_rows = build_profile_candidates(
        profile,
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_profiles_by_id=item_profiles_by_id,
        limit=max(quotas["profile"] * 3, 0),
        exclude_item_ids=excluded_item_ids,
    ) if quotas["profile"] > 0 else []
    semantic_rows = build_semantic_neighbor_candidates(
        seed_item_ids,
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_profiles_by_id=item_profiles_by_id,
        item_semantic_neighbors_collection=item_semantic_neighbors_collection,
        limit_per_source=max(quotas["semantic"], 1),
        exclude_item_ids=excluded_item_ids,
    ) if seed_item_ids and quotas["semantic"] > 0 else []
    cf_rows = build_cf_candidates(
        seed_item_ids,
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_item_cf_edges_collection=item_item_cf_edges_collection,
        limit_per_source=max(quotas["cf"], 1),
        exclude_item_ids=excluded_item_ids,
    ) if seed_item_ids and quotas["cf"] > 0 else []
    quality_rows = build_quality_candidates(
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        limit=max(top_k * 2, quotas["quality"] * 4, 10),
        exclude_item_ids=excluded_item_ids,
    )
    exploration_rows = build_cold_exploration_candidates(
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        limit=max(top_k * 2, quotas["exploration"] * 4, 10),
        exclude_item_ids=excluded_item_ids,
    )

    merged = merge_candidate_rows(profile_rows, semantic_rows, cf_rows, quality_rows, exploration_rows)
    merged = _filter_homepage_candidates(merged, profile=profile)
    merged = enrich_with_profile_context(
        merged,
        profile=profile,
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_profiles_by_id=item_profiles_by_id,
        surface="home",
    )
    scored = score_candidate_batch(merged, weights)
    reranked = apply_diversity_rerank(scored, top_k=top_k)

    request_id = _request_id()
    cards = [
        build_result_card(
            candidate,
            request_id=request_id,
            rank_position=index,
            surface="home",
            algorithm_version=settings.algorithm_version,
            ranking_version=settings.ranking_version,
        )
        for index, candidate in enumerate(reranked, start=1)
    ]
    snapshot = log_recommendation_snapshot(
        request_id=request_id,
        user_id_hash=user_id_hash,
        session_id=session_id,
        surface="home",
        items=cards,
        algorithm_version=settings.algorithm_version,
        ranking_version=settings.ranking_version,
        recommendation_logs_collection=recommendation_logs_collection,
    )
    return {
        "request_id": request_id,
        "surface": "home",
        "user_state": state,
        "personalized": effective_personalized,
        "algorithm_version": settings.algorithm_version,
        "ranking_version": settings.ranking_version,
        "snapshot": snapshot,
        "items": cards,
    }
