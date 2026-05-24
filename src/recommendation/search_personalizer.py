from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from src.behavior.event_logger import log_recommendation_snapshot
from src.config import get_settings
from src.mongodb import (
    get_item_hype_profiles_collection,
    get_item_item_cf_edges_collection,
    get_item_stats_collection,
    get_items_collection,
    get_recommendation_logs_collection,
    get_user_item_signals_collection,
    get_user_profiles_collection,
)
from src.query_processor import process_query
from src.recommendation.candidate_sources import (
    build_cf_candidates,
    enrich_with_profile_context,
    load_item_snapshot,
    load_user_profile,
    load_user_signals,
    merge_candidate_rows,
)
from src.recommendation.explanations import build_result_card
from src.recommendation.scoring import classify_query_type, get_search_weights, score_candidate_batch
from src.search_pipeline import run_search


def _request_id() -> str:
    return f"req_search_{uuid4().hex[:16]}"


def _candidate_from_search_result(result: dict[str, Any]) -> dict[str, Any]:
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    matched_channels = debug.get("matched_channels") if isinstance(debug.get("matched_channels"), list) else []
    return {
        "item_id": str(result.get("item_id") or ""),
        "title": str(result.get("title") or ""),
        "brand": str(debug.get("brand") or ""),
        "category_id": str(debug.get("category_id") or ""),
        "price_bucket": str(debug.get("price_bucket") or "unknown"),
        "price_vnd": debug.get("price_vnd"),
        "image_url": result.get("image_url"),
        "is_cold_item": bool(result.get("is_cold_item")),
        "interaction_count": result.get("interaction_count", 0),
        "query_hybrid_score_raw": max(float(result.get("score") or 0.0), float(result.get("fusion_score") or 0.0)),
        "profile_score_raw": -1.0,
        "semantic_neighbor_score_raw": 0.0,
        "item_item_cf_score_raw": 0.0,
        "metadata_score_raw": 0.0,
        "cold_start_boost_raw": 1.0 if result.get("is_cold_item") else 0.0,
        "exploration_score_raw": 0.0,
        "quality_score_raw": 0.0,
        "seen_penalty": 0.0,
        "negative_penalty": 0.0,
        "matched_intent": str(result.get("matched_intent") or ""),
        "matched_fact": str(result.get("matched_fact") or ""),
        "matched_channels": [str(value) for value in matched_channels],
        "candidate_sources": ["query_hybrid"],
        "matched_unit_ids": list(result.get("matched_unit_ids", [])) if isinstance(result.get("matched_unit_ids"), list) else [],
        "matched_aspects": [],
        "matched_profile_interest_ids": [],
        "matched_interest_embedding": None,
        "matched_neighbor_embedding": None,
        "profile_interest_label": "",
        "cf_evidence": None,
        "debug": dict(debug),
        "cold_start_note": str(result.get("cold_start_note") or ""),
    }


def personalized_search(
    user_id_hash: str,
    session_id: str,
    raw_query: str,
    top_k: int = 20,
    personalized: bool = True,
    *,
    process_query_fn: Callable[[str], dict[str, Any]] = process_query,
    run_search_fn: Callable[..., list[dict[str, Any]]] = run_search,
    user_profiles_collection: Any | None = None,
    user_item_signals_collection: Any | None = None,
    items_collection: Any | None = None,
    item_stats_collection: Any | None = None,
    item_hype_profiles_collection: Any | None = None,
    item_item_cf_edges_collection: Any | None = None,
    recommendation_logs_collection: Any | None = None,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not isinstance(raw_query, str) or not raw_query.strip():
        raise ValueError("raw_query must be a non-empty string")

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
    if item_item_cf_edges_collection is None:
        item_item_cf_edges_collection = get_item_item_cf_edges_collection()
    if recommendation_logs_collection is None:
        recommendation_logs_collection = get_recommendation_logs_collection()

    query_fixture = dict(process_query_fn(raw_query))
    query_type = classify_query_type(raw_query, query_fixture.get("hard_filters"))
    query_fixture["query_type"] = query_type
    raw_results = run_search_fn(query_fixture, top_k=max(top_k * 2, top_k))
    base_rows = [_candidate_from_search_result(result) for result in raw_results]
    item_ids = {str(row.get("item_id") or "") for row in base_rows if str(row.get("item_id") or "")}
    items_by_id, item_stats_by_id, item_profiles_by_id = load_item_snapshot(
        item_ids,
        items_collection=items_collection,
        item_stats_collection=item_stats_collection,
        item_hype_profiles_collection=item_hype_profiles_collection,
    )

    effective_personalized = bool(personalized and settings.enable_personalization)
    profile = load_user_profile(user_id_hash, user_profiles_collection=user_profiles_collection) if effective_personalized else None
    merged = merge_candidate_rows(base_rows)
    if effective_personalized and query_type in {"broad", "exploratory"}:
        signals = load_user_signals(
            user_id_hash,
            user_item_signals_collection=user_item_signals_collection,
            limit=5,
        )
        source_item_ids = [str(signal.get("item_id") or "") for signal in signals if str(signal.get("item_id") or "")]
        cf_rows = build_cf_candidates(
            source_item_ids,
            items_by_id=items_by_id,
            item_stats_by_id=item_stats_by_id,
            item_item_cf_edges_collection=item_item_cf_edges_collection,
            limit_per_source=max(top_k, 5),
        )
        cf_rows = [row for row in cf_rows if str(row.get("item_id") or "") in item_ids]
        merged = merge_candidate_rows(merged, cf_rows)

    merged = enrich_with_profile_context(
        merged,
        profile=profile,
        items_by_id=items_by_id,
        item_stats_by_id=item_stats_by_id,
        item_profiles_by_id=item_profiles_by_id,
        surface="search",
    )
    scored = score_candidate_batch(merged, get_search_weights(query_type))
    top_candidates = scored[:top_k]

    request_id = _request_id()
    cards = [
        build_result_card(
            candidate,
            request_id=request_id,
            rank_position=index,
            surface="search",
            algorithm_version=settings.algorithm_version,
            ranking_version=settings.ranking_version,
        )
        for index, candidate in enumerate(top_candidates, start=1)
    ]
    query_context = {
        "raw_query": raw_query,
        "english_query": query_fixture.get("english_query", ""),
        "query_type": query_type,
        "query_embedding": query_fixture.get("query_embedding"),
    }
    snapshot = log_recommendation_snapshot(
        request_id=request_id,
        user_id_hash=user_id_hash,
        session_id=session_id,
        surface="search",
        items=cards,
        algorithm_version=settings.algorithm_version,
        ranking_version=settings.ranking_version,
        query=query_context,
        recommendation_logs_collection=recommendation_logs_collection,
    )
    return {
        "request_id": request_id,
        "surface": "search",
        "query": query_context,
        "algorithm_version": settings.algorithm_version,
        "ranking_version": settings.ranking_version,
        "personalized": effective_personalized,
        "snapshot": snapshot,
        "items": cards,
    }