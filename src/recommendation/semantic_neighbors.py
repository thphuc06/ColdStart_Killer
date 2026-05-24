from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pymongo import UpdateOne
from pymongo.errors import OperationFailure, PyMongoError

from src.recommendation.schemas import EMBEDDING_DIM, ItemSemanticNeighborsDocument, SemanticNeighbor
from src.schemas import to_mongo_dict
from src.search_pipeline import VECTOR_INDEX_NAME, VECTOR_NUM_CANDIDATES
from src.utils import utc_now_iso


DEFAULT_RETRIEVAL_HIT_LIMIT = 100
DEFAULT_TOP_NEIGHBORS_PER_ITEM = 50
DEFAULT_BATCH_SIZE = 500
DEFAULT_TOP_MATCHED_UNITS = 5
DEFAULT_TOP_MATCHED_ASPECTS = 5


@dataclass
class SemanticNeighborBuildStats:
    source_profiles_seen: int = 0
    source_profiles_processed: int = 0
    source_profiles_skipped: int = 0
    source_profiles_written: int = 0
    invalid_embedding_profiles: int = 0
    missing_items_skipped: int = 0
    retrieval_queries: int = 0
    retrieval_hits_seen: int = 0
    self_hits_excluded: int = 0
    neighbor_docs_built: int = 0
    bulk_write_batches: int = 0
    vector_search_failures: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_profiles_seen": self.source_profiles_seen,
            "source_profiles_processed": self.source_profiles_processed,
            "source_profiles_skipped": self.source_profiles_skipped,
            "source_profiles_written": self.source_profiles_written,
            "invalid_embedding_profiles": self.invalid_embedding_profiles,
            "missing_items_skipped": self.missing_items_skipped,
            "retrieval_queries": self.retrieval_queries,
            "retrieval_hits_seen": self.retrieval_hits_seen,
            "self_hits_excluded": self.self_hits_excluded,
            "neighbor_docs_built": self.neighbor_docs_built,
            "bulk_write_batches": self.bulk_write_batches,
            "vector_search_failures": self.vector_search_failures,
            "errors": list(self.errors),
        }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _valid_embedding(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIM:
        return None
    try:
        embedding = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in embedding):
        return None
    return embedding


def _load_existing_item_ids(items_collection: Any) -> set[str]:
    projection = {"_id": 1}
    cursor = items_collection.find({}, projection)
    if hasattr(cursor, "batch_size"):
        cursor = cursor.batch_size(1000)
    return {str(doc.get("_id") or "").strip() for doc in cursor if str(doc.get("_id") or "").strip()}


def _load_source_profiles(item_hype_profiles_collection: Any, limit_profiles: int | None) -> list[dict[str, Any]]:
    projection = {"_id": 1, "item_id": 1, "item_semantic_embedding": 1}
    cursor = item_hype_profiles_collection.find({}, projection)
    if hasattr(cursor, "batch_size"):
        cursor = cursor.batch_size(1000)

    profiles = [dict(doc) for doc in cursor]
    profiles.sort(key=lambda doc: str(doc.get("item_id") or doc.get("_id") or ""))
    if limit_profiles is not None:
        return profiles[:limit_profiles]
    return profiles


def _vector_search_pipeline(
    query_vector: list[float],
    *,
    hit_limit: int,
    num_candidates: int,
) -> list[dict[str, Any]]:
    return [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": num_candidates,
                "limit": hit_limit,
                "filter": {"unit_type": "hype_question", "language": "en"},
            }
        },
        {
            "$project": {
                "_id": 1,
                "item_id": 1,
                "aspect": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]


def _average_top_scores(scores: list[float], limit: int = 3) -> float:
    if not scores:
        return 0.0
    top_scores = scores[:limit]
    return float(sum(top_scores) / len(top_scores))


def _matched_unit_ids(hits: list[dict[str, Any]], limit: int = DEFAULT_TOP_MATCHED_UNITS) -> list[str]:
    ordered_hits = sorted(
        hits,
        key=lambda hit: (-_safe_float(hit.get("score"), 0.0), str(hit.get("unit_id") or "")),
    )
    output: list[str] = []
    seen: set[str] = set()
    for hit in ordered_hits:
        unit_id = str(hit.get("unit_id") or "").strip()
        if not unit_id or unit_id in seen:
            continue
        output.append(unit_id)
        seen.add(unit_id)
        if len(output) >= limit:
            break
    return output


def _matched_aspects(hits: list[dict[str, Any]], limit: int = DEFAULT_TOP_MATCHED_ASPECTS) -> list[str]:
    aspect_scores: dict[str, float] = {}
    for hit in hits:
        aspect = str(hit.get("aspect") or "").strip().lower()
        if not aspect:
            continue
        aspect_scores[aspect] = max(aspect_scores.get(aspect, 0.0), _safe_float(hit.get("score"), 0.0))
    return [
        aspect
        for aspect, _ in sorted(aspect_scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _build_neighbor_document(
    *,
    source_item_id: str,
    grouped_hits: dict[str, list[dict[str, Any]]],
    top_neighbors_per_item: int,
    updated_at: str,
) -> dict[str, Any]:
    neighbors: list[SemanticNeighbor] = []
    for target_item_id, hits in grouped_hits.items():
        scores = sorted((_safe_float(hit.get("score"), 0.0) for hit in hits), reverse=True)
        if not scores:
            continue
        max_score = scores[0]
        avg_top3_score = _average_top_scores(scores)
        neighbor_score = 0.7 * max_score + 0.3 * avg_top3_score
        neighbors.append(
            SemanticNeighbor(
                neighbor_item_id=target_item_id,
                neighbor_score=round(neighbor_score, 6),
                matched_unit_ids=_matched_unit_ids(hits),
                matched_aspects=_matched_aspects(hits),
                source="hype_unit_vector_search",
            )
        )

    ranked_neighbors = sorted(
        neighbors,
        key=lambda neighbor: (-_safe_float(neighbor.neighbor_score, 0.0), neighbor.neighbor_item_id),
    )[:top_neighbors_per_item]

    doc = ItemSemanticNeighborsDocument(
        _id=source_item_id,
        item_id=source_item_id,
        neighbors=ranked_neighbors,
        updated_at=updated_at,
    )
    return to_mongo_dict(doc)


def _neighbor_upsert_operation(doc: dict[str, Any]) -> UpdateOne:
    payload = dict(doc)
    doc_id = payload.pop("_id", payload["item_id"])
    return UpdateOne({"_id": doc_id}, {"$set": payload, "$setOnInsert": {"_id": doc_id}}, upsert=True)


def _bulk_write_neighbors(collection: Any, docs: list[dict[str, Any]], batch_size: int) -> dict[str, int]:
    summary = {"batches": 0, "written": 0}
    for index in range(0, len(docs), batch_size):
        batch = docs[index : index + batch_size]
        if not batch:
            continue
        result = collection.bulk_write([_neighbor_upsert_operation(doc) for doc in batch], ordered=False)
        summary["batches"] += 1
        summary["written"] += int(getattr(result, "upserted_count", 0)) + int(
            getattr(result, "modified_count", 0)
        ) + int(getattr(result, "matched_count", 0))
    return summary


def build_item_semantic_neighbors(
    *,
    item_hype_profiles_collection: Any,
    retrieval_units_collection: Any,
    items_collection: Any,
    item_semantic_neighbors_collection: Any | None = None,
    write: bool = False,
    limit_profiles: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    retrieval_hit_limit: int = DEFAULT_RETRIEVAL_HIT_LIMIT,
    top_neighbors_per_item: int = DEFAULT_TOP_NEIGHBORS_PER_ITEM,
    num_candidates: int = VECTOR_NUM_CANDIDATES,
    updated_at: str | None = None,
) -> dict[str, Any]:
    if limit_profiles is not None and limit_profiles <= 0:
        raise ValueError("limit_profiles must be positive when provided")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if retrieval_hit_limit <= 0:
        raise ValueError("retrieval_hit_limit must be positive")
    if top_neighbors_per_item <= 0:
        raise ValueError("top_neighbors_per_item must be positive")
    if num_candidates < retrieval_hit_limit:
        raise ValueError("num_candidates must be greater than or equal to retrieval_hit_limit")
    if write and item_semantic_neighbors_collection is None:
        raise ValueError("item_semantic_neighbors_collection is required when write=True")

    updated_at = updated_at or utc_now_iso()
    stats = SemanticNeighborBuildStats()
    existing_item_ids = _load_existing_item_ids(items_collection)
    source_profiles = _load_source_profiles(item_hype_profiles_collection, limit_profiles)

    docs_to_write: list[dict[str, Any]] = []
    sample_neighbors: list[dict[str, Any]] = []

    for profile in source_profiles:
        stats.source_profiles_seen += 1
        item_id = str(profile.get("item_id") or profile.get("_id") or "").strip()
        if not item_id or item_id not in existing_item_ids:
            stats.missing_items_skipped += 1
            stats.source_profiles_skipped += 1
            continue

        query_vector = _valid_embedding(profile.get("item_semantic_embedding"))
        if query_vector is None:
            stats.invalid_embedding_profiles += 1
            stats.source_profiles_skipped += 1
            continue

        try:
            hits = list(
                retrieval_units_collection.aggregate(
                    _vector_search_pipeline(
                        query_vector,
                        hit_limit=retrieval_hit_limit,
                        num_candidates=num_candidates,
                    )
                )
            )
        except (OperationFailure, PyMongoError) as exc:
            stats.vector_search_failures += 1
            stats.errors.append(str(exc))
            return {
                "ok": False,
                "status": "semantic_neighbors_unavailable",
                "semantic_neighbors_unavailable": True,
                "write": write,
                "limit_profiles": limit_profiles,
                "retrieval_hit_limit": retrieval_hit_limit,
                "top_neighbors_per_item": top_neighbors_per_item,
                "num_candidates": num_candidates,
                "vector_index_name": VECTOR_INDEX_NAME,
                "stats": stats.as_dict(),
                "sample_neighbors": sample_neighbors,
            }

        stats.source_profiles_processed += 1
        stats.retrieval_queries += 1
        stats.retrieval_hits_seen += len(hits)

        grouped_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for hit in hits:
            target_item_id = str(hit.get("item_id") or "").strip()
            if not target_item_id:
                continue
            if target_item_id == item_id:
                stats.self_hits_excluded += 1
                continue
            if target_item_id not in existing_item_ids:
                stats.missing_items_skipped += 1
                continue

            score = _safe_float(hit.get("score"), 0.0)
            if score <= 0:
                continue
            grouped_hits[target_item_id].append(
                {
                    "unit_id": str(hit.get("_id") or "").strip(),
                    "aspect": hit.get("aspect"),
                    "score": score,
                }
            )

        doc = _build_neighbor_document(
            source_item_id=item_id,
            grouped_hits=grouped_hits,
            top_neighbors_per_item=top_neighbors_per_item,
            updated_at=updated_at,
        )
        stats.neighbor_docs_built += 1
        docs_to_write.append(doc)

        if len(sample_neighbors) < 3:
            sample = dict(doc)
            sample["neighbor_count"] = len(sample.get("neighbors", []))
            sample["neighbors"] = list(sample.get("neighbors", []))[:2]
            sample_neighbors.append(sample)

    if write and docs_to_write:
        summary = _bulk_write_neighbors(item_semantic_neighbors_collection, docs_to_write, batch_size)
        stats.bulk_write_batches = summary["batches"]
        stats.source_profiles_written = summary["written"]

    return {
        "ok": stats.source_profiles_processed > 0 and stats.vector_search_failures == 0,
        "status": "ok",
        "semantic_neighbors_unavailable": False,
        "write": write,
        "limit_profiles": limit_profiles,
        "retrieval_hit_limit": retrieval_hit_limit,
        "top_neighbors_per_item": top_neighbors_per_item,
        "num_candidates": num_candidates,
        "vector_index_name": VECTOR_INDEX_NAME,
        "stats": stats.as_dict(),
        "sample_neighbors": sample_neighbors,
    }