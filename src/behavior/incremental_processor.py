from __future__ import annotations

from typing import Any

from src.behavior.profile_builder import build_user_profiles
from src.behavior.signal_builder import (
    DEFAULT_BATCH_SIZE,
    EVENT_TYPES,
    _bulk_write_operations,
    _event_timestamp,
    _item_stats_upsert_operation,
    _load_recommendation_logs,
    _processed_operation,
    _project_doc,
    _signal_upsert_operation,
    build_signal_artifacts,
)
from src.utils import utc_now_iso


CF_RELEVANT_EVENT_TYPES = {
    "click",
    "view_detail",
    "wishlist",
    "add_to_cart",
    "purchase",
    "hide",
    "dislike",
}

EVENT_PROJECTION = {
    "_id": 1,
    "event_id": 1,
    "request_id": 1,
    "user_id_hash": 1,
    "session_id": 1,
    "surface": 1,
    "event_type": 1,
    "item_id": 1,
    "rank_position": 1,
    "dwell_time_ms": 1,
    "timestamp": 1,
    "created_at": 1,
    "processed": 1,
    "is_synthetic": 1,
    "metadata": 1,
}


def _find_events(collection: Any, filter_doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [_project_doc(doc, EVENT_PROJECTION) for doc in collection.find(filter_doc, EVENT_PROJECTION)]


def _stable_event_key(event: dict[str, Any]) -> tuple[str, str]:
    return (_event_timestamp(event) or "", str(event.get("event_id") or ""))


def _load_pending_events(collection: Any, max_events: int, user_id_hash: str | None = None) -> list[dict[str, Any]]:
    filter_doc: dict[str, Any] = {"processed": {"$ne": True}}
    normalized_user_id = str(user_id_hash or "").strip()
    if normalized_user_id:
        filter_doc["user_id_hash"] = normalized_user_id
    pending = _find_events(collection, filter_doc)
    return sorted(pending, key=_stable_event_key)[:max_events]


def _valid_pending_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if str(event.get("event_id") or "").strip()
        and str(event.get("user_id_hash") or "").strip()
        and str(event.get("item_id") or "").strip()
        and str(event.get("event_type") or "").strip() in EVENT_TYPES
    ]


def process_pending_behavior(
    *,
    clickstream_events_collection: Any,
    recommendation_logs_collection: Any,
    user_item_signals_collection: Any | None = None,
    item_stats_collection: Any | None = None,
    user_profiles_collection: Any | None = None,
    item_hype_profiles_collection: Any | None = None,
    items_collection: Any | None = None,
    retrieval_units_collection: Any | None = None,
    write: bool = False,
    rebuild_item_stats: bool = True,
    max_events: int = 100,
    batch_size: int = DEFAULT_BATCH_SIZE,
    user_id_hash: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    if max_events <= 0:
        raise ValueError("max_events must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if write and user_item_signals_collection is None:
        raise ValueError("user_item_signals_collection is required when write=True")
    if write and rebuild_item_stats and item_stats_collection is None:
        raise ValueError("item_stats_collection is required when rebuilding item stats")
    if write and any(
        collection is None
        for collection in (user_profiles_collection, item_hype_profiles_collection, items_collection)
    ):
        raise ValueError("profile collections are required when write=True")

    updated_at = updated_at or utc_now_iso()
    normalized_user_id_hash = str(user_id_hash or "").strip() or None
    selected_events = _load_pending_events(clickstream_events_collection, max_events, normalized_user_id_hash)
    valid_events = _valid_pending_events(selected_events)
    affected_keys = sorted(
        {
            (str(event["user_id_hash"]).strip(), str(event["item_id"]).strip())
            for event in valid_events
        }
    )
    affected_user_ids = {user_id for user_id, _item_id in affected_keys}
    affected_item_ids = {item_id for _user_id, item_id in affected_keys}
    source_event_max_timestamp = max(
        (_event_timestamp(event) for event in valid_events if _event_timestamp(event)),
        default=None,
    )
    cf_refresh_required = any(
        str(event.get("event_type") or "").strip() in CF_RELEVANT_EVENT_TYPES
        for event in valid_events
    )

    base_result: dict[str, Any] = {
        "ok": True,
        "mode": "write" if write else "dry-run",
        "processing_mode": "incremental_pending",
        "target_user_id_hash": normalized_user_id_hash,
        "events_selected": len(selected_events),
        "events_valid": len(valid_events),
        "affected_user_count": len(affected_user_ids),
        "affected_item_count": len(affected_item_ids),
        "signals_written": 0,
        "profiles_written": 0,
        "item_stats_written": 0,
        "events_marked_processed": 0,
        "source_event_max_timestamp": source_event_max_timestamp,
        "cf_refresh_required": cf_refresh_required,
    }
    if not valid_events:
        return base_result

    signal_events = _find_events(
        clickstream_events_collection,
        {
            "$or": [
                {"user_id_hash": user_id, "item_id": item_id}
                for user_id, item_id in affected_keys
            ]
        },
    )
    logs_by_key = _load_recommendation_logs(
        recommendation_logs_collection,
        signal_events,
        batch_size=batch_size,
    )
    signal_artifacts = build_signal_artifacts(
        events=signal_events,
        recommendation_logs_by_key=logs_by_key,
        updated_at=updated_at,
    )
    signal_docs = [
        doc
        for doc in signal_artifacts.signal_docs
        if (str(doc.get("user_id_hash") or ""), str(doc.get("item_id") or "")) in set(affected_keys)
    ]

    item_stats_docs: list[dict[str, Any]] = []
    if rebuild_item_stats:
        item_events = _find_events(
            clickstream_events_collection,
            {"item_id": {"$in": sorted(affected_item_ids)}},
        )
        item_stats_docs = build_signal_artifacts(events=item_events, updated_at=updated_at).item_stats_docs

    base_result["signals_built"] = len(signal_docs)
    base_result["item_stats_built"] = len(item_stats_docs)
    base_result["sample_signals"] = signal_docs[:3]
    base_result["sample_item_stats"] = item_stats_docs[:3]
    if not write:
        return base_result

    signal_summary = _bulk_write_operations(
        user_item_signals_collection,
        [_signal_upsert_operation(doc) for doc in signal_docs],
        batch_size,
    )
    base_result["signals_written"] = signal_summary["written"]

    if rebuild_item_stats:
        item_summary = _bulk_write_operations(
            item_stats_collection,
            [_item_stats_upsert_operation(doc) for doc in item_stats_docs],
            batch_size,
        )
        base_result["item_stats_written"] = item_summary["written"]

    profile_result = build_user_profiles(
        user_item_signals_collection=user_item_signals_collection,
        clickstream_events_collection=clickstream_events_collection,
        recommendation_logs_collection=recommendation_logs_collection,
        item_hype_profiles_collection=item_hype_profiles_collection,
        items_collection=items_collection,
        retrieval_units_collection=retrieval_units_collection,
        user_profiles_collection=user_profiles_collection,
        write=True,
        user_ids=affected_user_ids,
        batch_size=batch_size,
        updated_at=updated_at,
    )
    if not profile_result.get("ok"):
        raise RuntimeError("incremental profile refresh failed; pending events were not marked processed")
    base_result["profiles_written"] = int(profile_result.get("stats", {}).get("profiles_written", 0))
    base_result["profiles_built"] = int(profile_result.get("stats", {}).get("profiles_built", 0))

    processed_summary = _bulk_write_operations(
        clickstream_events_collection,
        [_processed_operation(str(event["event_id"]), updated_at) for event in valid_events],
        batch_size,
    )
    base_result["events_marked_processed"] = processed_summary["written"]
    return base_result
