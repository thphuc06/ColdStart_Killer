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
    build_same_category_price_candidates,
    build_semantic_neighbor_candidates,
    enrich_with_profile_context,
    exact_suppressed_item_ids,
    load_catalog_snapshot,
    load_item_snapshot,
    load_user_profile,
    load_user_signals,
    merge_candidate_rows,
)
from src.recommendation.explanations import build_result_card
from src.recommendation.scoring import SIMILAR_DEFAULT_WEIGHTS, score_candidate_batch


def _request_id() -> str:
    return f"req_sim_{uuid4().hex[:16]}"


def _filter_similar_candidates(rows: list[dict[str, Any]], *, profile: dict[str, Any] | None, source_item_id: str) -> list[dict[str, Any]]:
    excluded_item_ids = exact_suppressed_item_ids(profile, include_purchased=True) | {source_item_id}
    return [
        row
        for row in rows
        if str(row.get("item_id") or "") not in excluded_item_ids
    ]


def get_similar_products(
    user_id_hash: str,
    session_id: str,
    source_item_id: str,
    top_k: int = 12,
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

    items_by_id, item_stats_by_id, _ = load_catalog_snapshot(
        items_collection=items_collection,
        item_stats_collection=item_stats_collection,
        item_hype_profiles_collection=item_hype_profiles_collection,
        include_item_profiles=False,
    )
    if source_item_id not in items_by_id:
        return {
            "request_id": _request_id(),
            "surface": "detail_similar",
            "source_item_id": source_item_id,
            "algorithm_version": settings.algorithm_version,
            "ranking_version": settings.ranking_version,
            "items": [],
            "snapshot": {"ok": True, "attempted": 0, "inserted": 0, "existing": 0},
        }

    effective_personalized = bool(personalized and settings.enable_personalization)
    profile = load_user_profile(user_id_hash, user_profiles_collection=user_profiles_collection) if effective_personalized else None
    excluded_item_ids = exact_suppressed_item_ids(profile, include_purchased=True) | {source_item_id}
    _, _, source_profiles_by_id = load_item_snapshot(
        {source_item_id},
        items_collection=items_collection,
        item_stats_collection=item_stats_collection,
        item_hype_profiles_collection=item_hype_profiles_collection,
    )
    semantic_rows = build_semantic_neighbor_candidates(
        [source_item_id],
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_profiles_by_id=source_profiles_by_id,
        item_semantic_neighbors_collection=item_semantic_neighbors_collection,
        limit_per_source=max(top_k, 8),
        exclude_item_ids=excluded_item_ids,
    )
    cf_rows = build_cf_candidates(
        [source_item_id],
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_item_cf_edges_collection=item_item_cf_edges_collection,
        limit_per_source=max(top_k, 8),
        exclude_item_ids=excluded_item_ids,
    )
    fallback_rows = build_same_category_price_candidates(
        source_item_id,
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        limit=max(top_k * 2, 10),
        exclude_item_ids=excluded_item_ids,
    )
    merged = merge_candidate_rows(semantic_rows, cf_rows, fallback_rows)
    merged = _filter_similar_candidates(merged, profile=profile, source_item_id=source_item_id)
    profile_item_ids = {str(row.get("item_id") or "") for row in merged if str(row.get("item_id") or "")}
    _, _, item_profiles_by_id = load_item_snapshot(
        profile_item_ids,
        items_collection=items_collection,
        item_stats_collection=item_stats_collection,
        item_hype_profiles_collection=item_hype_profiles_collection,
    )
    merged = enrich_with_profile_context(
        merged,
        profile=profile,
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_profiles_by_id=item_profiles_by_id,
        surface="detail_similar",
    )
    scored = score_candidate_batch(merged, SIMILAR_DEFAULT_WEIGHTS)
    top_candidates = scored[:top_k]

    request_id = _request_id()
    cards = [
        build_result_card(
            candidate,
            request_id=request_id,
            rank_position=index,
            surface="detail_similar",
            algorithm_version=settings.algorithm_version,
            ranking_version=settings.ranking_version,
        )
        for index, candidate in enumerate(top_candidates, start=1)
    ]
    snapshot = log_recommendation_snapshot(
        request_id=request_id,
        user_id_hash=user_id_hash,
        session_id=session_id,
        surface="detail_similar",
        items=cards,
        algorithm_version=settings.algorithm_version,
        ranking_version=settings.ranking_version,
        recommendation_logs_collection=recommendation_logs_collection,
    )
    return {
        "request_id": request_id,
        "surface": "detail_similar",
        "source_item_id": source_item_id,
        "algorithm_version": settings.algorithm_version,
        "ranking_version": settings.ranking_version,
        "personalized": effective_personalized,
        "snapshot": snapshot,
        "items": cards,
    }
