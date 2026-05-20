from __future__ import annotations

from typing import Any, Literal

from pymongo.errors import OperationFailure

from .mongodb import get_retrieval_units_collection
from .retrieval_output import build_explainable_result


VECTOR_INDEX_NAME = "vector_index"
TEXT_INDEX_NAME = "text_index"
RRF_K = 60
DEFAULT_NUM_CANDIDATES = 150
DEFAULT_CHANNEL_LIMIT = 50
DEFAULT_TOP_K = 10
DEFAULT_WEIGHTS = {"vector": 0.60, "bm25": 0.40}

PipelineMode = Literal["auto", "rankFusion", "unionWith"]


def validate_query_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    """Validate the pre-computed query fixture required by spec section 3.3."""
    required = ["bm25_search_query_en", "query_embedding"]
    # Optional: hype_search_query_en is provided by the teammate's query-transform step.
    # It is not used directly in aggregation because query_embedding already encodes the HyPE intent.
    missing = [field for field in required if field not in fixture]
    if missing:
        raise ValueError(f"Missing query fixture fields: {', '.join(missing)}")
    embedding = fixture["query_embedding"]
    if not isinstance(embedding, list):
        raise ValueError("query_embedding must be a list of floats")
    if len(embedding) != 1024:
        raise ValueError(f"query_embedding must be 1024 dimensions, got {len(embedding)}")
    return fixture


def normalize_hard_filters(hard_filters: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize filter aliases for spec fields: price_bucket, in_stock, is_cold_item, seller_confirmed."""
    filters = dict(hard_filters or {})
    if "price_max" in filters and "max_price_vnd" not in filters:
        filters["max_price_vnd"] = filters["price_max"]
    if "price_min" in filters and "min_price_vnd" not in filters:
        filters["min_price_vnd"] = filters["price_min"]
    if "price_bucket" in filters and not isinstance(filters["price_bucket"], list):
        filters["price_bucket"] = [filters["price_bucket"]]
    if "in_stock" not in filters:
        filters["in_stock"] = True
    return filters


def vector_search_filter(unit_type: str, hard_filters: dict[str, Any] | None) -> dict[str, Any]:
    """Build the $vectorSearch pre-filter from spec sections 2.3 and 3.4."""
    filters = normalize_hard_filters(hard_filters)
    output: dict[str, Any] = {"unit_type": unit_type, "language": "en"}
    for field in ("in_stock", "is_cold_item"):
        if field in filters and filters[field] is not None:
            output[field] = bool(filters[field])
    if filters.get("price_bucket"):
        output["price_bucket"] = {"$in": list(filters["price_bucket"])}
    if filters.get("category_id"):
        output["category_id"] = filters["category_id"]
    if filters.get("exclude_categories"):
        output["category_id"] = {"$nin": list(filters["exclude_categories"])}
    return output


def atlas_search_compound(bm25_query_en: str, hard_filters: dict[str, Any] | None) -> dict[str, Any]:
    """Build the Atlas Search BM25 compound query from spec section 3.4."""
    return {
        "should": [
            {
                "text": {
                    "query": bm25_query_en,
                    "path": ["text_search", "embedding_text", "raw_text"],
                    "score": {"boost": {"value": 1.5}},
                }
            },
            {
                "text": {
                    "query": bm25_query_en,
                    "path": ["item_title_en", "item_brand"],
                    "fuzzy": {"maxEdits": 1},
                }
            },
        ],
    }


def item_match_stage(hard_filters: dict[str, Any] | None) -> dict[str, Any]:
    """Apply post-$lookup item-level hard filters from spec section 3.4 Stage 4."""
    filters = normalize_hard_filters(hard_filters)
    clauses: list[dict[str, Any]] = []
    if "in_stock" in filters:
        clauses.append({"item.in_stock": bool(filters["in_stock"])})
    if "is_cold_item" in filters:
        clauses.append({"item.cold_start.is_cold_item": bool(filters["is_cold_item"])})
    if "seller_confirmed" in filters:
        clauses.append({"item.description_enriched.seller_confirmed": bool(filters["seller_confirmed"])})
    if filters.get("price_bucket"):
        clauses.append({"item.price_bucket": {"$in": list(filters["price_bucket"])}})
    if filters.get("category_id"):
        clauses.append({"item.category_id": filters["category_id"]})
    if filters.get("exclude_categories"):
        clauses.append({"item.category_id": {"$nin": list(filters["exclude_categories"])}})
    if filters.get("max_price_vnd") is not None:
        clauses.append({"item.price_vnd": {"$lte": int(filters["max_price_vnd"])}})
    if filters.get("min_price_vnd") is not None:
        clauses.append({"item.price_vnd": {"$gte": int(filters["min_price_vnd"])}})
    return {"$match": {"$and": clauses}} if clauses else {"$match": {}}


def vector_subpipeline(
    query_embedding: list[float],
    hard_filters: dict[str, Any] | None,
    num_candidates: int = DEFAULT_NUM_CANDIDATES,
    channel_limit: int = DEFAULT_CHANNEL_LIMIT,
) -> list[dict[str, Any]]:
    """Spec section 3.4 Step 1: $vectorSearch over HyPE retrieval units."""
    return [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": num_candidates,
                "limit": channel_limit,
                "filter": vector_search_filter("hype_question", hard_filters),
            }
        },
        {
            "$addFields": {
                "channel": "vector",
                "matched_intent": "$raw_text",
                "matched_fact": None,
                "rank_bm25": None,
                "raw_vector_score": {"$meta": "vectorSearchScore"},
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"raw_vector_score": -1},
                "output": {"rank_vector": {"$documentNumber": {}}},
            }
        },
    ]


def bm25_subpipeline(
    bm25_search_query_en: str,
    hard_filters: dict[str, Any] | None,
    channel_limit: int = DEFAULT_CHANNEL_LIMIT,
) -> list[dict[str, Any]]:
    """Spec section 3.4 Step 2: Atlas Search BM25 over proposition retrieval units."""
    return [
        {
            "$search": {
                "index": TEXT_INDEX_NAME,
                "compound": atlas_search_compound(bm25_search_query_en, hard_filters),
            }
        },
        {"$limit": channel_limit},
        {
            "$addFields": {
                "channel": "bm25",
                "matched_intent": None,
                "matched_fact": "$raw_text",
                "rank_vector": None,
                "raw_bm25_score": {"$meta": "searchScore"},
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"raw_bm25_score": -1},
                "output": {"rank_bm25": {"$documentNumber": {}}},
            }
        },
    ]


def common_projection_stage() -> dict[str, Any]:
    return {
        "$project": {
            "_id": 1,
            "item_id": 1,
            "unit_type": 1,
            "channel": 1,
            "matched_intent": 1,
            "matched_fact": 1,
            "rank_vector": 1,
            "rank_bm25": 1,
            "fusion_score": 1,
            "raw_vector_score": 1,
            "raw_bm25_score": 1,
            "confidence": 1,
            "aspect": 1,
            "proposition_type": 1,
            "category_id": 1,
            "price_bucket": 1,
            "in_stock": 1,
            "is_cold_item": 1,
            "seller_confirmed": 1,
        }
    }


def post_fusion_stages(hard_filters: dict[str, Any] | None, top_k: int) -> list[dict[str, Any]]:
    """Spec section 3.4 Steps 5-6: lookup items, group by item_id, score, sort, top-K."""
    high_rank = 1_000_000
    return [
        {
            "$group": {
                "_id": "$item_id",
                "fusion_score": {"$max": "$fusion_score"},
                "rank_vector": {"$min": {"$ifNull": ["$rank_vector", high_rank]}},
                "rank_bm25": {"$min": {"$ifNull": ["$rank_bm25", high_rank]}},
                "raw_vector_score": {"$max": {"$ifNull": ["$raw_vector_score", 0]}},
                "raw_bm25_score": {"$max": {"$ifNull": ["$raw_bm25_score", 0]}},
                "matched_channels": {"$addToSet": "$channel"},
                "matches": {
                    "$push": {
                        "channel": "$channel",
                        "matched_intent": "$matched_intent",
                        "matched_fact": "$matched_fact",
                        "rank_vector": "$rank_vector",
                        "rank_bm25": "$rank_bm25",
                        "fusion_score": "$fusion_score",
                        "raw_vector_score": "$raw_vector_score",
                        "raw_bm25_score": "$raw_bm25_score",
                        "confidence": "$confidence",
                        "aspect": "$aspect",
                        "proposition_type": "$proposition_type",
                    }
                },
            }
        },
        {
            "$addFields": {
                "rank_vector": {"$cond": [{"$eq": ["$rank_vector", high_rank]}, None, "$rank_vector"]},
                "rank_bm25": {"$cond": [{"$eq": ["$rank_bm25", high_rank]}, None, "$rank_bm25"]},
                "best_vector": {
                    "$first": {
                        "$sortArray": {
                            "input": {
                                "$filter": {
                                    "input": "$matches",
                                    "as": "m",
                                    "cond": {"$eq": ["$$m.channel", "vector"]},
                                }
                            },
                            "sortBy": {"fusion_score": -1},
                        }
                    }
                },
                "best_bm25": {
                    "$first": {
                        "$sortArray": {
                            "input": {
                                "$filter": {
                                    "input": "$matches",
                                    "as": "m",
                                    "cond": {"$eq": ["$$m.channel", "bm25"]},
                                }
                            },
                            "sortBy": {"fusion_score": -1},
                        }
                    }
                },
            }
        },
        {
            "$lookup": {
                "from": "items",
                "localField": "_id",
                "foreignField": "_id",
                "as": "item",
            }
        },
        {"$unwind": "$item"},
        item_match_stage(hard_filters),
        {
            "$addFields": {
                "multi_channel_bonus": {
                    "$cond": [{"$gt": [{"$size": "$matched_channels"}, 1]}, 0.05, 0]
                },
                "cold_start_boost": {
                    "$cond": [
                        {"$eq": ["$item.cold_start.is_cold_item", True]},
                        0.03,
                        0,
                    ]
                },
            }
        },
        {
            "$addFields": {
                "score": {
                    "$add": [
                        "$fusion_score",
                        "$multi_channel_bonus",
                        "$cold_start_boost",
                        {"$multiply": [{"$ifNull": ["$item.content_richness", 0]}, 0.02]},
                    ]
                },
                "matched_intent": "$best_vector.matched_intent",
                "matched_fact": "$best_bm25.matched_fact",
            }
        },
        {"$sort": {"score": -1, "fusion_score": -1}},
        {"$limit": int(top_k)},
        {
            "$project": {
                "_id": 0,
                "item_id": "$_id",
                "title": "$item.title_en",
                "brand": "$item.brand",
                "category_id": "$item.category_id",
                "price_vnd": "$item.price_vnd",
                "price_bucket": "$item.price_bucket",
                "image_url": "$item.image_url",
                "is_cold_item": "$item.cold_start.is_cold_item",
                "interaction_count": "$item.cold_start.interaction_count",
                "seller_confirmed": "$item.description_enriched.seller_confirmed",
                "score": 1,
                "matched_intent": 1,
                "matched_fact": 1,
                "rank_vector": 1,
                "rank_bm25": 1,
                "fusion_score": 1,
                "debug": {
                    "raw_vector_score": "$raw_vector_score",
                    "raw_bm25_score": "$raw_bm25_score",
                    "matched_channels": "$matched_channels",
                    "multi_channel_bonus": "$multi_channel_bonus",
                    "cold_start_boost": "$cold_start_boost",
                    "best_vector": "$best_vector",
                    "best_bm25": "$best_bm25",
                },
            }
        },
    ]


def build_rank_fusion_pipeline(fixture: dict[str, Any], top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """Spec line ~496: build the native $rankFusion hybrid pipeline."""
    validate_query_fixture(fixture)
    hard_filters = normalize_hard_filters(fixture.get("hard_filters"))
    vector_pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": fixture["query_embedding"],
                "numCandidates": DEFAULT_NUM_CANDIDATES,
                "limit": DEFAULT_CHANNEL_LIMIT,
                "filter": vector_search_filter("hype_question", hard_filters),
            }
        },
        {"$limit": DEFAULT_CHANNEL_LIMIT},
    ]
    bm25_pipeline = [
        {
            "$search": {
                "index": TEXT_INDEX_NAME,
                "compound": atlas_search_compound(fixture["bm25_search_query_en"], hard_filters),
            }
        },
        {"$limit": DEFAULT_CHANNEL_LIMIT},
    ]
    pipeline = [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "vectorPipeline": vector_pipeline,
                        "bm25Pipeline": bm25_pipeline,
                    }
                },
                "combination": {
                    "weights": {
                        "vectorPipeline": DEFAULT_WEIGHTS["vector"],
                        "bm25Pipeline": DEFAULT_WEIGHTS["bm25"],
                    }
                },
                "scoreDetails": True,
            }
        },
        {
            "$addFields": {
                "fusion_score": {"$meta": "score"},
                "score_details": {"$meta": "searchScoreDetails"},
            }
        },
        {
            "$addFields": {
                "vector_detail": {
                    "$arrayElemAt": [
                        {
                            "$filter": {
                                "input": {"$ifNull": ["$score_details.details", []]},
                                "as": "detail",
                                "cond": {
                                    "$eq": ["$$detail.inputPipelineName", "vectorPipeline"]
                                },
                            }
                        },
                        0,
                    ]
                },
                "bm25_detail": {
                    "$arrayElemAt": [
                        {
                            "$filter": {
                                "input": {"$ifNull": ["$score_details.details", []]},
                                "as": "detail",
                                "cond": {
                                    "$eq": ["$$detail.inputPipelineName", "bm25Pipeline"]
                                },
                            }
                        },
                        0,
                    ]
                },
            }
        },
        {
            "$addFields": {
                "has_bm25_match": {
                    "$and": [
                        {"$ne": [{"$ifNull": ["$bm25_detail", None]}, None]},
                        {"$ne": [{"$ifNull": ["$bm25_detail.rank", "N/A"]}, "N/A"]},
                    ]
                },
            }
        },
        {
            "$addFields": {
                "channel": {
                    "$cond": ["$has_bm25_match", "bm25", "vector"]
                },
                "matched_intent": {
                    "$cond": ["$has_bm25_match", None, "$raw_text"]
                },
                "matched_fact": {
                    "$cond": ["$has_bm25_match", "$raw_text", None]
                },
                "rank_vector": {
                    "$cond": [
                        {"$eq": [{"$ifNull": ["$vector_detail.rank", "N/A"]}, "N/A"]},
                        None,
                        "$vector_detail.rank",
                    ]
                },
                "rank_bm25": {
                    "$cond": [
                        {"$eq": [{"$ifNull": ["$bm25_detail.rank", "N/A"]}, "N/A"]},
                        None,
                        "$bm25_detail.rank",
                    ]
                },
                "raw_vector_score": None,
                "raw_bm25_score": None,
            }
        },
        common_projection_stage(),
    ]
    pipeline.extend(post_fusion_stages(hard_filters, top_k))
    return pipeline


def build_union_with_pipeline(fixture: dict[str, Any], top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """Spec line ~486: build Atlas M0-compatible $unionWith fallback with manual RRF."""
    validate_query_fixture(fixture)
    hard_filters = normalize_hard_filters(fixture.get("hard_filters"))
    pipeline = vector_subpipeline(fixture["query_embedding"], hard_filters)
    pipeline.extend(
        [
            {
                "$addFields": {
                    "fusion_score": {
                        "$divide": [DEFAULT_WEIGHTS["vector"], {"$add": [RRF_K, "$rank_vector"]}]
                    }
                }
            },
            common_projection_stage(),
            {
                "$unionWith": {
                    "coll": "retrieval_units",
                    "pipeline": bm25_subpipeline(fixture["bm25_search_query_en"], hard_filters)
                    + [
                        {
                            "$addFields": {
                                "fusion_score": {
                                    "$divide": [
                                        DEFAULT_WEIGHTS["bm25"],
                                        {"$add": [RRF_K, "$rank_bm25"]},
                                    ]
                                }
                            }
                        },
                        common_projection_stage(),
                    ],
                }
            },
        ]
    )
    pipeline.extend(post_fusion_stages(hard_filters, top_k))
    return pipeline


def build_search_pipeline(
    fixture: dict[str, Any],
    top_k: int = DEFAULT_TOP_K,
    mode: PipelineMode = "rankFusion",
) -> list[dict[str, Any]]:
    """Build either the $rankFusion pipeline or the $unionWith RRF fallback."""
    if mode == "unionWith":
        return build_union_with_pipeline(fixture, top_k=top_k)
    return build_rank_fusion_pipeline(fixture, top_k=top_k)


def is_rank_fusion_unavailable(exc: OperationFailure) -> bool:
    if getattr(exc, "code", None) == 9191103 or (exc.details or {}).get("code") == 9191103:
        return True
    message = str(exc).lower()
    return "$rankfusion" in message or "rankfusion" in message or "unrecognized pipeline stage" in message


def run_search(
    fixture: dict[str, Any],
    top_k: int = DEFAULT_TOP_K,
    mode: PipelineMode = "auto",
    collection: Any | None = None,
) -> list[dict[str, Any]]:
    """Run buyer search using pre-computed query inputs; no LLM or embedding calls are made."""
    validate_query_fixture(fixture)
    retrieval_units = collection or get_retrieval_units_collection()

    if mode == "unionWith":
        raw_results = list(retrieval_units.aggregate(build_union_with_pipeline(fixture, top_k=top_k)))
        return [build_explainable_result(result) for result in raw_results]

    try:
        raw_results = list(retrieval_units.aggregate(build_rank_fusion_pipeline(fixture, top_k=top_k)))
    except OperationFailure as exc:
        if mode != "auto" or not is_rank_fusion_unavailable(exc):
            raise
        raw_results = list(retrieval_units.aggregate(build_union_with_pipeline(fixture, top_k=top_k)))

    return [build_explainable_result(result) for result in raw_results]
