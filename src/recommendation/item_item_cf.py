from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from typing import Any

from pymongo import UpdateOne

from src.config import get_settings
from src.recommendation.schemas import ItemItemCFEdgeDocument
from src.schemas import to_mongo_dict
from src.utils import utc_now_iso


DEFAULT_CF_MIN_SUPPORT = 2
DEFAULT_MAX_ITEMS_PER_USER = 30
DEFAULT_TOP_NEIGHBORS_PER_ITEM = 50
DEFAULT_BATCH_SIZE = 500
CF_HALF_LIFE_DAYS = 45.0


@dataclass
class CFBuildStats:
    users_seen: int = 0
    users_with_positive_items: int = 0
    users_skipped: int = 0
    positive_signal_docs: int = 0
    missing_items_skipped: int = 0
    pair_candidates: int = 0
    undirected_pairs_retained: int = 0
    undirected_pairs_selected: int = 0
    directional_edges_built: int = 0
    directional_edges_written: int = 0
    stale_edges_deleted: int = 0
    bulk_write_batches: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "users_seen": self.users_seen,
            "users_with_positive_items": self.users_with_positive_items,
            "users_skipped": self.users_skipped,
            "positive_signal_docs": self.positive_signal_docs,
            "missing_items_skipped": self.missing_items_skipped,
            "pair_candidates": self.pair_candidates,
            "undirected_pairs_retained": self.undirected_pairs_retained,
            "undirected_pairs_selected": self.undirected_pairs_selected,
            "directional_edges_built": self.directional_edges_built,
            "directional_edges_written": self.directional_edges_written,
            "stale_edges_deleted": self.stale_edges_deleted,
            "bulk_write_batches": self.bulk_write_batches,
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


def _recency_decay(timestamp: str | None, updated_at: str, half_life_days: float = CF_HALF_LIFE_DAYS) -> float:
    event_time = _to_datetime(timestamp)
    now_time = _to_datetime(updated_at)
    if event_time is None or now_time is None:
        return 1.0
    age_days = max(0.0, (now_time - event_time).total_seconds() / 86_400)
    return float(0.5 ** (age_days / half_life_days))


def _positive_signal_value(signal: dict[str, Any]) -> float:
    implicit_score = _safe_float(signal.get("implicit_score"), 0.0)
    positive_score = _safe_float(signal.get("positive_score"), 0.0)
    return max(implicit_score, positive_score, 0.0)


def _is_positive_signal(signal: dict[str, Any]) -> bool:
    return _safe_float(signal.get("implicit_score"), 0.0) > 1.0 or bool(signal.get("preference"))


def _event_count(signal: dict[str, Any], event_type: str) -> int:
    counts = signal.get("event_counts")
    if not isinstance(counts, dict):
        return 0
    try:
        return int(counts.get(event_type) or 0)
    except (TypeError, ValueError):
        return 0


def _load_positive_signals(user_item_signals_collection: Any) -> list[dict[str, Any]]:
    projection = {
        "user_id_hash": 1,
        "item_id": 1,
        "implicit_score": 1,
        "positive_score": 1,
        "preference": 1,
        "event_counts": 1,
        "last_interaction_at": 1,
        "derivation": 1,
        "updated_at": 1,
    }
    docs = [dict(doc) for doc in user_item_signals_collection.find({}, projection)]
    return [doc for doc in docs if _is_positive_signal(doc)]


def _load_existing_item_ids(items_collection: Any, item_ids: set[str]) -> set[str]:
    if not item_ids:
        return set()
    projection = {"_id": 1}
    docs = items_collection.find({"_id": {"$in": sorted(item_ids)}}, projection)
    return {str(doc.get("_id") or "").strip() for doc in docs if str(doc.get("_id") or "").strip()}


def _sort_positive_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        signals,
        key=lambda signal: (
            -_positive_signal_value(signal),
            -_safe_float(signal.get("implicit_score"), 0.0),
            str(signal.get("last_interaction_at") or ""),
            str(signal.get("item_id") or ""),
        ),
        reverse=False,
    )


def _pair_key(left_item_id: str, right_item_id: str) -> tuple[str, str]:
    return (left_item_id, right_item_id) if left_item_id < right_item_id else (right_item_id, left_item_id)


def _build_edge_doc(
    *,
    item_id: str,
    neighbor_item_id: str,
    stats: dict[str, Any],
    cf_score: float,
    confidence: float,
    updated_at: str,
    derivation: dict[str, Any],
) -> dict[str, Any]:
    doc = ItemItemCFEdgeDocument(
        _id=f"{item_id}::{neighbor_item_id}",
        item_id=item_id,
        neighbor_item_id=neighbor_item_id,
        cf_score=round(cf_score, 6),
        co_view_count=int(stats.get("co_view_count", 0)),
        co_click_count=int(stats.get("co_click_count", 0)),
        co_cart_count=int(stats.get("co_cart_count", 0)),
        co_purchase_count=int(stats.get("co_purchase_count", 0)),
        support=int(stats.get("support", 0)),
        confidence=round(confidence, 6),
        top_common_user_hashes_sample=list(stats.get("user_hashes", []))[:5],
        explanation="Users who interacted with this item also interacted with this recommendation.",
        derivation=derivation,
        updated_at=updated_at,
    )
    return to_mongo_dict(doc)


def _source_signal_model_version(signal_docs: list[dict[str, Any]]) -> str | None:
    versions = sorted(
        {
            str(signal.get("derivation", {}).get("model_version") or "").strip()
            for signal in signal_docs
            if isinstance(signal.get("derivation"), dict) and str(signal.get("derivation", {}).get("model_version") or "").strip()
        }
    )
    if not versions:
        return None
    if len(versions) == 1:
        return versions[0]
    return "mixed"


def _latest_signal_built_at(signal_docs: list[dict[str, Any]]) -> str | None:
    timestamps = [
        str(signal.get("derivation", {}).get("built_at") or signal.get("updated_at") or "").strip()
        for signal in signal_docs
        if str(signal.get("derivation", {}).get("built_at") or signal.get("updated_at") or "").strip()
    ]
    if not timestamps:
        return None
    return max(timestamps)


def _edge_upsert_operation(doc: dict[str, Any]) -> UpdateOne:
    payload = dict(doc)
    doc_id = payload.pop("_id")
    return UpdateOne(
        {"item_id": payload["item_id"], "neighbor_item_id": payload["neighbor_item_id"]},
        {"$set": payload, "$setOnInsert": {"_id": doc_id}},
        upsert=True,
    )


def _bulk_write_edges(collection: Any, docs: list[dict[str, Any]], batch_size: int) -> dict[str, int]:
    summary = {"batches": 0, "written": 0}
    for index in range(0, len(docs), batch_size):
        batch = docs[index : index + batch_size]
        if not batch:
            continue
        result = collection.bulk_write([_edge_upsert_operation(doc) for doc in batch], ordered=False)
        summary["batches"] += 1
        summary["written"] += int(getattr(result, "upserted_count", 0)) + int(
            getattr(result, "modified_count", 0)
        ) + int(getattr(result, "matched_count", 0))
    return summary


def build_item_item_cf_edges(
    *,
    user_item_signals_collection: Any,
    items_collection: Any,
    item_item_cf_edges_collection: Any | None = None,
    write: bool = False,
    limit_users: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    min_support: int = DEFAULT_CF_MIN_SUPPORT,
    max_items_per_user: int = DEFAULT_MAX_ITEMS_PER_USER,
    top_neighbors_per_item: int = DEFAULT_TOP_NEIGHBORS_PER_ITEM,
    replace_existing: bool = False,
    updated_at: str | None = None,
) -> dict[str, Any]:
    if limit_users is not None and limit_users <= 0:
        raise ValueError("limit_users must be positive when provided")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if min_support <= 0:
        raise ValueError("min_support must be positive")
    if max_items_per_user <= 1:
        raise ValueError("max_items_per_user must be greater than 1")
    if top_neighbors_per_item <= 0:
        raise ValueError("top_neighbors_per_item must be positive")
    if replace_existing and limit_users is not None:
        raise ValueError("replace_existing requires a full rebuild without limit_users")
    if write and item_item_cf_edges_collection is None:
        raise ValueError("item_item_cf_edges_collection is required when write=True")
    if write and limit_users is not None:
        raise ValueError("unsafe_partial_cf_write: limit_users may only be used in dry-run mode")

    settings = get_settings()
    updated_at = updated_at or utc_now_iso()
    stats = CFBuildStats()
    signal_docs = _load_positive_signals(user_item_signals_collection)
    stats.positive_signal_docs = len(signal_docs)

    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidate_item_ids: set[str] = set()
    for signal in signal_docs:
        user_id_hash = str(signal.get("user_id_hash") or "").strip()
        item_id = str(signal.get("item_id") or "").strip()
        if not user_id_hash or not item_id:
            continue
        by_user[user_id_hash].append(signal)
        candidate_item_ids.add(item_id)

    selected_user_ids = sorted(by_user)
    if limit_users is not None:
        selected_user_ids = selected_user_ids[:limit_users]
    stats.users_seen = len(selected_user_ids)

    existing_item_ids = _load_existing_item_ids(items_collection, candidate_item_ids)

    positive_items_by_user: dict[str, list[dict[str, Any]]] = {}
    popularity: dict[str, int] = defaultdict(int)
    for user_id_hash in selected_user_ids:
        filtered: list[dict[str, Any]] = []
        for signal in _sort_positive_signals(by_user[user_id_hash]):
            item_id = str(signal.get("item_id") or "").strip()
            if item_id not in existing_item_ids:
                stats.missing_items_skipped += 1
                continue
            filtered.append(signal)
            if len(filtered) >= max_items_per_user:
                break

        if not filtered:
            stats.users_skipped += 1
            continue
        stats.users_with_positive_items += 1
        positive_items_by_user[user_id_hash] = filtered
        for signal in filtered:
            popularity[str(signal.get("item_id") or "").strip()] += 1

    pair_stats: dict[tuple[str, str], dict[str, Any]] = {}
    for user_id_hash, signals in positive_items_by_user.items():
        if len(signals) < 2:
            stats.users_skipped += 1
            continue
        for left_signal, right_signal in combinations(signals, 2):
            left_item_id = str(left_signal.get("item_id") or "").strip()
            right_item_id = str(right_signal.get("item_id") or "").strip()
            if not left_item_id or not right_item_id or left_item_id == right_item_id:
                continue
            stats.pair_candidates += 1
            pair_key = _pair_key(left_item_id, right_item_id)
            state = pair_stats.setdefault(
                pair_key,
                {
                    "item_ids": pair_key,
                    "pair_score": 0.0,
                    "support": 0,
                    "co_view_count": 0,
                    "co_click_count": 0,
                    "co_cart_count": 0,
                    "co_purchase_count": 0,
                    "user_hashes": [],
                },
            )
            pair_decay = min(
                _recency_decay(str(left_signal.get("last_interaction_at") or "") or None, updated_at),
                _recency_decay(str(right_signal.get("last_interaction_at") or "") or None, updated_at),
            )
            pair_strength = min(_positive_signal_value(left_signal), _positive_signal_value(right_signal)) * pair_decay
            state["pair_score"] += pair_strength
            state["support"] += 1
            if _event_count(left_signal, "view_detail") > 0 and _event_count(right_signal, "view_detail") > 0:
                state["co_view_count"] += 1
            if _event_count(left_signal, "click") > 0 and _event_count(right_signal, "click") > 0:
                state["co_click_count"] += 1
            if _event_count(left_signal, "add_to_cart") > 0 and _event_count(right_signal, "add_to_cart") > 0:
                state["co_cart_count"] += 1
            if _event_count(left_signal, "purchase") > 0 and _event_count(right_signal, "purchase") > 0:
                state["co_purchase_count"] += 1
            if len(state["user_hashes"]) < 5 and user_id_hash not in state["user_hashes"]:
                state["user_hashes"].append(user_id_hash)

    ranked_pairs: list[tuple[float, int, str, str, dict[str, Any], float]] = []
    for pair_key, pair_state in pair_stats.items():
        support = int(pair_state["support"])
        if support < min_support:
            continue
        left_item_id, right_item_id = pair_key
        left_popularity = popularity.get(left_item_id, 0)
        right_popularity = popularity.get(right_item_id, 0)
        denominator = math.sqrt(float(left_popularity * right_popularity))
        if denominator <= 0 or not math.isfinite(denominator):
            continue
        cf_score = float(pair_state["pair_score"]) / denominator
        if not math.isfinite(cf_score) or cf_score <= 0:
            continue
        stats.undirected_pairs_retained += 1
        confidence = min(1.0, support / max(1.0, denominator))
        ranked_pairs.append((cf_score, support, left_item_id, right_item_id, pair_state, confidence))

    # Select whole pairs so per-item top-K pruning can never leave one-way CF evidence.
    edge_docs: list[dict[str, Any]] = []
    neighbor_counts: dict[str, int] = defaultdict(int)
    derivation = {
        "model_version": settings.cf_model_version,
        "source_collection": "user_item_signals",
        "source_signal_model_version": _source_signal_model_version(signal_docs) or settings.signal_model_version,
        "source_signal_count": len(signal_docs),
        "source_signal_built_at": _latest_signal_built_at(signal_docs),
        "partial_build": limit_users is not None,
        "built_at": updated_at,
    }
    for cf_score, support, left_item_id, right_item_id, pair_state, confidence in sorted(
        ranked_pairs,
        key=lambda row: (-row[0], -row[1], row[2], row[3]),
    ):
        if neighbor_counts[left_item_id] >= top_neighbors_per_item:
            continue
        if neighbor_counts[right_item_id] >= top_neighbors_per_item:
            continue
        edge_docs.append(
            _build_edge_doc(
                item_id=left_item_id,
                neighbor_item_id=right_item_id,
                stats=pair_state,
                cf_score=cf_score,
                confidence=confidence,
                updated_at=updated_at,
                derivation=derivation,
            )
        )
        edge_docs.append(
            _build_edge_doc(
                item_id=right_item_id,
                neighbor_item_id=left_item_id,
                stats=pair_state,
                cf_score=cf_score,
                confidence=confidence,
                updated_at=updated_at,
                derivation=derivation,
            )
        )
        neighbor_counts[left_item_id] += 1
        neighbor_counts[right_item_id] += 1
        stats.undirected_pairs_selected += 1

    stats.directional_edges_built = len(edge_docs)
    sample_edges = edge_docs[: min(5, len(edge_docs))]

    if write:
        if edge_docs:
            summary = _bulk_write_edges(item_item_cf_edges_collection, edge_docs, batch_size)
            stats.bulk_write_batches = summary["batches"]
            stats.directional_edges_written = summary["written"]
        if replace_existing:
            retained_ids = [doc["_id"] for doc in edge_docs]
            stale_filter = {"_id": {"$nin": retained_ids}} if retained_ids else {}
            result = item_item_cf_edges_collection.delete_many(stale_filter)
            stats.stale_edges_deleted = int(getattr(result, "deleted_count", 0))

    return {
        "ok": not stats.errors,
        "write": write,
        "limit_users": limit_users,
        "min_support": min_support,
        "max_items_per_user": max_items_per_user,
        "top_neighbors_per_item": top_neighbors_per_item,
        "replace_existing": replace_existing,
        "stats": stats.as_dict(),
        "sample_edges": sample_edges,
    }
