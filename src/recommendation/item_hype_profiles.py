from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pymongo import UpdateOne

from src.recommendation.schemas import EMBEDDING_DIM, ItemHypeProfileDocument
from src.schemas import to_mongo_dict
from src.utils import utc_now_iso


ASPECT_WEIGHTS: dict[str, float] = {
    "constraint": 1.15,
    "persona": 1.10,
    "benefit": 1.05,
    "function": 1.00,
    "occasion": 0.95,
    "style": 0.90,
}
DEFAULT_ASPECT_WEIGHT = 1.00
DEFAULT_TOP_UNIT_LIMIT = 5
DEFAULT_TOP_ASPECT_LIMIT = 5


@dataclass
class ProfileBuildStats:
    units_seen: int = 0
    valid_units: int = 0
    invalid_dimension_units: int = 0
    non_finite_units: int = 0
    non_positive_weight_units: int = 0
    profiles_built: int = 0
    profiles_skipped: int = 0
    profiles_written: int = 0
    bulk_write_batches: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "ProfileBuildStats") -> None:
        self.units_seen += other.units_seen
        self.valid_units += other.valid_units
        self.invalid_dimension_units += other.invalid_dimension_units
        self.non_finite_units += other.non_finite_units
        self.non_positive_weight_units += other.non_positive_weight_units
        self.profiles_built += other.profiles_built
        self.profiles_skipped += other.profiles_skipped
        self.profiles_written += other.profiles_written
        self.bulk_write_batches += other.bulk_write_batches
        self.errors.extend(other.errors)

    def as_dict(self) -> dict[str, Any]:
        return {
            "units_seen": self.units_seen,
            "valid_units": self.valid_units,
            "invalid_dimension_units": self.invalid_dimension_units,
            "non_finite_units": self.non_finite_units,
            "non_positive_weight_units": self.non_positive_weight_units,
            "profiles_built": self.profiles_built,
            "profiles_skipped": self.profiles_skipped,
            "profiles_written": self.profiles_written,
            "bulk_write_batches": self.bulk_write_batches,
            "errors": list(self.errors),
        }


def aspect_weight(aspect: Any) -> float:
    key = str(aspect or "").strip().lower()
    return ASPECT_WEIGHTS.get(key, DEFAULT_ASPECT_WEIGHT)


def coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(confidence):
        return 0.0
    return max(confidence, 0.0)


def validate_unit_embedding(value: Any) -> np.ndarray | None:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIM:
        return None
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if vector.shape != (EMBEDDING_DIM,) or not np.isfinite(vector).all():
        return None
    return vector


def _first_text(*values: Any, default: str = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _top_aspects(weighted_units: list[dict[str, Any]], limit: int = DEFAULT_TOP_ASPECT_LIMIT) -> list[str]:
    aspect_scores: dict[str, float] = {}
    for unit in weighted_units:
        aspect = str(unit.get("aspect") or "").strip().lower()
        if not aspect:
            continue
        aspect_scores[aspect] = aspect_scores.get(aspect, 0.0) + float(unit["weight"])
    return [
        aspect
        for aspect, _ in sorted(aspect_scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def build_profile_from_hype_units(
    item_id: str,
    units: Iterable[dict[str, Any]],
    *,
    item_doc: dict[str, Any] | None = None,
    updated_at: str | None = None,
) -> tuple[dict[str, Any] | None, ProfileBuildStats]:
    stats = ProfileBuildStats()
    vectors: list[np.ndarray] = []
    weights: list[float] = []
    weighted_units: list[dict[str, Any]] = []
    first_unit: dict[str, Any] | None = None

    for unit in units:
        stats.units_seen += 1
        if first_unit is None:
            first_unit = unit
        vector = validate_unit_embedding(unit.get("embedding"))
        if vector is None:
            if isinstance(unit.get("embedding"), list) and len(unit.get("embedding", [])) == EMBEDDING_DIM:
                stats.non_finite_units += 1
            else:
                stats.invalid_dimension_units += 1
            continue

        weight = coerce_confidence(unit.get("confidence")) * aspect_weight(unit.get("aspect"))
        if weight <= 0:
            stats.non_positive_weight_units += 1
            continue

        stats.valid_units += 1
        vectors.append(vector)
        weights.append(weight)
        weighted_units.append(
            {
                "unit_id": str(unit.get("_id") or ""),
                "aspect": unit.get("aspect"),
                "weight": weight,
            }
        )

    if not vectors:
        stats.profiles_skipped += 1
        stats.errors.append(f"{item_id}: no valid weighted HyPE embeddings")
        return None, stats

    centroid = np.average(np.vstack(vectors), axis=0, weights=np.asarray(weights, dtype=np.float64))
    norm = float(np.linalg.norm(centroid))
    if not math.isfinite(norm) or norm <= 0:
        stats.profiles_skipped += 1
        stats.errors.append(f"{item_id}: centroid norm is invalid")
        return None, stats

    centroid = centroid / norm
    if not np.isfinite(centroid).all():
        stats.profiles_skipped += 1
        stats.errors.append(f"{item_id}: normalized centroid contains non-finite values")
        return None, stats

    item_doc = item_doc or {}
    first_unit = first_unit or {}
    sorted_units = sorted(weighted_units, key=lambda unit: unit["weight"], reverse=True)
    profile = ItemHypeProfileDocument(
        _id=item_id,
        item_id=item_id,
        item_semantic_embedding=centroid.astype(float).tolist(),
        top_hype_unit_ids=[
            unit["unit_id"] for unit in sorted_units[:DEFAULT_TOP_UNIT_LIMIT] if unit["unit_id"]
        ],
        top_aspects=_top_aspects(weighted_units),
        num_hype_units=stats.valid_units,
        category_id=_first_text(item_doc.get("category_id"), first_unit.get("category_id")),
        price_bucket=_first_text(item_doc.get("price_bucket"), first_unit.get("price_bucket"), default="unknown"),
        updated_at=updated_at or utc_now_iso(),
    )
    stats.profiles_built += 1
    return to_mongo_dict(profile), stats


def iter_hype_unit_groups(
    retrieval_units_collection: Any,
    *,
    limit_profiles: int | None = None,
) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    projection = {
        "_id": 1,
        "item_id": 1,
        "unit_type": 1,
        "embedding": 1,
        "confidence": 1,
        "aspect": 1,
        "category_id": 1,
        "price_bucket": 1,
    }
    if limit_profiles is not None and hasattr(retrieval_units_collection, "aggregate"):
        item_cursor = retrieval_units_collection.aggregate(
            [
                {"$match": {"unit_type": "hype_question"}},
                {"$group": {"_id": "$item_id"}},
                {"$match": {"_id": {"$type": "string", "$ne": ""}}},
                {"$limit": int(limit_profiles)},
            ],
            allowDiskUse=True,
        )
        for row in item_cursor:
            item_id = str(row.get("_id") or "").strip()
            if not item_id:
                continue
            units = list(
                retrieval_units_collection.find(
                    {"unit_type": "hype_question", "item_id": item_id},
                    projection,
                )
            )
            if units:
                yield item_id, units
        return

    cursor = retrieval_units_collection.find({"unit_type": "hype_question"}, projection)
    if hasattr(cursor, "batch_size"):
        cursor = cursor.batch_size(1000)

    groups: dict[str, list[dict[str, Any]]] = {}
    for unit in cursor:
        item_id = str(unit.get("item_id") or "").strip()
        if not item_id:
            continue
        groups.setdefault(item_id, []).append(unit)

    for index, item_id in enumerate(sorted(groups)):
        if limit_profiles is not None and index >= limit_profiles:
            return
        yield item_id, groups[item_id]


def _item_metadata(items_collection: Any | None, item_id: str) -> dict[str, Any] | None:
    if items_collection is None:
        return None
    return items_collection.find_one({"_id": item_id}, {"category_id": 1, "price_bucket": 1})


def _upsert_operation(profile_doc: dict[str, Any]) -> UpdateOne:
    doc = dict(profile_doc)
    doc_id = doc.pop("_id", doc["item_id"])
    return UpdateOne({"_id": doc_id}, {"$set": doc, "$setOnInsert": {"_id": doc_id}}, upsert=True)


def build_item_hype_profiles(
    *,
    retrieval_units_collection: Any,
    items_collection: Any | None = None,
    item_hype_profiles_collection: Any | None = None,
    limit_profiles: int | None = None,
    write: bool = False,
    batch_size: int = 500,
) -> dict[str, Any]:
    if limit_profiles is not None and limit_profiles <= 0:
        raise ValueError("limit_profiles must be positive when provided")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if write and item_hype_profiles_collection is None:
        raise ValueError("item_hype_profiles_collection is required when write=True")

    stats = ProfileBuildStats()
    sample_profiles: list[dict[str, Any]] = []
    operations: list[UpdateOne] = []
    updated_at = utc_now_iso()

    for item_id, units in iter_hype_unit_groups(retrieval_units_collection, limit_profiles=limit_profiles):
        item_doc = _item_metadata(items_collection, item_id)
        profile_doc, profile_stats = build_profile_from_hype_units(
            item_id,
            units,
            item_doc=item_doc,
            updated_at=updated_at,
        )
        stats.merge(profile_stats)
        if profile_doc is None:
            continue

        if len(sample_profiles) < 3:
            sample = dict(profile_doc)
            sample["embedding_preview"] = sample.pop("item_semantic_embedding")[:5]
            sample_profiles.append(sample)

        if write:
            operations.append(_upsert_operation(profile_doc))
            if len(operations) >= batch_size:
                result = item_hype_profiles_collection.bulk_write(operations, ordered=False)
                stats.bulk_write_batches += 1
                stats.profiles_written += result.upserted_count + result.modified_count + result.matched_count
                operations = []

    if write and operations:
        result = item_hype_profiles_collection.bulk_write(operations, ordered=False)
        stats.bulk_write_batches += 1
        stats.profiles_written += result.upserted_count + result.modified_count + result.matched_count

    return {
        "ok": stats.profiles_built > 0 and not stats.errors,
        "write": write,
        "limit_profiles": limit_profiles,
        "stats": stats.as_dict(),
        "sample_profiles": sample_profiles,
    }
