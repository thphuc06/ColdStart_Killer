from __future__ import annotations

import math
import re
from time import monotonic
from typing import Any

import numpy as np

from src.mongodb import (
    get_item_hype_profiles_collection,
    get_item_item_cf_edges_collection,
    get_item_semantic_neighbors_collection,
    get_item_stats_collection,
    get_items_collection,
    get_user_item_signals_collection,
    get_user_profiles_collection,
)
from src.recommendation.schemas import EMBEDDING_DIM


DEFAULT_CANDIDATE_LIMIT = 60
CATALOG_SNAPSHOT_CACHE_TTL_SECONDS = 30.0
AMAZON_THUMBNAIL_TRANSFORM_PATTERN = re.compile(r"\._AC_(?:SR\d+,\d+|US\d+)_", re.IGNORECASE)

ITEM_PROJECTION = {
    "_id": 1,
    "title_en": 1,
    "brand": 1,
    "category_id": 1,
    "price_bucket": 1,
    "price_vnd": 1,
    "image_url": 1,
    "image_urls": 1,
    "quality_score": 1,
    "cold_start": 1,
}
ITEM_STATS_PROJECTION = {
    "item_id": 1,
    "quality_score": 1,
    "cold_start": 1,
    "ctr": 1,
    "cart_rate": 1,
    "purchase_rate": 1,
}
ITEM_PROFILE_PROJECTION = {
    "item_id": 1,
    "item_semantic_embedding": 1,
    "top_aspects": 1,
    "category_id": 1,
    "price_bucket": 1,
}

_catalog_snapshot_cache: tuple[
    float,
    tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]],
] | None = None


def clear_catalog_snapshot_cache() -> None:
    global _catalog_snapshot_cache
    _catalog_snapshot_cache = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def display_image_url(image_url: str) -> str:
    return AMAZON_THUMBNAIL_TRANSFORM_PATTERN.sub("._AC_", image_url, count=1)


def preferred_image_sources(item_doc: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return a usable primary image while retaining the seeded URL as fallback."""
    primary = str(item_doc.get("image_url") or "").strip()
    alternatives = [
        str(value).strip()
        for value in item_doc.get("image_urls", [])
        if isinstance(value, str) and value.strip()
    ]
    if not primary and alternatives:
        primary = alternatives[0]
    if not primary:
        return None, None

    primary_image_id = primary.split("._AC_", 1)[0]
    same_primary = next(
        (
            value
            for value in alternatives
            if value != primary
            and value.split("._AC_", 1)[0] == primary_image_id
            and not AMAZON_THUMBNAIL_TRANSFORM_PATTERN.search(value)
        ),
        None,
    )
    if same_primary:
        return same_primary, primary

    upgraded_primary = display_image_url(primary)
    if upgraded_primary != primary:
        return upgraded_primary, primary
    return primary, None


def _project_doc(doc: dict[str, Any], projection: dict[str, int] | None) -> dict[str, Any]:
    if not projection:
        return dict(doc)
    return {
        key: doc.get(key)
        for key, enabled in projection.items()
        if enabled and key in doc
    }


def _dedupe_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _embedding_array(value: Any) -> np.ndarray | None:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIM:
        return None
    try:
        vector = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if vector.shape != (EMBEDDING_DIM,) or not np.isfinite(vector).all():
        return None
    norm = float(np.linalg.norm(vector))
    if norm <= 0 or not math.isfinite(norm):
        return None
    return vector / norm


def _cosine_similarity(left: np.ndarray | None, right: np.ndarray | None) -> float:
    if left is None or right is None:
        return -1.0
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0 or not math.isfinite(denom):
        return -1.0
    return float(np.dot(left, right) / denom)


def _stable_exploration_score(item_id: str) -> float:
    if not item_id:
        return 0.0
    checksum = sum(ord(char) for char in item_id)
    return round(((checksum % 100) / 100.0), 6)


def _find_one(
    collection: Any,
    filter_doc: dict[str, Any],
    projection: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    doc = collection.find_one(filter_doc, projection) if hasattr(collection, "find_one") else None
    if doc is not None:
        return dict(doc)
    cursor = collection.find(filter_doc, projection)
    for row in cursor:
        return dict(row)
    return None


def _collection_docs(
    collection: Any,
    filter_doc: dict[str, Any],
    projection: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    return [_project_doc(dict(doc), projection) for doc in collection.find(filter_doc, projection)]


def load_user_profile(
    user_id_hash: str,
    *,
    user_profiles_collection: Any | None = None,
) -> dict[str, Any] | None:
    if user_profiles_collection is None:
        user_profiles_collection = get_user_profiles_collection()
    return _find_one(user_profiles_collection, {"user_id_hash": user_id_hash})


def load_user_signals(
    user_id_hash: str,
    *,
    user_item_signals_collection: Any | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if user_item_signals_collection is None:
        user_item_signals_collection = get_user_item_signals_collection()
    projection = {
        "user_id_hash": 1,
        "item_id": 1,
        "implicit_score": 1,
        "positive_score": 1,
        "negative_score": 1,
        "seed_eligible": 1,
        "intent_tier": 1,
        "contributions": 1,
        "event_counts": 1,
        "last_interaction_at": 1,
        "preference": 1,
    }
    docs = _collection_docs(user_item_signals_collection, {"user_id_hash": user_id_hash}, projection)

    def deliberate_score(doc: dict[str, Any]) -> float:
        contributions = doc.get("contributions") if isinstance(doc.get("contributions"), dict) else {}
        return _safe_float(contributions.get("engaged"), 0.0) + _safe_float(contributions.get("conversion"), 0.0)

    ranked = sorted(
        docs,
        key=lambda doc: (
            bool(doc.get("seed_eligible")),
            deliberate_score(doc),
            _safe_float(doc.get("implicit_score"), 0.0),
            _safe_float(doc.get("positive_score"), 0.0),
            str(doc.get("last_interaction_at") or ""),
        ),
        reverse=True,
    )
    return ranked[:limit]


def load_catalog_snapshot(
    *,
    items_collection: Any | None = None,
    item_stats_collection: Any | None = None,
    item_hype_profiles_collection: Any | None = None,
    include_item_profiles: bool = True,
    use_cache: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    global _catalog_snapshot_cache
    if use_cache and include_item_profiles and _catalog_snapshot_cache is not None:
        cached_at, cached_snapshot = _catalog_snapshot_cache
        if monotonic() - cached_at <= CATALOG_SNAPSHOT_CACHE_TTL_SECONDS:
            return cached_snapshot

    if items_collection is None:
        items_collection = get_items_collection()
    if item_stats_collection is None:
        item_stats_collection = get_item_stats_collection()
    if item_hype_profiles_collection is None:
        item_hype_profiles_collection = get_item_hype_profiles_collection()

    items_by_id = {
        str(doc.get("_id") or "").strip(): dict(doc)
        for doc in items_collection.find({}, ITEM_PROJECTION)
        if str(doc.get("_id") or "").strip()
    }
    item_stats_by_id = {
        str(doc.get("item_id") or doc.get("_id") or "").strip(): dict(doc)
        for doc in item_stats_collection.find({}, ITEM_STATS_PROJECTION)
        if str(doc.get("item_id") or doc.get("_id") or "").strip()
    }
    item_profiles_by_id = {}
    if include_item_profiles:
        item_profiles_by_id = {
            str(doc.get("item_id") or doc.get("_id") or "").strip(): dict(doc)
            for doc in item_hype_profiles_collection.find({}, ITEM_PROFILE_PROJECTION)
            if str(doc.get("item_id") or doc.get("_id") or "").strip()
        }
    snapshot = (items_by_id, item_stats_by_id, item_profiles_by_id)
    if use_cache and include_item_profiles:
        _catalog_snapshot_cache = (monotonic(), snapshot)
    return snapshot


def load_item_snapshot(
    item_ids: set[str],
    *,
    items_collection: Any | None = None,
    item_stats_collection: Any | None = None,
    item_hype_profiles_collection: Any | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    normalized_item_ids = sorted({str(item_id).strip() for item_id in item_ids if str(item_id).strip()})
    if not normalized_item_ids:
        return {}, {}, {}
    if items_collection is None:
        items_collection = get_items_collection()
    if item_stats_collection is None:
        item_stats_collection = get_item_stats_collection()
    if item_hype_profiles_collection is None:
        item_hype_profiles_collection = get_item_hype_profiles_collection()
    item_id_filter = {"$in": normalized_item_ids}
    items_by_id = {
        str(doc.get("_id") or "").strip(): dict(doc)
        for doc in items_collection.find({"_id": item_id_filter}, ITEM_PROJECTION)
        if str(doc.get("_id") or "").strip()
    }
    item_stats_by_id = {
        str(doc.get("item_id") or doc.get("_id") or "").strip(): dict(doc)
        for doc in item_stats_collection.find({"item_id": item_id_filter}, ITEM_STATS_PROJECTION)
        if str(doc.get("item_id") or doc.get("_id") or "").strip()
    }
    item_profiles_by_id = {
        str(doc.get("item_id") or doc.get("_id") or "").strip(): dict(doc)
        for doc in item_hype_profiles_collection.find({"item_id": item_id_filter}, ITEM_PROFILE_PROJECTION)
        if str(doc.get("item_id") or doc.get("_id") or "").strip()
    }
    return items_by_id, item_stats_by_id, item_profiles_by_id


def _base_candidate(
    item_id: str,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    item_doc = items_by_id.get(item_id)
    if not item_doc:
        return None
    item_stats = item_stats_by_id.get(item_id, {})
    cold_state = item_stats.get("cold_start") if isinstance(item_stats.get("cold_start"), dict) else {}
    item_cold_state = item_doc.get("cold_start") if isinstance(item_doc.get("cold_start"), dict) else {}
    is_cold_item = bool(
        cold_state.get("is_cold_item")
        if cold_state
        else item_cold_state.get("is_cold_item", True)
    )
    interaction_count = _safe_int(
        cold_state.get("interaction_count")
        if cold_state
        else item_cold_state.get("interaction_count"),
        0,
    )
    quality_score = max(
        _safe_float(item_stats.get("quality_score"), 0.0),
        _safe_float(item_doc.get("quality_score"), 0.0),
    )
    image_url, image_fallback_url = preferred_image_sources(item_doc)
    return {
        "item_id": item_id,
        "title": str(item_doc.get("title_en") or item_doc.get("title") or ""),
        "brand": str(item_doc.get("brand") or ""),
        "category_id": str(item_doc.get("category_id") or ""),
        "price_bucket": str(item_doc.get("price_bucket") or "unknown"),
        "price_vnd": item_doc.get("price_vnd"),
        "image_url": image_url,
        "image_fallback_url": image_fallback_url,
        "is_cold_item": is_cold_item,
        "interaction_count": interaction_count,
        "quality_score_raw": round(max(0.0, min(1.0, quality_score)), 6),
        "query_hybrid_score_raw": 0.0,
        "profile_score_raw": -1.0,
        "semantic_neighbor_score_raw": 0.0,
        "item_item_cf_score_raw": 0.0,
        "metadata_score_raw": 0.0,
        "cold_start_boost_raw": 1.0 if is_cold_item else 0.0,
        "exploration_score_raw": 0.0,
        "seen_penalty": 0.0,
        "negative_penalty": 0.0,
        "matched_intent": "",
        "matched_fact": "",
        "matched_channels": [],
        "candidate_sources": [],
        "matched_unit_ids": [],
        "matched_aspects": [],
        "matched_profile_interest_ids": [],
        "matched_interest_embedding": None,
        "matched_neighbor_embedding": None,
        "profile_interest_label": "",
        "cf_evidence": None,
        "debug": {},
    }


def profile_signal_for_item(
    profile: dict[str, Any] | None,
    item_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if not profile or not item_profile:
        return {
            "profile_score_raw": -1.0,
            "matched_profile_interest_ids": [],
            "matched_interest_embedding": None,
            "profile_interest_label": "",
        }

    item_vector = _embedding_array(item_profile.get("item_semantic_embedding"))
    if item_vector is None:
        return {
            "profile_score_raw": -1.0,
            "matched_profile_interest_ids": [],
            "matched_interest_embedding": None,
            "profile_interest_label": "",
        }

    best_score = -1.0
    best_interest_id = ""
    best_interest_label = ""
    best_interest_embedding: list[float] | None = None
    interests = profile.get("interest_vectors") if isinstance(profile.get("interest_vectors"), list) else []
    item_category_id = str(item_profile.get("category_id") or "").strip()
    scored_interests: list[tuple[float, dict[str, Any]]] = []
    for interest in interests:
        embedding = _embedding_array(interest.get("embedding"))
        if embedding is None:
            continue
        weight_factor = max(0.25, min(1.0, _safe_float(interest.get("weight"), 0.0) / 5.0))
        score = _cosine_similarity(item_vector, embedding) * weight_factor
        scored_interests.append((score, interest))

    category_matches = [
        (score, interest)
        for score, interest in scored_interests
        if score > 0
        and item_category_id
        and item_category_id
        in {
            str(category).strip()
            for category in (
                interest.get("categories") if isinstance(interest.get("categories"), list) else []
            )
        }
    ]
    has_categorized_interests = any(
        isinstance(interest.get("categories"), list) and any(str(value).strip() for value in interest["categories"])
        for _score, interest in scored_interests
    )
    category_guarded = bool(item_category_id and has_categorized_interests)
    eligible_interests = category_matches if category_guarded else scored_interests
    for score, interest in eligible_interests:
        if score > best_score:
            best_score = score
            best_interest_id = str(interest.get("interest_id") or "")
            best_interest_label = str(interest.get("label") or "")
            best_interest_embedding = list(interest.get("embedding", [])) if isinstance(interest.get("embedding"), list) else None

    if best_score <= -1.0 and not category_guarded:
        long_term_vector = _embedding_array(profile.get("long_term_embedding"))
        if long_term_vector is not None:
            best_score = _cosine_similarity(item_vector, long_term_vector)

    return {
        "profile_score_raw": round(best_score, 6),
        "matched_profile_interest_ids": [best_interest_id] if best_interest_id else [],
        "matched_interest_embedding": best_interest_embedding,
        "profile_interest_label": best_interest_label,
    }


def metadata_affinity_score(
    profile: dict[str, Any] | None,
    item_doc: dict[str, Any],
    item_stats: dict[str, Any] | None = None,
) -> float:
    if not profile:
        return 0.0
    item_stats = item_stats or {}
    category_affinity = profile.get("category_affinity") if isinstance(profile.get("category_affinity"), dict) else {}
    brand_affinity = profile.get("brand_affinity") if isinstance(profile.get("brand_affinity"), dict) else {}
    price_affinity = profile.get("price_affinity") if isinstance(profile.get("price_affinity"), dict) else {}
    price_buckets = price_affinity.get("preferred_buckets") if isinstance(price_affinity.get("preferred_buckets"), dict) else {}

    components: list[float] = []
    category_id = str(item_doc.get("category_id") or "")
    brand = str(item_doc.get("brand") or "")
    price_bucket = str(item_doc.get("price_bucket") or "")
    if category_id:
        components.append(_safe_float(category_affinity.get(category_id), 0.0))
    if brand:
        components.append(_safe_float(brand_affinity.get(brand), 0.0))
    if price_bucket:
        components.append(_safe_float(price_buckets.get(price_bucket), 0.0))
    if item_stats:
        components.append(min(1.0, _safe_float(item_stats.get("quality_score"), 0.0)))
    if not components:
        return 0.0
    return round(sum(components) / len(components), 6)


def penalty_snapshot(
    profile: dict[str, Any] | None,
    item_doc: dict[str, Any],
    item_id: str,
    *,
    surface: str,
) -> dict[str, float]:
    if not profile:
        return {"seen_penalty": 0.0, "negative_penalty": 0.0}

    seen_penalty = 0.0
    recent_items = set(str(value) for value in profile.get("recent_item_ids", []))
    purchased_items = set(str(value) for value in profile.get("purchased_item_ids", []))
    if item_id in recent_items:
        seen_penalty += 0.08 if surface == "search" else 0.15
    if item_id in purchased_items:
        seen_penalty += 0.20 if surface == "search" else 0.60

    negative = profile.get("negative_preferences") if isinstance(profile.get("negative_preferences"), dict) else {}
    negative_penalty = 0.0
    if item_id in {str(value) for value in negative.get("item_ids", [])}:
        negative_penalty += 0.45 if surface == "search" else 0.85
    brand = str(item_doc.get("brand") or "")
    category_id = str(item_doc.get("category_id") or "")
    if brand and brand in {str(value) for value in negative.get("brands", [])}:
        negative_penalty += 0.18 if surface == "search" else 0.30
    if category_id and category_id in {str(value) for value in negative.get("categories", [])}:
        negative_penalty += 0.15 if surface == "search" else 0.25
    return {
        "seen_penalty": round(min(seen_penalty, 0.75), 6),
        "negative_penalty": round(min(negative_penalty, 0.95), 6),
    }


def enrich_with_profile_context(
    candidates: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | None,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
    item_profiles_by_id: dict[str, dict[str, Any]],
    surface: str,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        item_id = str(candidate.get("item_id") or "")
        item_doc = items_by_id.get(item_id, {})
        item_stats = item_stats_by_id.get(item_id, {})
        item_profile = item_profiles_by_id.get(item_id)

        profile_signal = profile_signal_for_item(profile, item_profile)
        penalties = penalty_snapshot(profile, item_doc, item_id, surface=surface)

        row = dict(candidate)
        image_url, image_fallback_url = preferred_image_sources(item_doc)
        if image_url:
            row["image_url"] = image_url
        if image_fallback_url:
            row["image_fallback_url"] = image_fallback_url
        row["profile_score_raw"] = max(
            _safe_float(row.get("profile_score_raw"), -1.0),
            _safe_float(profile_signal.get("profile_score_raw"), -1.0),
        )
        row["metadata_score_raw"] = max(
            _safe_float(row.get("metadata_score_raw"), 0.0),
            metadata_affinity_score(profile, item_doc, item_stats),
        )
        row["seen_penalty"] = max(_safe_float(row.get("seen_penalty"), 0.0), penalties["seen_penalty"])
        row["negative_penalty"] = max(
            _safe_float(row.get("negative_penalty"), 0.0),
            penalties["negative_penalty"],
        )
        row["matched_profile_interest_ids"] = _dedupe_text(
            list(row.get("matched_profile_interest_ids", []))
            + list(profile_signal.get("matched_profile_interest_ids", []))
        )
        if row.get("matched_interest_embedding") is None and isinstance(profile_signal.get("matched_interest_embedding"), list):
            row["matched_interest_embedding"] = list(profile_signal.get("matched_interest_embedding", []))
        if not row.get("profile_interest_label"):
            row["profile_interest_label"] = profile_signal.get("profile_interest_label", "")
        enriched.append(row)
    return enriched


def build_profile_candidates(
    profile: dict[str, Any] | None,
    *,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
    item_profiles_by_id: dict[str, dict[str, Any]],
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    exclude_item_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not profile:
        return []
    exclude_item_ids = exclude_item_ids or set()
    rows: list[dict[str, Any]] = []
    for item_id, item_profile in item_profiles_by_id.items():
        if item_id in exclude_item_ids:
            continue
        base = _base_candidate(item_id, items_by_id, item_stats_by_id)
        if base is None:
            continue
        signal = profile_signal_for_item(profile, item_profile)
        if _safe_float(signal.get("profile_score_raw"), -1.0) <= 0:
            continue
        base["profile_score_raw"] = _safe_float(signal.get("profile_score_raw"), -1.0)
        base["metadata_score_raw"] = metadata_affinity_score(profile, items_by_id[item_id], item_stats_by_id.get(item_id))
        base["matched_profile_interest_ids"] = list(signal.get("matched_profile_interest_ids", []))
        if isinstance(signal.get("matched_interest_embedding"), list):
            base["matched_interest_embedding"] = list(signal.get("matched_interest_embedding", []))
        base["profile_interest_label"] = str(signal.get("profile_interest_label") or "")
        base["candidate_sources"] = ["profile"]
        base["matched_channels"] = ["profile"]
        rows.append(base)
    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("profile_score_raw"), -1.0),
            _safe_float(row.get("metadata_score_raw"), 0.0),
            _safe_float(row.get("quality_score_raw"), 0.0),
        ),
        reverse=True,
    )[:limit]


def build_semantic_neighbor_candidates(
    source_item_ids: list[str],
    *,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
    item_profiles_by_id: dict[str, dict[str, Any]] | None = None,
    item_semantic_neighbors_collection: Any | None = None,
    limit_per_source: int = 12,
    exclude_item_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if item_semantic_neighbors_collection is None:
        item_semantic_neighbors_collection = get_item_semantic_neighbors_collection()
    exclude_item_ids = exclude_item_ids or set()
    rows: list[dict[str, Any]] = []

    for source_item_id in source_item_ids:
        doc = _find_one(item_semantic_neighbors_collection, {"item_id": source_item_id}) or _find_one(
            item_semantic_neighbors_collection,
            {"_id": source_item_id},
        )
        if not doc:
            continue
        neighbors = doc.get("neighbors") if isinstance(doc.get("neighbors"), list) else []
        for neighbor in neighbors[:limit_per_source]:
            item_id = str(neighbor.get("neighbor_item_id") or "").strip()
            if not item_id or item_id in exclude_item_ids or item_id == source_item_id:
                continue
            base = _base_candidate(item_id, items_by_id, item_stats_by_id)
            if base is None:
                continue
            base["semantic_neighbor_score_raw"] = _safe_float(neighbor.get("neighbor_score"), 0.0)
            base["candidate_sources"] = ["semantic_neighbor"]
            base["matched_channels"] = ["semantic_neighbor"]
            base["matched_unit_ids"] = _dedupe_text(list(neighbor.get("matched_unit_ids", [])))
            base["matched_aspects"] = _dedupe_text(list(neighbor.get("matched_aspects", [])))
            if item_profiles_by_id is not None:
                source_profile = item_profiles_by_id.get(source_item_id)
                if isinstance(source_profile, dict) and isinstance(source_profile.get("item_semantic_embedding"), list):
                    base["matched_neighbor_embedding"] = list(source_profile.get("item_semantic_embedding", []))
            base["debug"] = {"source_item_id": source_item_id}
            rows.append(base)

    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("semantic_neighbor_score_raw"), 0.0),
            _safe_float(row.get("quality_score_raw"), 0.0),
        ),
        reverse=True,
    )


def build_cf_candidates(
    source_item_ids: list[str],
    *,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
    item_item_cf_edges_collection: Any | None = None,
    limit_per_source: int = 12,
    exclude_item_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    if item_item_cf_edges_collection is None:
        item_item_cf_edges_collection = get_item_item_cf_edges_collection()
    exclude_item_ids = exclude_item_ids or set()
    rows: list[dict[str, Any]] = []

    for source_item_id in source_item_ids:
        edges = _collection_docs(
            item_item_cf_edges_collection,
            {"item_id": source_item_id},
            {
                "item_id": 1,
                "neighbor_item_id": 1,
                "cf_score": 1,
                "support": 1,
                "co_click_count": 1,
                "co_cart_count": 1,
                "co_purchase_count": 1,
            },
        )
        ranked = sorted(edges, key=lambda edge: _safe_float(edge.get("cf_score"), 0.0), reverse=True)
        for edge in ranked[:limit_per_source]:
            item_id = str(edge.get("neighbor_item_id") or "").strip()
            if not item_id or item_id in exclude_item_ids or item_id == source_item_id:
                continue
            base = _base_candidate(item_id, items_by_id, item_stats_by_id)
            if base is None:
                continue
            cf_score = _safe_float(edge.get("cf_score"), 0.0)
            base["item_item_cf_score_raw"] = cf_score
            base["candidate_sources"] = ["cf"]
            base["matched_channels"] = ["cf"]
            base["cf_evidence"] = {
                "source_item_id": source_item_id,
                "support": _safe_int(edge.get("support"), 0),
                "cf_score": round(cf_score, 6),
                "co_click_count": _safe_int(edge.get("co_click_count"), 0),
                "co_cart_count": _safe_int(edge.get("co_cart_count"), 0),
            }
            rows.append(base)

    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("item_item_cf_score_raw"), 0.0),
            _safe_float(row.get("quality_score_raw"), 0.0),
        ),
        reverse=True,
    )


def build_quality_candidates(
    *,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    exclude_item_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude_item_ids = exclude_item_ids or set()
    rows: list[dict[str, Any]] = []
    for item_id in items_by_id:
        if item_id in exclude_item_ids:
            continue
        base = _base_candidate(item_id, items_by_id, item_stats_by_id)
        if base is None:
            continue
        item_stats = item_stats_by_id.get(item_id, {})
        popularity_score = min(1.0, _safe_int(item_stats.get("cold_start", {}).get("interaction_count"), 0) / 20.0)
        base["metadata_score_raw"] = max(base["metadata_score_raw"], round(popularity_score, 6))
        base["candidate_sources"] = ["quality"]
        base["matched_channels"] = ["quality"]
        rows.append(base)
    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("quality_score_raw"), 0.0),
            _safe_float(row.get("metadata_score_raw"), 0.0),
        ),
        reverse=True,
    )[:limit]


def build_cold_exploration_candidates(
    *,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    exclude_item_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude_item_ids = exclude_item_ids or set()
    rows: list[dict[str, Any]] = []
    for item_id in items_by_id:
        if item_id in exclude_item_ids:
            continue
        base = _base_candidate(item_id, items_by_id, item_stats_by_id)
        if base is None or not base.get("is_cold_item"):
            continue
        base["exploration_score_raw"] = _stable_exploration_score(item_id)
        base["candidate_sources"] = ["exploration"]
        base["matched_channels"] = ["exploration"]
        rows.append(base)
    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("exploration_score_raw"), 0.0),
            _safe_float(row.get("quality_score_raw"), 0.0),
        ),
        reverse=True,
    )[:limit]


def build_same_category_price_candidates(
    source_item_id: str,
    *,
    items_by_id: dict[str, dict[str, Any]],
    item_stats_by_id: dict[str, dict[str, Any]],
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    exclude_item_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    exclude_item_ids = exclude_item_ids or set()
    source_item = items_by_id.get(source_item_id)
    if not source_item:
        return []

    source_category = str(source_item.get("category_id") or "")
    source_price_bucket = str(source_item.get("price_bucket") or "")
    source_price = _safe_float(source_item.get("price_vnd"), -1.0)
    rows: list[dict[str, Any]] = []
    for item_id, item_doc in items_by_id.items():
        if item_id == source_item_id or item_id in exclude_item_ids:
            continue
        category_match = 1.0 if str(item_doc.get("category_id") or "") == source_category else 0.0
        price_bucket_match = 1.0 if str(item_doc.get("price_bucket") or "") == source_price_bucket else 0.0
        price_match = 0.0
        candidate_price = _safe_float(item_doc.get("price_vnd"), -1.0)
        if source_price > 0 and candidate_price > 0:
            price_gap = abs(source_price - candidate_price) / max(source_price, candidate_price)
            price_match = max(0.0, 1.0 - price_gap)
        fallback_score = max(0.0, min(1.0, (0.60 * category_match) + (0.20 * price_bucket_match) + (0.20 * price_match)))
        if fallback_score <= 0:
            continue
        base = _base_candidate(item_id, items_by_id, item_stats_by_id)
        if base is None:
            continue
        base["metadata_score_raw"] = fallback_score
        base["candidate_sources"] = ["metadata_fallback"]
        base["matched_channels"] = ["metadata_fallback"]
        rows.append(base)

    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("metadata_score_raw"), 0.0),
            _safe_float(row.get("quality_score_raw"), 0.0),
        ),
        reverse=True,
    )[:limit]


def merge_candidate_rows(*candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in candidate_groups:
        for candidate in group:
            item_id = str(candidate.get("item_id") or "").strip()
            if not item_id:
                continue
            existing = merged.get(item_id)
            if existing is None:
                merged[item_id] = dict(candidate)
                continue

            existing["query_hybrid_score_raw"] = max(
                _safe_float(existing.get("query_hybrid_score_raw"), 0.0),
                _safe_float(candidate.get("query_hybrid_score_raw"), 0.0),
            )
            existing["profile_score_raw"] = max(
                _safe_float(existing.get("profile_score_raw"), -1.0),
                _safe_float(candidate.get("profile_score_raw"), -1.0),
            )
            existing["semantic_neighbor_score_raw"] = max(
                _safe_float(existing.get("semantic_neighbor_score_raw"), 0.0),
                _safe_float(candidate.get("semantic_neighbor_score_raw"), 0.0),
            )
            existing["item_item_cf_score_raw"] = max(
                _safe_float(existing.get("item_item_cf_score_raw"), 0.0),
                _safe_float(candidate.get("item_item_cf_score_raw"), 0.0),
            )
            existing["metadata_score_raw"] = max(
                _safe_float(existing.get("metadata_score_raw"), 0.0),
                _safe_float(candidate.get("metadata_score_raw"), 0.0),
            )
            existing["cold_start_boost_raw"] = max(
                _safe_float(existing.get("cold_start_boost_raw"), 0.0),
                _safe_float(candidate.get("cold_start_boost_raw"), 0.0),
            )
            existing["exploration_score_raw"] = max(
                _safe_float(existing.get("exploration_score_raw"), 0.0),
                _safe_float(candidate.get("exploration_score_raw"), 0.0),
            )
            existing["quality_score_raw"] = max(
                _safe_float(existing.get("quality_score_raw"), 0.0),
                _safe_float(candidate.get("quality_score_raw"), 0.0),
            )
            existing["seen_penalty"] = max(
                _safe_float(existing.get("seen_penalty"), 0.0),
                _safe_float(candidate.get("seen_penalty"), 0.0),
            )
            existing["negative_penalty"] = max(
                _safe_float(existing.get("negative_penalty"), 0.0),
                _safe_float(candidate.get("negative_penalty"), 0.0),
            )
            existing["candidate_sources"] = _dedupe_text(
                list(existing.get("candidate_sources", [])) + list(candidate.get("candidate_sources", []))
            )
            existing["matched_channels"] = _dedupe_text(
                list(existing.get("matched_channels", [])) + list(candidate.get("matched_channels", []))
            )
            existing["matched_unit_ids"] = _dedupe_text(
                list(existing.get("matched_unit_ids", [])) + list(candidate.get("matched_unit_ids", []))
            )
            existing["matched_aspects"] = _dedupe_text(
                list(existing.get("matched_aspects", [])) + list(candidate.get("matched_aspects", []))
            )
            existing["matched_profile_interest_ids"] = _dedupe_text(
                list(existing.get("matched_profile_interest_ids", []))
                + list(candidate.get("matched_profile_interest_ids", []))
            )
            if existing.get("matched_interest_embedding") is None and isinstance(candidate.get("matched_interest_embedding"), list):
                existing["matched_interest_embedding"] = list(candidate.get("matched_interest_embedding", []))
            if existing.get("matched_neighbor_embedding") is None and isinstance(candidate.get("matched_neighbor_embedding"), list):
                existing["matched_neighbor_embedding"] = list(candidate.get("matched_neighbor_embedding", []))
            if not existing.get("matched_intent"):
                existing["matched_intent"] = candidate.get("matched_intent", "")
            if not existing.get("matched_fact"):
                existing["matched_fact"] = candidate.get("matched_fact", "")
            if not existing.get("profile_interest_label"):
                existing["profile_interest_label"] = candidate.get("profile_interest_label", "")
            current_cf = existing.get("cf_evidence") if isinstance(existing.get("cf_evidence"), dict) else None
            next_cf = candidate.get("cf_evidence") if isinstance(candidate.get("cf_evidence"), dict) else None
            if next_cf and (
                current_cf is None
                or _safe_float(next_cf.get("cf_score"), 0.0) > _safe_float(current_cf.get("cf_score"), 0.0)
            ):
                existing["cf_evidence"] = dict(next_cf)
    return list(merged.values())
