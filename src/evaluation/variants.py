"""Evaluation variant runners for ColdStart_Killer.

Each variant wraps production pipeline functions to produce
comparable retrieval results for evaluation.

Import safety: no side effects at import time.
All MongoDB/Ollama dependencies are deferred to function calls.
"""

from __future__ import annotations

import re
from typing import Any

from .contracts import EvaluationResult, FailureRecord


EVALUATION_VARIANTS = (
    "title_only",
    "vector_only",
    "bm25_only",
    "hybrid_union",
    "hybrid_no_cold_boost",
)


def _result_to_evaluation_result(
    result: dict[str, Any],
    query_id: str,
    variant: str,
    rank: int,
) -> EvaluationResult:
    """Convert a pipeline result dict to an EvaluationResult."""
    debug = result.get("debug", {})

    # Derive is_cold_item from cold_start_note or is_cold_item field
    cold_note = result.get("cold_start_note", "")
    is_cold = result.get("is_cold_item")
    if is_cold is None and cold_note:
        is_cold = True
    elif is_cold is None:
        is_cold = None  # explicitly unknown

    return EvaluationResult(
        query_id=query_id,
        variant=variant,
        rank=rank,
        item_id=result.get("item_id", ""),
        score=float(result.get("score", 0.0)),
        title=result.get("title", ""),
        brand=debug.get("brand", result.get("brand", "")),
        category_id=debug.get("category_id", result.get("category_id", "")),
        price_vnd=result.get("price_vnd") or debug.get("price_vnd"),
        price_bucket=debug.get("price_bucket", result.get("price_bucket", "")),
        matched_intent=result.get("matched_intent", ""),
        matched_fact=result.get("matched_fact", ""),
        channels=debug.get("matched_channels", []),
        is_cold_item=is_cold,
        result_status="ok",
        debug=debug,
    )


def run_hybrid_union(
    fixture: dict[str, Any],
    query_id: str,
    top_k: int,
    collection: Any | None = None,
) -> list[EvaluationResult]:
    """Run the main hybrid_union variant using production run_search()."""
    from src.search_pipeline import run_search

    results = run_search(fixture, top_k=top_k, mode="unionWith", collection=collection)
    return [
        _result_to_evaluation_result(r, query_id, "hybrid_union", i + 1)
        for i, r in enumerate(results)
    ]


def run_vector_only(
    fixture: dict[str, Any],
    query_id: str,
    top_k: int,
    collection: Any | None = None,
) -> list[EvaluationResult]:
    """Run vector_only variant — HyPE vector units only."""
    from src.search_pipeline import (
        normalize_hard_filters,
        post_fusion_stages,
        validate_query_fixture,
        vector_subpipeline,
    )
    from src.retrieval_output import build_explainable_result

    validate_query_fixture(fixture)
    hard_filters = normalize_hard_filters(fixture.get("hard_filters"))
    pipeline = vector_subpipeline(fixture["query_embedding"], hard_filters)
    pipeline.extend(post_fusion_stages(hard_filters, top_k))

    coll = collection
    if coll is None:
        from src.mongodb import get_retrieval_units_collection
        coll = get_retrieval_units_collection()

    raw = list(coll.aggregate(pipeline))
    results = [build_explainable_result(r) for r in raw]
    return [
        _result_to_evaluation_result(r, query_id, "vector_only", i + 1)
        for i, r in enumerate(results)
    ]


def run_bm25_only(
    fixture: dict[str, Any],
    query_id: str,
    top_k: int,
    collection: Any | None = None,
) -> list[EvaluationResult]:
    """Run bm25_only variant — proposition BM25 units only."""
    from src.search_pipeline import (
        bm25_subpipeline,
        normalize_hard_filters,
        post_fusion_stages,
        validate_query_fixture,
    )
    from src.retrieval_output import build_explainable_result

    validate_query_fixture(fixture)
    hard_filters = normalize_hard_filters(fixture.get("hard_filters"))
    pipeline = bm25_subpipeline(fixture["bm25_search_query_en"], hard_filters)
    pipeline.extend(post_fusion_stages(hard_filters, top_k))

    coll = collection
    if coll is None:
        from src.mongodb import get_retrieval_units_collection
        coll = get_retrieval_units_collection()

    raw = list(coll.aggregate(pipeline))
    results = [build_explainable_result(r) for r in raw]
    return [
        _result_to_evaluation_result(r, query_id, "bm25_only", i + 1)
        for i, r in enumerate(results)
    ]


def _title_only_pipeline(
    bm25_search_query_en: str,
    hard_filters: dict[str, Any] | None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Build a weak regex baseline pipeline on the items collection.

    This searches items.title_en and items.brand directly — NOT retrieval_units.
    It does NOT use Atlas Search, $vectorSearch, or any retrieval unit.
    """
    from src.search_pipeline import normalize_hard_filters

    filters = normalize_hard_filters(hard_filters)
    tokens = [t for t in bm25_search_query_en.split() if len(t) > 1]
    if not tokens:
        return []
    regex_pattern = "|".join(re.escape(t) for t in tokens)

    match_stage: dict[str, Any] = {
        "$match": {
            "$or": [
                {"title_en": {"$regex": regex_pattern, "$options": "i"}},
                {"brand": {"$regex": regex_pattern, "$options": "i"}},
            ],
            "in_stock": filters.get("in_stock", True),
        }
    }

    # Apply price filters
    if filters.get("max_price_vnd") is not None:
        match_stage["$match"]["price_vnd"] = {"$lte": int(filters["max_price_vnd"])}
    if filters.get("min_price_vnd") is not None:
        match_stage["$match"].setdefault("price_vnd", {})
        match_stage["$match"]["price_vnd"]["$gte"] = int(filters["min_price_vnd"])

    return [
        match_stage,
        {"$addFields": {
            "match_score": {
                "$size": {
                    "$regexFindAll": {
                        "input": {"$toLower": "$title_en"},
                        "regex": regex_pattern,
                    }
                }
            },
        }},
        {"$sort": {"match_score": -1, "price_vnd": 1}},
        {"$limit": top_k},
        {"$project": {
            "_id": 0,
            "item_id": "$_id",
            "title": "$title_en",
            "brand": 1,
            "category_id": 1,
            "price_vnd": 1,
            "price_bucket": 1,
            "is_cold_item": "$cold_start.is_cold_item",
            "score": "$match_score",
            "matched_intent": "",
            "matched_fact": "",
            "rank_vector": {"$literal": None},
            "rank_bm25": {"$literal": None},
            "fusion_score": {"$literal": 0},
            "debug": {
                "matched_channels": [],
                "variant": "title_only",
            },
        }},
    ]


def run_title_only(
    fixture: dict[str, Any],
    query_id: str,
    top_k: int,
    items_collection: Any | None = None,
) -> list[EvaluationResult]:
    """Run title_only variant using regex on items collection."""
    pipeline = _title_only_pipeline(
        bm25_search_query_en=fixture.get("bm25_search_query_en", ""),
        hard_filters=fixture.get("hard_filters"),
        top_k=top_k,
    )
    if not pipeline:
        return []

    coll = items_collection
    if coll is None:
        from src.mongodb import get_items_collection
        coll = get_items_collection()

    raw = list(coll.aggregate(pipeline))
    return [
        _result_to_evaluation_result(r, query_id, "title_only", i + 1)
        for i, r in enumerate(raw)
    ]


def run_hybrid_no_cold_boost(
    fixture: dict[str, Any],
    query_id: str,
    top_k: int,
    collection: Any | None = None,
) -> list[EvaluationResult]:
    """Run hybrid without cold boost — ablation disables boost BEFORE sort/rank.

    Builds a custom pipeline with include_cold_boost=False so MongoDB
    sorts and limits WITHOUT cold_start_boost influence. This is the
    correct ablation approach — the old approach of subtracting boost
    after ranking was incorrect because the ranking order had already
    been influenced by the boost.

    Does NOT mutate global COLD_START_BOOST.
    """
    from src.search_pipeline import build_union_with_pipeline_parametrized
    from src.retrieval_output import build_explainable_result

    # Build pipeline WITHOUT cold boost — boost is disabled BEFORE sort
    pipeline = build_union_with_pipeline_parametrized(
        fixture,
        top_k=top_k,
        include_cold_boost=False,
        include_content_bonus=True,
        include_multi_channel_bonus=True,
    )

    coll = collection
    if coll is None:
        from src.mongodb import get_retrieval_units_collection
        coll = get_retrieval_units_collection()

    raw = list(coll.aggregate(pipeline))
    results = [build_explainable_result(r) for r in raw]
    return [
        _result_to_evaluation_result(r, query_id, "hybrid_no_cold_boost", i + 1)
        for i, r in enumerate(results)
    ]


# Dispatcher
_VARIANT_RUNNERS = {
    "hybrid_union": run_hybrid_union,
    "vector_only": run_vector_only,
    "bm25_only": run_bm25_only,
    "title_only": run_title_only,
    "hybrid_no_cold_boost": run_hybrid_no_cold_boost,
}


def run_variant(
    fixture: dict[str, Any],
    variant: str,
    query_id: str,
    top_k: int,
    collection: Any | None = None,
    items_collection: Any | None = None,
) -> tuple[list[EvaluationResult], FailureRecord | None]:
    """Run a single variant and return results + optional failure.

    Returns:
        (results, None) on success.
        ([], FailureRecord) on failure.
    """
    if variant not in EVALUATION_VARIANTS:
        raise ValueError(f"Unknown variant: {variant!r}. Valid: {EVALUATION_VARIANTS}")

    runner = _VARIANT_RUNNERS[variant]
    try:
        if variant == "title_only":
            results = runner(fixture, query_id, top_k, items_collection=items_collection)
        else:
            results = runner(fixture, query_id, top_k, collection=collection)
        return results, None
    except Exception as exc:
        error_type = "aggregation_failed"
        if "variant_unavailable" in str(exc).lower():
            error_type = "variant_unavailable"
        elif "connection" in str(exc).lower():
            error_type = "mongodb_connection_failed"

        failure = FailureRecord(
            stage="search",
            error_type=error_type,
            error=f"{type(exc).__name__}: {exc}",
            recoverable=True,
            query_id=query_id,
            variant=variant,
            next_file_to_inspect="src/evaluation/variants.py",
            next_function_to_inspect=f"run_{variant}",
        )
        return [], failure
