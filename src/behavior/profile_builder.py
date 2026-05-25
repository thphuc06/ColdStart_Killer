from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
from pymongo import UpdateOne

from src.behavior.intent_hygiene import (
    is_valid_interest_label,
    normalize_interest_label,
    sanitize_interest_labels,
)
from src.behavior.schemas import InterestVector, UserProfileDocument
from src.config import get_settings
from src.recommendation.schemas import EMBEDDING_DIM
from src.schemas import to_mongo_dict
from src.utils import utc_now_iso


INTEREST_MERGE_THRESHOLD = 0.72
MAX_INTERESTS_PER_USER = 8
MAX_INTEREST_WEIGHT = 20.0
POSITIVE_SIGNAL_THRESHOLD = 0.5
RECENT_ITEM_LIMIT = 20
PURCHASED_ITEM_LIMIT = 20
NEGATIVE_ENTITY_THRESHOLD = 2
DEFAULT_BATCH_SIZE = 500
POSITIVE_EVENT_TYPES = {"click", "view_detail", "wishlist", "add_to_cart", "purchase"}
SURFACE_WEIGHTS = {
    "search": 1.10,
    "home": 1.00,
    "detail_similar": 1.00,
    "onboarding": 1.00,
}
QUERY_INTENT_STRENGTH = {
    "specific": 1.20,
    "constraint_rich": 1.12,
    "normal": 1.00,
    "broad": 0.85,
    "exploratory": 0.75,
    "none": 1.00,
}
LONG_TERM_HALF_LIFE_DAYS = 30.0


@dataclass
class ProfileBuildStats:
    users_seen: int = 0
    users_skipped: int = 0
    profiles_built: int = 0
    profiles_written: int = 0
    bulk_write_batches: int = 0
    item_profiles_missing: int = 0
    invalid_signal_embeddings: int = 0
    non_finite_profiles: int = 0
    invalid_interest_labels_dropped: int = 0
    calibration: dict[str, float | int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "users_seen": self.users_seen,
            "users_skipped": self.users_skipped,
            "profiles_built": self.profiles_built,
            "profiles_written": self.profiles_written,
            "bulk_write_batches": self.bulk_write_batches,
            "item_profiles_missing": self.item_profiles_missing,
            "invalid_signal_embeddings": self.invalid_signal_embeddings,
            "non_finite_profiles": self.non_finite_profiles,
            "invalid_interest_labels_dropped": self.invalid_interest_labels_dropped,
            "calibration": dict(self.calibration),
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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def _normalize_vector(vector: np.ndarray | None) -> list[float]:
    if vector is None:
        return []
    norm = float(np.linalg.norm(vector))
    if norm <= 0 or not math.isfinite(norm):
        return []
    normalized = vector / norm
    if not np.isfinite(normalized).all():
        return []
    return normalized.astype(float).tolist()


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0 or not math.isfinite(denom):
        return -1.0
    return float(np.dot(left, right) / denom)


def _max_timestamp(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _to_datetime(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _recency_decay(timestamp: str | None, updated_at: str, half_life_days: float = LONG_TERM_HALF_LIFE_DAYS) -> float:
    event_time = _to_datetime(timestamp)
    now_time = _to_datetime(updated_at)
    if event_time is None or now_time is None:
        return 1.0
    age_days = max(0.0, (now_time - event_time).total_seconds() / 86_400)
    return float(0.5 ** (age_days / half_life_days))


def _normalize_blend(components: list[tuple[np.ndarray | None, float]]) -> np.ndarray | None:
    valid_components: list[tuple[np.ndarray, float]] = []
    for vector, weight in components:
        if vector is None or weight <= 0:
            continue
        valid_components.append((vector, weight))
    if not valid_components:
        return None
    blended = np.zeros(EMBEDDING_DIM, dtype=np.float64)
    for vector, weight in valid_components:
        blended += vector * weight
    norm = float(np.linalg.norm(blended))
    if norm <= 0 or not math.isfinite(norm):
        return None
    normalized = blended / norm
    if not np.isfinite(normalized).all():
        return None
    return normalized


def _first_valid_embedding(candidates: list[Any]) -> np.ndarray | None:
    for candidate in candidates:
        vector = _embedding_array(candidate)
        if vector is not None:
            return vector
    return None


def _query_vector_from_context(event: dict[str, Any], log: dict[str, Any] | None) -> np.ndarray | None:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if metadata:
        direct = _embedding_array(metadata.get("query_embedding"))
        if direct is not None:
            return direct
    if not isinstance(log, dict):
        return None
    query = log.get("query") if isinstance(log.get("query"), dict) else {}
    return _embedding_array(query.get("query_embedding")) if query else None


def _matched_interest_vector(event: dict[str, Any], log: dict[str, Any] | None) -> np.ndarray | None:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if metadata:
        direct = _embedding_array(metadata.get("matched_interest_embedding"))
        if direct is not None:
            return direct
    if not isinstance(log, dict):
        return None
    attribution = log.get("attribution") if isinstance(log.get("attribution"), dict) else {}
    return _embedding_array(attribution.get("matched_interest_embedding")) if attribution else None


def _matched_neighbor_vector(event: dict[str, Any], log: dict[str, Any] | None) -> np.ndarray | None:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    if metadata:
        direct = _embedding_array(metadata.get("matched_neighbor_embedding"))
        if direct is not None:
            return direct
    if not isinstance(log, dict):
        return None
    attribution = log.get("attribution") if isinstance(log.get("attribution"), dict) else {}
    return _embedding_array(attribution.get("matched_neighbor_embedding")) if attribution else None


def _source_item_id(event: dict[str, Any], log: dict[str, Any] | None) -> str | None:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    source = str(metadata.get("source_item_id") or "").strip() if metadata else ""
    if source:
        return source
    if not isinstance(log, dict):
        return None
    attribution = log.get("attribution") if isinstance(log.get("attribution"), dict) else {}
    cf_evidence = attribution.get("cf_evidence") if isinstance(attribution.get("cf_evidence"), dict) else {}
    source = str(cf_evidence.get("source_item_id") or "").strip() if cf_evidence else ""
    return source or None


def _matched_unit_vectors(
    log: dict[str, Any] | None,
    retrieval_units_by_id: dict[str, dict[str, Any]],
    item_vector: np.ndarray,
) -> tuple[np.ndarray | None, np.ndarray | None, bool]:
    if not isinstance(log, dict):
        return None, None, False
    attribution = log.get("attribution") if isinstance(log.get("attribution"), dict) else {}
    unit_ids = attribution.get("matched_unit_ids") if isinstance(attribution.get("matched_unit_ids"), list) else []
    unit_vectors: list[tuple[np.ndarray, dict[str, Any]]] = []
    for unit_id in unit_ids[:5]:
        unit_doc = retrieval_units_by_id.get(str(unit_id).strip())
        if not isinstance(unit_doc, dict):
            continue
        vector = _embedding_array(unit_doc.get("embedding"))
        if vector is None:
            continue
        unit_vectors.append((vector, unit_doc))

    if not unit_vectors:
        return None, None, False

    matched_vector = unit_vectors[0][0]
    title_or_fact: np.ndarray | None = None
    for vector, unit_doc in unit_vectors:
        unit_type = str(unit_doc.get("unit_type") or "").strip()
        if unit_type == "proposition":
            title_or_fact = vector
            break
    if title_or_fact is None:
        title_or_fact = item_vector

    channels = attribution.get("matched_channels") if isinstance(attribution.get("matched_channels"), list) else []
    has_bm25_channel = any("bm25" in str(channel).lower() for channel in channels)
    has_fact = isinstance(attribution.get("matched_facts"), list) and bool(attribution.get("matched_facts"))
    return matched_vector, title_or_fact, bool(has_bm25_channel or has_fact)


def _event_update_score(event: dict[str, Any], log: dict[str, Any] | None, updated_at: str) -> float:
    settings = get_settings()
    event_type = str(event.get("event_type") or "").strip()
    if event_type == "click":
        base_weight = settings.signal_click_weight
    elif event_type == "view_detail":
        dwell_time_ms = max(_safe_int(event.get("dwell_time_ms"), 0), 0)
        if dwell_time_ms >= settings.signal_detail_meaningful_ms:
            base_weight = settings.signal_detail_long_weight
        elif dwell_time_ms >= settings.signal_detail_short_ms:
            base_weight = settings.signal_detail_medium_weight
        else:
            base_weight = settings.signal_detail_short_weight
    elif event_type == "wishlist":
        base_weight = settings.signal_wishlist_weight
    elif event_type == "add_to_cart":
        base_weight = settings.signal_add_to_cart_weight
    elif event_type == "purchase":
        base_weight = settings.signal_purchase_weight
    else:
        base_weight = 0.0
    if base_weight <= 0:
        return 0.0
    surface = str(event.get("surface") or (log.get("surface") if isinstance(log, dict) else "") or "").strip()
    surface_weight = SURFACE_WEIGHTS.get(surface, 1.0)
    query_type = "none"
    if isinstance(log, dict):
        query = log.get("query") if isinstance(log.get("query"), dict) else {}
        query_type = str(query.get("query_type") or "none").strip()
    query_strength = QUERY_INTENT_STRENGTH.get(query_type, 1.0)
    recency = _recency_decay(
        str(event.get("timestamp") or event.get("created_at") or "") or None,
        updated_at,
    )
    return max(base_weight * surface_weight * query_strength * recency, 0.0)


def _build_event_vector(
    *,
    event: dict[str, Any],
    log: dict[str, Any] | None,
    item_vector: np.ndarray,
    item_profiles: dict[str, dict[str, Any]],
    retrieval_units_by_id: dict[str, dict[str, Any]],
) -> np.ndarray | None:
    surface = str(event.get("surface") or (log.get("surface") if isinstance(log, dict) else "") or "").strip()
    query_vector = _query_vector_from_context(event, log)
    matched_vector, title_or_fact_vector, bm25_only = _matched_unit_vectors(log, retrieval_units_by_id, item_vector)
    interest_vector = _matched_interest_vector(event, log)
    neighbor_vector = _matched_neighbor_vector(event, log)
    source_vector: np.ndarray | None = None
    source_item_id = _source_item_id(event, log)
    if source_item_id:
        source_profile = item_profiles.get(source_item_id)
        if isinstance(source_profile, dict):
            source_vector = _embedding_array(source_profile.get("item_semantic_embedding"))

    if surface == "search":
        if matched_vector is not None and query_vector is not None:
            return _normalize_blend(
                [
                    (matched_vector, 0.65),
                    (item_vector, 0.25),
                    (query_vector, 0.10),
                ]
            )
        if bm25_only:
            return _normalize_blend(
                [
                    (item_vector, 0.70),
                    (query_vector, 0.20),
                    (title_or_fact_vector, 0.10),
                ]
            )
        if query_vector is not None:
            return _normalize_blend(
                [
                    (item_vector, 0.80),
                    (query_vector, 0.20),
                ]
            )
        return item_vector

    if surface == "home":
        if interest_vector is not None:
            return _normalize_blend(
                [
                    (item_vector, 0.65),
                    (interest_vector, 0.35),
                ]
            )
        return item_vector

    if surface == "detail_similar":
        if source_vector is not None and neighbor_vector is not None:
            return _normalize_blend(
                [
                    (item_vector, 0.55),
                    (source_vector, 0.25),
                    (neighbor_vector, 0.20),
                ]
            )
        if source_vector is not None:
            return _normalize_blend(
                [
                    (item_vector, 0.75),
                    (source_vector, 0.25),
                ]
            )
        return item_vector

    if surface == "onboarding":
        return item_vector

    return item_vector


def _category_display_label(category_id: Any) -> str:
    return normalize_interest_label(str(category_id or "").replace("_", " "))


def _interest_label(intents: list[str], category_id: str) -> str:
    if intents:
        return intents[0]
    category_label = _category_display_label(category_id)
    if category_label:
        return category_label
    return "interest"


def _valid_reason_intent(reason: dict[str, Any], *, max_label_length: int, stats: ProfileBuildStats) -> str:
    intent = normalize_interest_label(reason.get("intent"))
    if not intent:
        return ""
    if not is_valid_interest_label(intent, max_length=max_label_length):
        stats.invalid_interest_labels_dropped += 1
        return ""
    return intent


def _intent_list(
    signal: dict[str, Any],
    log: dict[str, Any] | None,
    *,
    max_label_length: int,
    stats: ProfileBuildStats,
) -> list[str]:
    if not isinstance(log, dict):
        return []
    attribution = log.get("attribution")
    if not isinstance(attribution, dict):
        return []
    intents, dropped = sanitize_interest_labels(
        attribution.get("matched_intents"),
        max_length=max_label_length,
        limit=5,
    )
    stats.invalid_interest_labels_dropped += dropped
    return intents


def _signal_weight(signal: dict[str, Any]) -> float:
    settings = get_settings()
    positive = _safe_float(signal.get("positive_score"), 0.0)
    negative = _safe_float(signal.get("negative_score"), 0.0)
    implicit = _safe_float(signal.get("implicit_score"), positive - negative)
    if implicit <= 0:
        return 0.0
    contributions = signal.get("contributions") if isinstance(signal.get("contributions"), dict) else {}
    exploratory = _safe_float(contributions.get("exploratory"), 0.0)
    engaged = _safe_float(contributions.get("engaged"), 0.0)
    conversion = _safe_float(contributions.get("conversion"), 0.0)
    deliberate = engaged + conversion
    if deliberate > 0 or exploratory > 0:
        return max(deliberate + (exploratory * settings.profile_exploratory_weight), 0.0)
    return max(implicit, 0.0)


def _recent_item_ids(events: list[dict[str, Any]]) -> list[str]:
    sorted_events = sorted(
        events,
        key=lambda event: str(event.get("timestamp") or event.get("created_at") or ""),
        reverse=True,
    )
    seen: set[str] = set()
    result: list[str] = []
    for event in sorted_events:
        item_id = str(event.get("item_id") or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item_id)
        if len(result) >= RECENT_ITEM_LIMIT:
            break
    return result


def _source_signal_model_version(signals: list[dict[str, Any]]) -> str | None:
    versions = sorted(
        {
            str(signal.get("derivation", {}).get("model_version") or "").strip()
            for signal in signals
            if isinstance(signal.get("derivation"), dict) and str(signal.get("derivation", {}).get("model_version") or "").strip()
        }
    )
    if not versions:
        return None
    if len(versions) == 1:
        return versions[0]
    return "mixed"


def _latest_signal_built_at(signals: list[dict[str, Any]]) -> str | None:
    timestamps = [
        str(signal.get("derivation", {}).get("built_at") or signal.get("updated_at") or "").strip()
        for signal in signals
        if str(signal.get("derivation", {}).get("built_at") or signal.get("updated_at") or "").strip()
    ]
    if not timestamps:
        return None
    return max(timestamps)


def _purchased_item_ids(events: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[str]:
    purchased = []
    seen: set[str] = set()
    sorted_events = sorted(
        [event for event in events if str(event.get("event_type") or "") == "purchase"],
        key=lambda event: str(event.get("timestamp") or event.get("created_at") or ""),
        reverse=True,
    )
    for event in sorted_events:
        item_id = str(event.get("item_id") or "").strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            purchased.append(item_id)
    for signal in sorted(
        signals,
        key=lambda row: str(row.get("last_interaction_at") or ""),
        reverse=True,
    ):
        if _safe_int(signal.get("event_counts", {}).get("purchase"), 0) <= 0:
            continue
        item_id = str(signal.get("item_id") or "").strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            purchased.append(item_id)
    return purchased[:PURCHASED_ITEM_LIMIT]


def _weighted_average(vectors: list[tuple[np.ndarray, float]]) -> list[float]:
    if not vectors:
        return []
    matrix = np.vstack([vector for vector, _ in vectors])
    weights = np.asarray([weight for _, weight in vectors], dtype=np.float64)
    centroid = np.average(matrix, axis=0, weights=weights)
    return _normalize_vector(centroid)


def _select_interest_index(
    interests: list[dict[str, Any]],
    event_vector: np.ndarray,
    *,
    threshold: float,
    max_interests: int,
) -> tuple[int | None, bool]:
    if not interests:
        return None, True
    similarities = [_cosine_similarity(event_vector, interest["embedding_array"]) for interest in interests]
    best_index = max(range(len(similarities)), key=lambda idx: similarities[idx])
    if similarities[best_index] >= threshold:
        return best_index, False
    if len(interests) < max_interests:
        return None, True
    return best_index, False


def _merge_interest_state(
    interest: dict[str, Any],
    *,
    event_vector: np.ndarray,
    signal: dict[str, Any],
    item_doc: dict[str, Any],
    intents: list[str],
    event_weight: float,
) -> None:
    old_weight = _safe_float(interest.get("weight"), 0.0)
    new_embedding = (interest["embedding_array"] * old_weight) + (event_vector * event_weight)
    normalized = _embedding_array(_normalize_vector(new_embedding))
    if normalized is not None:
        interest["embedding_array"] = normalized
        interest["embedding"] = normalized.astype(float).tolist()
    interest["weight"] = min(old_weight + abs(event_weight), MAX_INTEREST_WEIGHT)

    category_id = str(item_doc.get("category_id") or "").strip()
    if category_id and category_id not in interest["categories"]:
        interest["categories"].append(category_id)
        interest["categories"] = interest["categories"][:5]

    for item_id in [str(signal.get("item_id") or "").strip()] + interest["top_item_ids"]:
        if item_id and item_id not in interest["top_item_ids"]:
            interest["top_item_ids"].append(item_id)
    interest["top_item_ids"] = interest["top_item_ids"][:5]

    for intent in intents:
        score = _safe_float(interest["intent_scores"].get(intent), 0.0) + event_weight
        interest["intent_scores"][intent] = score
    ranked_intents = sorted(
        interest["intent_scores"].items(), key=lambda item: (-item[1], item[0])
    )
    interest["top_intents"] = [intent for intent, _ in ranked_intents[:3]]
    interest["label"] = _interest_label(interest["top_intents"], category_id)

    event_counts = signal.get("event_counts", {})
    interest["evidence"]["click"] += _safe_int(event_counts.get("click"), 0)
    interest["evidence"]["view_detail"] += _safe_int(event_counts.get("view_detail"), 0)
    interest["evidence"]["add_to_cart"] += _safe_int(event_counts.get("add_to_cart"), 0)
    interest["evidence"]["purchase"] += _safe_int(event_counts.get("purchase"), 0)
    interest["last_updated_at"] = _max_timestamp(
        interest.get("last_updated_at"),
        str(signal.get("last_interaction_at") or signal.get("updated_at") or "") or None,
    ) or utc_now_iso()


def _interest_document(index: int, interest: dict[str, Any]) -> dict[str, Any]:
    doc = InterestVector(
        interest_id=f"int_{index:03d}",
        label=str(interest.get("label") or "interest"),
        embedding=interest.get("embedding", []),
        weight=_safe_float(interest.get("weight"), 0.0),
        categories=list(interest.get("categories", [])),
        top_intents=list(interest.get("top_intents", [])),
        evidence=interest.get("evidence", {}),
        top_item_ids=list(interest.get("top_item_ids", [])),
        last_updated_at=str(interest.get("last_updated_at") or utc_now_iso()),
    )
    return to_mongo_dict(doc)


def _profile_quality(
    *,
    signals: list[dict[str, Any]],
    positive_signals: list[dict[str, Any]],
    distinct_categories: set[str],
) -> dict[str, Any]:
    num_events = 0
    num_purchases = 0
    for signal in signals:
        event_counts = signal.get("event_counts", {})
        num_events += sum(_safe_int(value, 0) for value in event_counts.values())
        num_purchases += _safe_int(event_counts.get("purchase"), 0)
    confidence = min(
        1.0,
        (0.02 * num_events)
        + (0.06 * len(positive_signals))
        + (0.08 * len(distinct_categories))
        + (0.12 * min(num_purchases, 3)),
    )
    return {
        "num_events": num_events,
        "num_positive_items": len(positive_signals),
        "num_purchases": num_purchases,
        "num_categories": len(distinct_categories),
        "confidence": round(confidence, 6),
    }


def _profile_status(profile_quality: dict[str, Any]) -> str:
    num_events = _safe_int(profile_quality.get("num_events"), 0)
    if num_events <= 0:
        return "new"
    if num_events < 5 or _safe_int(profile_quality.get("num_positive_items"), 0) <= 0:
        return "warming"
    return "warm"


def _affinity_map(scores: dict[str, float]) -> dict[str, float]:
    positive = {key: value for key, value in scores.items() if value > 0}
    if not positive:
        return {}
    max_score = max(positive.values())
    if max_score <= 0:
        return {}
    return {key: round(value / max_score, 6) for key, value in sorted(positive.items())}


def _median_price(prices: list[int]) -> int | None:
    if not prices:
        return None
    sorted_prices = sorted(prices)
    middle = len(sorted_prices) // 2
    if len(sorted_prices) % 2 == 1:
        return int(sorted_prices[middle])
    return int((sorted_prices[middle - 1] + sorted_prices[middle]) / 2)


def _threshold_diagnostics(profile_docs: list[dict[str, Any]]) -> dict[str, float | int]:
    if not profile_docs:
        return {
            "mean_interests": 0.0,
            "max_interests": 0,
            "users_with_1_interest": 0,
            "users_with_8plus_interests": 0,
        }
    counts = [len(profile.get("interest_vectors", [])) for profile in profile_docs]
    return {
        "mean_interests": round(sum(counts) / len(counts), 6),
        "max_interests": max(counts),
        "users_with_1_interest": sum(1 for count in counts if count == 1),
        "users_with_8plus_interests": sum(1 for count in counts if count >= 8),
    }


def _load_collection_docs(
    collection: Any,
    filter_doc: dict[str, Any],
    projection: dict[str, int],
) -> list[dict[str, Any]]:
    return [dict(doc) for doc in collection.find(filter_doc, projection)]


def _load_user_item_signals(user_item_signals_collection: Any) -> list[dict[str, Any]]:
    projection = {
        "_id": 1,
        "user_id_hash": 1,
        "item_id": 1,
        "implicit_score": 1,
        "positive_score": 1,
        "negative_score": 1,
        "preference": 1,
        "seed_eligible": 1,
        "intent_tier": 1,
        "contributions": 1,
        "event_counts": 1,
        "reason_scores": 1,
        "last_interaction_at": 1,
        "first_interaction_at": 1,
        "derivation": 1,
        "updated_at": 1,
    }
    return _load_collection_docs(user_item_signals_collection, {}, projection)


def _load_clickstream_events(clickstream_events_collection: Any, user_ids: set[str]) -> list[dict[str, Any]]:
    projection = {
        "event_id": 1,
        "request_id": 1,
        "user_id_hash": 1,
        "item_id": 1,
        "event_type": 1,
        "surface": 1,
        "dwell_time_ms": 1,
        "timestamp": 1,
        "created_at": 1,
        "metadata": 1,
    }
    if not user_ids:
        return []
    return _load_collection_docs(
        clickstream_events_collection,
        {"user_id_hash": {"$in": sorted(user_ids)}},
        projection,
    )


def _load_recommendation_logs(recommendation_logs_collection: Any, keys: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    if not keys:
        return {}
    projection = {
        "request_id": 1,
        "item_id": 1,
        "query": 1,
        "scores": 1,
        "attribution": 1,
        "shown_at": 1,
        "surface": 1,
    }
    docs = _load_collection_docs(
        recommendation_logs_collection,
        {"$or": [{"request_id": request_id, "item_id": item_id} for request_id, item_id in sorted(keys)]},
        projection,
    )
    return {
        (str(doc.get("request_id") or "").strip(), str(doc.get("item_id") or "").strip()): doc
        for doc in docs
        if str(doc.get("request_id") or "").strip() and str(doc.get("item_id") or "").strip()
    }


def _load_item_hype_profiles(item_hype_profiles_collection: Any, item_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not item_ids:
        return {}
    projection = {
        "item_id": 1,
        "item_semantic_embedding": 1,
        "top_aspects": 1,
        "num_hype_units": 1,
        "category_id": 1,
        "price_bucket": 1,
    }
    docs = _load_collection_docs(item_hype_profiles_collection, {"item_id": {"$in": sorted(item_ids)}}, projection)
    return {str(doc.get("item_id") or doc.get("_id") or "").strip(): doc for doc in docs}


def _load_items(items_collection: Any, item_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not item_ids:
        return {}
    projection = {
        "_id": 1,
        "brand": 1,
        "category_id": 1,
        "price_bucket": 1,
        "price_vnd": 1,
    }
    docs = _load_collection_docs(items_collection, {"_id": {"$in": sorted(item_ids)}}, projection)
    return {str(doc.get("_id") or "").strip(): doc for doc in docs}


def _load_retrieval_units(retrieval_units_collection: Any | None, unit_ids: set[str]) -> dict[str, dict[str, Any]]:
    if retrieval_units_collection is None or not unit_ids:
        return {}
    projection = {
        "_id": 1,
        "item_id": 1,
        "unit_type": 1,
        "embedding": 1,
    }
    docs = _load_collection_docs(retrieval_units_collection, {"_id": {"$in": sorted(unit_ids)}}, projection)
    return {str(doc.get("_id") or "").strip(): doc for doc in docs if str(doc.get("_id") or "").strip()}


def _build_profile_doc(
    *,
    user_id_hash: str,
    signals: list[dict[str, Any]],
    events: list[dict[str, Any]],
    logs_by_key: dict[tuple[str, str], dict[str, Any]],
    item_profiles: dict[str, dict[str, Any]],
    items_by_id: dict[str, dict[str, Any]],
    retrieval_units_by_id: dict[str, dict[str, Any]],
    threshold: float,
    max_interests: int,
    stats: ProfileBuildStats,
    updated_at: str,
    profile_model_version: str,
    source_signal_model_version: str,
    source_signal_built_at: str | None,
    partial_build: bool,
    profile_label_max_length: int,
) -> dict[str, Any] | None:
    positive_vectors_long: list[tuple[np.ndarray, float]] = []
    positive_vectors_short: list[tuple[np.ndarray, float]] = []
    category_scores: dict[str, float] = defaultdict(float)
    brand_scores: dict[str, float] = defaultdict(float)
    price_scores: dict[str, float] = defaultdict(float)
    intent_scores: dict[str, float] = defaultdict(float)
    negative_brand_counts: dict[str, int] = defaultdict(int)
    negative_category_counts: dict[str, int] = defaultdict(int)
    negative_intent_counts: dict[str, int] = defaultdict(int)
    interests: list[dict[str, Any]] = []
    distinct_categories: set[str] = set()
    clicked_prices: list[int] = []
    cart_prices: list[int] = []
    purchased_prices: list[int] = []
    negative_item_ids: list[str] = []

    events_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        item_id = str(event.get("item_id") or "").strip()
        if not item_id:
            continue
        events_by_item[item_id].append(event)
    for item_id in events_by_item:
        events_by_item[item_id].sort(
            key=lambda row: str(row.get("timestamp") or row.get("created_at") or ""),
            reverse=True,
        )

    positive_signals = sorted(
        [signal for signal in signals if _signal_weight(signal) >= POSITIVE_SIGNAL_THRESHOLD],
        key=lambda row: str(row.get("last_interaction_at") or row.get("updated_at") or ""),
    )

    for recency_index, signal in enumerate(positive_signals[::-1], start=1):
        item_id = str(signal.get("item_id") or "").strip()
        item_profile = item_profiles.get(item_id)
        vector = _embedding_array(item_profile.get("item_semantic_embedding") if item_profile else None)
        if vector is None:
            if item_profile is None:
                stats.item_profiles_missing += 1
            else:
                stats.invalid_signal_embeddings += 1
            continue

        event_weight = _signal_weight(signal)
        event_vectors: list[tuple[np.ndarray, float]] = []
        intents: list[str] = []
        for candidate_event in events_by_item.get(item_id, []):
            event_type = str(candidate_event.get("event_type") or "").strip()
            if event_type not in POSITIVE_EVENT_TYPES:
                continue
            request_id = str(candidate_event.get("request_id") or "").strip()
            log = logs_by_key.get((request_id, item_id)) if request_id else None
            candidate_vector = _build_event_vector(
                event=candidate_event,
                log=log,
                item_vector=vector,
                item_profiles=item_profiles,
                retrieval_units_by_id=retrieval_units_by_id,
            )
            if candidate_vector is None:
                candidate_vector = vector
            candidate_weight = _event_update_score(candidate_event, log, updated_at)
            if candidate_weight <= 0:
                continue
            event_vectors.append((candidate_vector, candidate_weight))
            if not intents:
                intents = _intent_list(
                    signal,
                    log,
                    max_label_length=profile_label_max_length,
                    stats=stats,
                )

        if not event_vectors:
            fallback_event = {
                "item_id": item_id,
                "surface": "search",
                "event_type": "click",
                "timestamp": str(signal.get("last_interaction_at") or signal.get("updated_at") or updated_at),
                "metadata": {},
            }
            event_vectors = [(vector, max(event_weight, _event_update_score(fallback_event, None, updated_at), 0.0))]

        blended_event_vector = _normalize_blend(event_vectors)
        event_vector = blended_event_vector if blended_event_vector is not None else vector
        event_update_score = max(event_weight, sum(weight for _vector, weight in event_vectors))
        positive_vectors_long.append((event_vector, event_update_score))
        positive_vectors_short.append((event_vector, event_update_score / recency_index))

        item_doc = items_by_id.get(item_id, {})
        category_id = str(item_doc.get("category_id") or item_profile.get("category_id") or "").strip()
        brand = str(item_doc.get("brand") or "").strip()
        price_bucket = str(item_doc.get("price_bucket") or item_profile.get("price_bucket") or "").strip()
        if category_id:
            category_scores[category_id] += event_weight
            distinct_categories.add(category_id)
        if brand:
            brand_scores[brand] += event_weight
        if price_bucket:
            price_scores[price_bucket] += event_weight

        event_counts = signal.get("event_counts", {})
        price_vnd = item_doc.get("price_vnd")
        price_int = _safe_int(price_vnd, default=-1)
        if price_int >= 0:
            if _safe_int(event_counts.get("click"), 0) > 0:
                clicked_prices.append(price_int)
            if _safe_int(event_counts.get("add_to_cart"), 0) > 0:
                cart_prices.append(price_int)
            if _safe_int(event_counts.get("purchase"), 0) > 0:
                purchased_prices.append(price_int)

        for reason in signal.get("reason_scores", []):
            if not isinstance(reason, dict):
                continue
            intent = _valid_reason_intent(
                reason,
                max_label_length=profile_label_max_length,
                stats=stats,
            )
            if not intent:
                continue
            intent_scores[intent] += _safe_float(reason.get("score"), event_weight)

        index, create_new = _select_interest_index(
            interests,
            event_vector,
            threshold=threshold,
            max_interests=max_interests,
        )
        if create_new:
            interests.append(
                {
                    "embedding_array": event_vector,
                    "embedding": event_vector.astype(float).tolist(),
                    "weight": min(event_update_score, MAX_INTEREST_WEIGHT),
                    "categories": [category_id] if category_id else [],
                    "top_intents": intents[:3],
                    "intent_scores": {intent: event_update_score for intent in intents[:3]},
                    "evidence": {
                        "click": _safe_int(event_counts.get("click"), 0),
                        "view_detail": _safe_int(event_counts.get("view_detail"), 0),
                        "add_to_cart": _safe_int(event_counts.get("add_to_cart"), 0),
                        "purchase": _safe_int(event_counts.get("purchase"), 0),
                    },
                    "top_item_ids": [item_id] if item_id else [],
                    "label": _interest_label(intents[:3], category_id),
                    "last_updated_at": str(signal.get("last_interaction_at") or signal.get("updated_at") or updated_at),
                }
            )
        else:
            _merge_interest_state(
                interests[index],
                event_vector=event_vector,
                signal=signal,
                item_doc=item_doc,
                intents=intents,
                event_weight=event_update_score,
            )

    for signal in signals:
        if _safe_float(signal.get("negative_score"), 0.0) <= 0:
            continue
        item_id = str(signal.get("item_id") or "").strip()
        if item_id and item_id not in negative_item_ids:
            negative_item_ids.append(item_id)
        item_doc = items_by_id.get(item_id, {})
        brand = str(item_doc.get("brand") or "").strip()
        category_id = str(item_doc.get("category_id") or "").strip()
        if brand:
            negative_brand_counts[brand] += 1
        if category_id:
            negative_category_counts[category_id] += 1
        for reason in signal.get("reason_scores", []):
            if not isinstance(reason, dict):
                continue
            intent = _valid_reason_intent(
                reason,
                max_label_length=profile_label_max_length,
                stats=stats,
            )
            if intent:
                negative_intent_counts[intent] += 1

    long_term_embedding = _weighted_average(positive_vectors_long)
    short_term_embedding = _weighted_average(positive_vectors_short[:10])
    if not positive_signals and not _recent_item_ids(events):
        stats.users_skipped += 1
        return None
    if (long_term_embedding and len(long_term_embedding) != EMBEDDING_DIM) or (
        short_term_embedding and len(short_term_embedding) != EMBEDDING_DIM
    ):
        stats.non_finite_profiles += 1
        stats.errors.append(f"{user_id_hash}: invalid embedding length")
        return None

    profile_quality = _profile_quality(
        signals=signals,
        positive_signals=positive_signals,
        distinct_categories=distinct_categories,
    )
    interest_docs = [_interest_document(index + 1, interest) for index, interest in enumerate(interests)]
    profile = UserProfileDocument(
        _id=user_id_hash,
        user_id_hash=user_id_hash,
        profile_status=_profile_status(profile_quality),
        profile_quality=profile_quality,
        category_affinity=_affinity_map(category_scores),
        brand_affinity=_affinity_map(brand_scores),
        price_affinity={
            "preferred_buckets": _affinity_map(price_scores),
            "median_clicked_price": _median_price(clicked_prices),
            "median_cart_price": _median_price(cart_prices),
            "median_purchased_price": _median_price(purchased_prices),
        },
        intent_affinity=[
            {
                "intent": intent,
                "score": round(score, 6),
                "source": "behavior_signal",
                "last_seen_at": updated_at,
            }
            for intent, score in sorted(intent_scores.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
        short_term_embedding=short_term_embedding,
        long_term_embedding=long_term_embedding,
        interest_vectors=interest_docs,
        negative_preferences={
            "item_ids": negative_item_ids[:20],
            "brands": sorted(
                [brand for brand, count in negative_brand_counts.items() if count >= NEGATIVE_ENTITY_THRESHOLD]
            )[:10],
            "categories": sorted(
                [category for category, count in negative_category_counts.items() if count >= NEGATIVE_ENTITY_THRESHOLD]
            )[:10],
            "intents": sorted(
                [intent for intent, count in negative_intent_counts.items() if count >= NEGATIVE_ENTITY_THRESHOLD]
            )[:10],
        },
        recent_item_ids=_recent_item_ids(events),
        purchased_item_ids=_purchased_item_ids(events, signals),
        derivation={
            "model_version": profile_model_version,
            "source_collection": "user_item_signals",
            "source_signal_model_version": source_signal_model_version,
            "source_signal_count": len(signals),
            "source_signal_built_at": source_signal_built_at,
            "partial_build": partial_build,
            "built_at": updated_at,
        },
        updated_at=updated_at,
    )
    return to_mongo_dict(profile)


def _profile_upsert_operation(doc: dict[str, Any]) -> UpdateOne:
    payload = dict(doc)
    doc_id = payload.pop("_id")
    return UpdateOne(
        {"user_id_hash": payload["user_id_hash"]},
        {"$set": payload, "$setOnInsert": {"_id": doc_id}},
        upsert=True,
    )


def _bulk_write_profiles(collection: Any, docs: list[dict[str, Any]], batch_size: int) -> dict[str, int]:
    summary = {"batches": 0, "written": 0}
    for index in range(0, len(docs), batch_size):
        batch = docs[index : index + batch_size]
        if not batch:
            continue
        result = collection.bulk_write([_profile_upsert_operation(doc) for doc in batch], ordered=False)
        summary["batches"] += 1
        summary["written"] += int(getattr(result, "upserted_count", 0)) + int(
            getattr(result, "modified_count", 0)
        )
    return summary


def build_user_profiles(
    *,
    user_item_signals_collection: Any,
    clickstream_events_collection: Any,
    recommendation_logs_collection: Any,
    item_hype_profiles_collection: Any,
    items_collection: Any,
    retrieval_units_collection: Any | None = None,
    user_profiles_collection: Any | None = None,
    write: bool = False,
    limit_users: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    threshold: float = INTEREST_MERGE_THRESHOLD,
    max_interests: int = MAX_INTERESTS_PER_USER,
    updated_at: str | None = None,
) -> dict[str, Any]:
    if limit_users is not None and limit_users <= 0:
        raise ValueError("limit_users must be positive when provided")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if threshold <= 0 or threshold > 1.0:
        raise ValueError("threshold must be in (0, 1]")
    if max_interests <= 0:
        raise ValueError("max_interests must be positive")
    if write and user_profiles_collection is None:
        raise ValueError("user_profiles_collection is required when write=True")
    if write and limit_users is not None:
        raise ValueError("unsafe_partial_profile_write: limit_users may only be used in dry-run mode")

    settings = get_settings()
    updated_at = updated_at or utc_now_iso()
    stats = ProfileBuildStats()
    signal_docs = _load_user_item_signals(user_item_signals_collection)
    users: dict[str, list[dict[str, Any]]] = defaultdict(list)
    item_ids: set[str] = set()
    for signal in signal_docs:
        user_id_hash = str(signal.get("user_id_hash") or "").strip()
        item_id = str(signal.get("item_id") or "").strip()
        if not user_id_hash or not item_id:
            continue
        users[user_id_hash].append(signal)
        item_ids.add(item_id)

    selected_user_ids = sorted(users)
    if limit_users is not None:
        selected_user_ids = selected_user_ids[:limit_users]
    selected_users = {user_id: users[user_id] for user_id in selected_user_ids}
    stats.users_seen = len(selected_user_ids)

    events = _load_clickstream_events(clickstream_events_collection, set(selected_user_ids))
    events_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    log_keys: set[tuple[str, str]] = set()
    for event in events:
        user_id_hash = str(event.get("user_id_hash") or "").strip()
        item_id = str(event.get("item_id") or "").strip()
        if not user_id_hash or user_id_hash not in selected_users or not item_id:
            continue
        events_by_user[user_id_hash].append(event)
        request_id = str(event.get("request_id") or "").strip()
        if request_id:
            log_keys.add((request_id, item_id))
        item_ids.add(item_id)

    logs_by_key = _load_recommendation_logs(recommendation_logs_collection, log_keys)

    matched_unit_ids: set[str] = set()
    for log in logs_by_key.values():
        attribution = log.get("attribution") if isinstance(log.get("attribution"), dict) else {}
        unit_ids = attribution.get("matched_unit_ids") if isinstance(attribution.get("matched_unit_ids"), list) else []
        matched_unit_ids.update(str(unit_id).strip() for unit_id in unit_ids if str(unit_id).strip())

    item_profiles = _load_item_hype_profiles(item_hype_profiles_collection, item_ids)
    items_by_id = _load_items(items_collection, item_ids)
    retrieval_units_by_id = _load_retrieval_units(retrieval_units_collection, matched_unit_ids)
    profile_docs: list[dict[str, Any]] = []
    sample_profiles: list[dict[str, Any]] = []
    for user_id_hash in selected_user_ids:
        user_signals = selected_users[user_id_hash]
        profile_doc = _build_profile_doc(
            user_id_hash=user_id_hash,
            signals=user_signals,
            events=events_by_user.get(user_id_hash, []),
            logs_by_key=logs_by_key,
            item_profiles=item_profiles,
            items_by_id=items_by_id,
            retrieval_units_by_id=retrieval_units_by_id,
            threshold=threshold,
            max_interests=max_interests,
            stats=stats,
            updated_at=updated_at,
            profile_model_version=settings.profile_model_version,
            source_signal_model_version=_source_signal_model_version(user_signals) or settings.signal_model_version,
            source_signal_built_at=_latest_signal_built_at(user_signals),
            partial_build=limit_users is not None,
            profile_label_max_length=settings.profile_label_max_length,
        )
        if profile_doc is None:
            continue
        profile_docs.append(profile_doc)
        stats.profiles_built += 1
        if len(sample_profiles) < 3:
            sample = dict(profile_doc)
            if sample.get("short_term_embedding"):
                sample["short_term_embedding_preview"] = sample.pop("short_term_embedding")[:5]
            if sample.get("long_term_embedding"):
                sample["long_term_embedding_preview"] = sample.pop("long_term_embedding")[:5]
            sample_profiles.append(sample)

    stats.calibration = _threshold_diagnostics(profile_docs)

    if write and profile_docs:
        summary = _bulk_write_profiles(user_profiles_collection, profile_docs, batch_size)
        stats.bulk_write_batches = summary["batches"]
        stats.profiles_written = summary["written"]

    return {
        "ok": not stats.errors,
        "write": write,
        "limit_users": limit_users,
        "threshold": threshold,
        "max_interests": max_interests,
        "stats": stats.as_dict(),
        "sample_profiles": sample_profiles,
    }
