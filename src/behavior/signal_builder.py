from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pymongo import UpdateOne

from src.behavior.schemas import UserItemSignalDocument
from src.recommendation.schemas import ItemStatsDocument
from src.schemas import to_mongo_dict
from src.utils import utc_now_iso


EVENT_TYPES = (
    "impression",
    "click",
    "view_detail",
    "wishlist",
    "add_to_cart",
    "purchase",
    "hide",
    "dislike",
)
POSITIVE_EVENT_WEIGHTS = {
    "click": 1.0,
    "view_detail": 1.0,
    "wishlist": 2.0,
    "add_to_cart": 3.0,
    "purchase": 5.0,
}
NEGATIVE_EVENT_WEIGHTS = {
    "hide": 2.0,
    "dislike": 3.0,
}
VIEW_DETAIL_DWELL_BONUS_MS = 60_000
VIEW_DETAIL_DWELL_BONUS_CAP = 1.0
COLD_ITEM_INTERACTION_THRESHOLD = 20
DEFAULT_BATCH_SIZE = 500


@dataclass
class SignalBuildStats:
    events_seen: int = 0
    events_skipped: int = 0
    recommendation_logs_matched: int = 0
    signals_built: int = 0
    item_stats_built: int = 0
    signal_write_batches: int = 0
    item_stats_write_batches: int = 0
    processed_write_batches: int = 0
    signals_written: int = 0
    item_stats_written: int = 0
    events_marked_processed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "events_seen": self.events_seen,
            "events_skipped": self.events_skipped,
            "recommendation_logs_matched": self.recommendation_logs_matched,
            "signals_built": self.signals_built,
            "item_stats_built": self.item_stats_built,
            "signal_write_batches": self.signal_write_batches,
            "item_stats_write_batches": self.item_stats_write_batches,
            "processed_write_batches": self.processed_write_batches,
            "signals_written": self.signals_written,
            "item_stats_written": self.item_stats_written,
            "events_marked_processed": self.events_marked_processed,
            "errors": list(self.errors),
        }


@dataclass
class SignalBuildArtifacts:
    signal_docs: list[dict[str, Any]]
    item_stats_docs: list[dict[str, Any]]
    processed_event_ids: list[str]
    stats: SignalBuildStats


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


def _round_score(value: float) -> float:
    return round(float(value), 6)


def _event_timestamp(event: dict[str, Any]) -> str | None:
    for field_name in ("timestamp", "created_at", "shown_at"):
        value = event.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _max_timestamp(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _min_timestamp(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _empty_event_counts() -> dict[str, int]:
    return {event_type: 0 for event_type in EVENT_TYPES}


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, (tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _positive_weight(event: dict[str, Any]) -> float:
    event_type = event.get("event_type")
    if event_type != "view_detail":
        return POSITIVE_EVENT_WEIGHTS.get(str(event_type), 0.0)

    dwell_time_ms = max(_safe_int(event.get("dwell_time_ms"), 0), 0)
    dwell_bonus = min(dwell_time_ms / VIEW_DETAIL_DWELL_BONUS_MS, VIEW_DETAIL_DWELL_BONUS_CAP)
    return POSITIVE_EVENT_WEIGHTS["view_detail"] + dwell_bonus


def _negative_weight(event: dict[str, Any]) -> float:
    return NEGATIVE_EVENT_WEIGHTS.get(str(event.get("event_type")), 0.0)


def _recommendation_score(log: dict[str, Any] | None) -> float:
    if not log:
        return 0.0
    scores = log.get("scores")
    if not isinstance(scores, dict):
        return 0.0
    for field_name in (
        "final_score",
        "profile_score",
        "query_hybrid_score",
        "semantic_neighbor_score",
        "category_affinity_score",
        "price_affinity_score",
    ):
        score = _safe_float(scores.get(field_name), 0.0)
        if score > 0:
            return score
    return 0.0


def _reason_source(attribution: dict[str, Any]) -> str:
    for field_name in ("candidate_sources", "matched_channels"):
        values = _as_string_list(attribution.get(field_name))
        if values:
            return values[0]
    return "recommendation_log"


def _reason_intents(attribution: dict[str, Any]) -> list[str]:
    return _as_string_list(attribution.get("matched_intents"))[:5]


def _merge_reason_scores(
    reasons: dict[tuple[str, str], dict[str, Any]],
    *,
    event: dict[str, Any],
    log: dict[str, Any] | None,
    event_weight: float,
) -> None:
    if not log:
        return
    attribution = log.get("attribution")
    if not isinstance(attribution, dict):
        return

    intents = _reason_intents(attribution)
    if not intents:
        return

    source = _reason_source(attribution)
    base_score = _recommendation_score(log)
    score = max(base_score, 0.1) * max(abs(event_weight), 1.0)
    last_seen_at = _event_timestamp(event) or log.get("shown_at")

    for intent in intents:
        key = (intent, source)
        existing = reasons.setdefault(
            key,
            {"intent": intent, "source": source, "score": 0.0, "last_seen_at": None},
        )
        existing["score"] = _round_score(float(existing["score"]) + score)
        existing["last_seen_at"] = _max_timestamp(existing.get("last_seen_at"), last_seen_at)


def _signal_doc_from_state(
    *,
    user_id_hash: str,
    item_id: str,
    state: dict[str, Any],
    updated_at: str,
) -> dict[str, Any]:
    positive_score = _round_score(state["positive_score"])
    negative_score = _round_score(state["negative_score"])
    implicit_score = _round_score(positive_score - negative_score)
    confidence = _round_score(
        state["event_counts"]["impression"] * 0.1 + positive_score + negative_score
    )
    reason_scores = sorted(
        state["reason_scores"].values(),
        key=lambda reason: (-float(reason["score"]), reason["intent"], reason["source"]),
    )[:10]

    doc = UserItemSignalDocument(
        _id={"user_id_hash": user_id_hash, "item_id": item_id},
        user_id_hash=user_id_hash,
        item_id=item_id,
        implicit_score=implicit_score,
        confidence=confidence,
        positive_score=positive_score,
        negative_score=negative_score,
        preference=implicit_score > 0 and positive_score >= 1.0,
        event_counts=state["event_counts"],
        reason_scores=reason_scores,
        first_interaction_at=state["first_interaction_at"],
        last_interaction_at=state["last_interaction_at"],
        updated_at=updated_at,
    )
    return to_mongo_dict(doc)


def _quality_score(*, ctr: float, cart_rate: float, purchase_rate: float) -> float:
    return _round_score(min(1.0, max(0.0, 0.55 * ctr + 0.25 * cart_rate + 0.20 * purchase_rate)))


def _item_stats_doc_from_state(item_id: str, state: dict[str, Any], updated_at: str) -> dict[str, Any]:
    counts = state["event_counts"]
    impression_count = counts["impression"]
    interaction_count = sum(counts.values())
    ctr = _round_score(counts["click"] / impression_count) if impression_count else 0.0
    cart_rate = _round_score(counts["add_to_cart"] / impression_count) if impression_count else 0.0
    purchase_rate = _round_score(counts["purchase"] / impression_count) if impression_count else 0.0

    doc = ItemStatsDocument(
        _id=item_id,
        item_id=item_id,
        impression_count=counts["impression"],
        click_count=counts["click"],
        view_detail_count=counts["view_detail"],
        add_to_cart_count=counts["add_to_cart"],
        purchase_count=counts["purchase"],
        hide_count=counts["hide"],
        dislike_count=counts["dislike"],
        ctr=ctr,
        cart_rate=cart_rate,
        purchase_rate=purchase_rate,
        first_seen_at=state["first_seen_at"],
        last_interaction_at=state["last_interaction_at"],
        cold_start={
            "is_cold_item": interaction_count < COLD_ITEM_INTERACTION_THRESHOLD,
            "interaction_count": interaction_count,
            "age_days": None,
        },
        quality_score=_quality_score(ctr=ctr, cart_rate=cart_rate, purchase_rate=purchase_rate),
        updated_at=updated_at,
    )
    return to_mongo_dict(doc)


def build_signal_artifacts(
    *,
    events: list[dict[str, Any]],
    recommendation_logs_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
    updated_at: str | None = None,
) -> SignalBuildArtifacts:
    updated_at = updated_at or utc_now_iso()
    recommendation_logs_by_key = recommendation_logs_by_key or {}
    stats = SignalBuildStats(events_seen=len(events))
    signal_states: dict[tuple[str, str], dict[str, Any]] = {}
    item_states: dict[str, dict[str, Any]] = {}
    processed_event_ids: list[str] = []
    seen_event_ids: set[str] = set()

    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        user_id_hash = str(event.get("user_id_hash") or "").strip()
        item_id = str(event.get("item_id") or "").strip()
        event_type = str(event.get("event_type") or "").strip()
        if not event_id or not user_id_hash or not item_id or event_type not in EVENT_TYPES:
            stats.events_skipped += 1
            continue
        if event_id in seen_event_ids:
            stats.events_skipped += 1
            continue
        seen_event_ids.add(event_id)
        processed_event_ids.append(event_id)

        timestamp = _event_timestamp(event)
        positive_weight = _positive_weight(event)
        negative_weight = _negative_weight(event)
        event_weight = positive_weight - negative_weight
        log_key = (str(event.get("request_id") or "").strip(), item_id)
        log = recommendation_logs_by_key.get(log_key)
        if log is not None:
            stats.recommendation_logs_matched += 1

        signal_key = (user_id_hash, item_id)
        signal_state = signal_states.setdefault(
            signal_key,
            {
                "event_counts": _empty_event_counts(),
                "positive_score": 0.0,
                "negative_score": 0.0,
                "first_interaction_at": None,
                "last_interaction_at": None,
                "reason_scores": {},
            },
        )
        signal_state["event_counts"][event_type] += 1
        signal_state["positive_score"] += positive_weight
        signal_state["negative_score"] += negative_weight
        signal_state["first_interaction_at"] = _min_timestamp(signal_state["first_interaction_at"], timestamp)
        signal_state["last_interaction_at"] = _max_timestamp(signal_state["last_interaction_at"], timestamp)
        _merge_reason_scores(signal_state["reason_scores"], event=event, log=log, event_weight=event_weight)

        item_state = item_states.setdefault(
            item_id,
            {
                "event_counts": _empty_event_counts(),
                "first_seen_at": None,
                "last_interaction_at": None,
            },
        )
        item_state["event_counts"][event_type] += 1
        item_state["first_seen_at"] = _min_timestamp(item_state["first_seen_at"], timestamp)
        item_state["last_interaction_at"] = _max_timestamp(item_state["last_interaction_at"], timestamp)

    signal_docs = [
        _signal_doc_from_state(user_id_hash=user_id_hash, item_id=item_id, state=state, updated_at=updated_at)
        for (user_id_hash, item_id), state in sorted(signal_states.items())
    ]
    item_stats_docs = [
        _item_stats_doc_from_state(item_id, state, updated_at)
        for item_id, state in sorted(item_states.items())
    ]
    stats.signals_built = len(signal_docs)
    stats.item_stats_built = len(item_stats_docs)
    return SignalBuildArtifacts(
        signal_docs=signal_docs,
        item_stats_docs=item_stats_docs,
        processed_event_ids=processed_event_ids,
        stats=stats,
    )


def _project_doc(doc: dict[str, Any], projection: dict[str, int] | None) -> dict[str, Any]:
    if not projection:
        return dict(doc)
    return {key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc}


def _load_clickstream_events(clickstream_events_collection: Any, limit_events: int | None = None) -> list[dict[str, Any]]:
    projection = {
        "_id": 1,
        "event_id": 1,
        "request_id": 1,
        "user_id_hash": 1,
        "session_id": 1,
        "event_type": 1,
        "item_id": 1,
        "rank_position": 1,
        "dwell_time_ms": 1,
        "timestamp": 1,
        "created_at": 1,
        "processed": 1,
        "is_synthetic": 1,
    }
    cursor = clickstream_events_collection.find({}, projection)
    if limit_events is not None and hasattr(cursor, "limit"):
        cursor = cursor.limit(limit_events)
    events = [_project_doc(doc, projection) for doc in cursor]
    if limit_events is not None:
        return events[:limit_events]
    return events


def _chunked(values: list[Any], chunk_size: int) -> list[list[Any]]:
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


def _load_recommendation_logs(
    recommendation_logs_collection: Any,
    events: list[dict[str, Any]],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[tuple[str, str], dict[str, Any]]:
    projection = {
        "_id": 1,
        "request_id": 1,
        "item_id": 1,
        "scores": 1,
        "attribution": 1,
        "shown_at": 1,
        "rank_position": 1,
        "algorithm_version": 1,
        "ranking_version": 1,
    }
    keys = sorted(
        {
            (str(event.get("request_id") or "").strip(), str(event.get("item_id") or "").strip())
            for event in events
            if str(event.get("request_id") or "").strip() and str(event.get("item_id") or "").strip()
        }
    )
    logs: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in _chunked(keys, batch_size):
        query = {"$or": [{"request_id": request_id, "item_id": item_id} for request_id, item_id in chunk]}
        for log in recommendation_logs_collection.find(query, projection):
            request_id = str(log.get("request_id") or "").strip()
            item_id = str(log.get("item_id") or "").strip()
            if request_id and item_id:
                logs[(request_id, item_id)] = _project_doc(log, projection)
    return logs


def _signal_upsert_operation(doc: dict[str, Any]) -> UpdateOne:
    payload = dict(doc)
    doc_id = payload.pop("_id")
    return UpdateOne(
        {"user_id_hash": payload["user_id_hash"], "item_id": payload["item_id"]},
        {"$set": payload, "$setOnInsert": {"_id": doc_id}},
        upsert=True,
    )


def _item_stats_upsert_operation(doc: dict[str, Any]) -> UpdateOne:
    payload = dict(doc)
    doc_id = payload.pop("_id")
    return UpdateOne(
        {"_id": doc_id},
        {"$set": payload, "$setOnInsert": {"_id": doc_id}},
        upsert=True,
    )


def _processed_operation(event_id: str, processed_at: str) -> UpdateOne:
    return UpdateOne({"event_id": event_id}, {"$set": {"processed": True, "processed_at": processed_at}})


def _bulk_write_operations(collection: Any, operations: list[UpdateOne], batch_size: int) -> dict[str, int]:
    summary = {"batches": 0, "written": 0}
    for batch in _chunked(operations, batch_size):
        if not batch:
            continue
        result = collection.bulk_write(batch, ordered=False)
        summary["batches"] += 1
        summary["written"] += int(getattr(result, "upserted_count", 0)) + int(
            getattr(result, "modified_count", 0)
        )
    return summary


def build_user_item_signals(
    *,
    clickstream_events_collection: Any,
    recommendation_logs_collection: Any,
    user_item_signals_collection: Any | None = None,
    item_stats_collection: Any | None = None,
    write: bool = False,
    rebuild_item_stats: bool = False,
    limit_events: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    updated_at: str | None = None,
) -> dict[str, Any]:
    if limit_events is not None and limit_events <= 0:
        raise ValueError("limit_events must be positive when provided")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if write and user_item_signals_collection is None:
        raise ValueError("user_item_signals_collection is required when write=True")
    if write and rebuild_item_stats and item_stats_collection is None:
        raise ValueError("item_stats_collection is required when write=True and rebuild_item_stats=True")
    if write and limit_events is not None:
        if not hasattr(clickstream_events_collection, "count_documents"):
            raise ValueError("unsafe_partial_signal_write: cannot verify complete clickstream input for limited write")
        total_events = int(clickstream_events_collection.count_documents({}))
        if limit_events < total_events:
            raise ValueError(
                "unsafe_partial_signal_write: limited write would aggregate "
                f"{limit_events} of {total_events} clickstream events"
            )

    updated_at = updated_at or utc_now_iso()
    events = _load_clickstream_events(clickstream_events_collection, limit_events=limit_events)
    logs_by_key = _load_recommendation_logs(recommendation_logs_collection, events, batch_size=batch_size)
    artifacts = build_signal_artifacts(
        events=events,
        recommendation_logs_by_key=logs_by_key,
        updated_at=updated_at,
    )
    stats = artifacts.stats

    if write:
        signal_summary = _bulk_write_operations(
            user_item_signals_collection,
            [_signal_upsert_operation(doc) for doc in artifacts.signal_docs],
            batch_size,
        )
        stats.signal_write_batches = signal_summary["batches"]
        stats.signals_written = signal_summary["written"]

        if rebuild_item_stats:
            item_stats_summary = _bulk_write_operations(
                item_stats_collection,
                [_item_stats_upsert_operation(doc) for doc in artifacts.item_stats_docs],
                batch_size,
            )
            stats.item_stats_write_batches = item_stats_summary["batches"]
            stats.item_stats_written = item_stats_summary["written"]

        processed_summary = _bulk_write_operations(
            clickstream_events_collection,
            [_processed_operation(event_id, updated_at) for event_id in artifacts.processed_event_ids],
            batch_size,
        )
        stats.processed_write_batches = processed_summary["batches"]
        stats.events_marked_processed = processed_summary["written"]

    sample_signals = artifacts.signal_docs[:3]
    sample_item_stats = artifacts.item_stats_docs[:3] if rebuild_item_stats else []
    return {
        "ok": not stats.errors,
        "write": write,
        "rebuild_item_stats": rebuild_item_stats,
        "limit_events": limit_events,
        "stats": stats.as_dict(),
        "sample_signals": sample_signals,
        "sample_item_stats": sample_item_stats,
    }
