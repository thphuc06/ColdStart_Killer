from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError

from src.behavior.schemas import ClickstreamEventDocument, RecommendationLogDocument
from src.config import get_settings
from src.schemas import to_mongo_dict


IMPRESSION_EVENT_TYPE = "impression"
ATTRIBUTED_SURFACES = {"search", "home", "detail_similar"}


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_dict(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a dictionary when provided")
    return dict(value)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rank_position(item: dict[str, Any], fallback_rank: int) -> int:
    value = item.get("rank_position", item.get("rank", fallback_rank))
    try:
        rank = int(value)
    except (TypeError, ValueError):
        rank = fallback_rank
    return max(rank, 1)


def _normalize_scores(item: dict[str, Any]) -> dict[str, Any]:
    scores = item.get("scores", item.get("score_breakdown"))
    if isinstance(scores, dict):
        normalized = dict(scores)
    else:
        normalized = {}

    score = _number(item.get("final_score", item.get("score")), 0.0)
    normalized.setdefault("query_hybrid_score", _number(item.get("query_hybrid_score"), score))
    normalized.setdefault("profile_score", _number(item.get("profile_score"), 0.0))
    normalized.setdefault("semantic_neighbor_score", _number(item.get("semantic_neighbor_score"), 0.0))
    normalized.setdefault("item_item_cf_score", _number(item.get("item_item_cf_score"), 0.0))
    normalized.setdefault("cold_start_boost", _number(item.get("cold_start_boost"), 0.0))
    normalized.setdefault("exploration_score", _number(item.get("exploration_score"), 0.0))
    normalized.setdefault("final_score", score)
    return normalized


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, (tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str) and value:
        return [value]
    return []


def _normalize_attribution(item: dict[str, Any]) -> dict[str, Any]:
    attribution = item.get("attribution")
    if isinstance(attribution, dict):
        normalized = dict(attribution)
    else:
        debug = _optional_dict(item.get("debug"), "debug")
        matched_channels = _as_string_list(item.get("matched_channels", debug.get("matched_channels")))
        normalized = {
            "matched_unit_ids": _as_string_list(item.get("matched_unit_ids")),
            "matched_intents": _as_string_list(item.get("matched_intent")),
            "matched_facts": _as_string_list(item.get("matched_fact")),
            "matched_channels": matched_channels,
            "candidate_sources": matched_channels,
            "matched_profile_interest_ids": _as_string_list(item.get("matched_profile_interest_ids")),
            "explanation": str(item.get("why_shown") or item.get("cold_start_note") or ""),
        }

    if "cf_evidence" in normalized and not normalized["cf_evidence"]:
        normalized["cf_evidence"] = None
    return normalized


def _normalize_query(query: dict[str, Any] | None) -> dict[str, Any]:
    payload = _optional_dict(query, "query")
    if "query_type" not in payload:
        payload["query_type"] = "none"
    return payload


def _build_recommendation_doc(
    *,
    request_id: str,
    surface: str,
    user_id_hash: str,
    session_id: str,
    algorithm_version: str,
    ranking_version: str,
    query: dict[str, Any] | None,
    item: dict[str, Any],
    fallback_rank: int,
    is_synthetic: bool = False,
) -> dict[str, Any]:
    item_id = _required_text(item.get("item_id", item.get("_id")), "item_id")
    doc = RecommendationLogDocument(
        request_id=request_id,
        surface=surface,
        user_id_hash=user_id_hash,
        session_id=session_id,
        algorithm_version=algorithm_version,
        ranking_version=ranking_version,
        query=_normalize_query(query),
        item_id=item_id,
        rank_position=_rank_position(item, fallback_rank),
        scores=_normalize_scores(item),
        attribution=_normalize_attribution(item),
        is_synthetic=is_synthetic,
    )
    return to_mongo_dict(doc)


def _snapshot_operation(doc: dict[str, Any]) -> UpdateOne:
    return UpdateOne(
        {"request_id": doc["request_id"], "item_id": doc["item_id"]},
        {"$setOnInsert": doc},
        upsert=True,
    )


def log_recommendation_snapshot(
    *,
    request_id: str,
    user_id_hash: str,
    session_id: str,
    surface: str,
    items: list[dict[str, Any]],
    algorithm_version: str | None = None,
    ranking_version: str | None = None,
    query: dict[str, Any] | None = None,
    is_synthetic: bool = False,
    recommendation_logs_collection: Any | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_event_logging:
        return {"ok": True, "skipped": True, "reason": "event logging disabled"}
    if not isinstance(items, list):
        raise ValueError("items must be a list of dictionaries")
    if not items:
        return {"ok": True, "request_id": request_id, "attempted": 0, "inserted": 0, "existing": 0}

    request_id = _required_text(request_id, "request_id")
    user_id_hash = _required_text(user_id_hash, "user_id_hash")
    session_id = _required_text(session_id, "session_id")
    surface = _required_text(surface, "surface")
    algorithm_version = _required_text(algorithm_version or settings.algorithm_version, "algorithm_version")
    ranking_version = _required_text(ranking_version or settings.ranking_version, "ranking_version")

    docs = [
        _build_recommendation_doc(
            request_id=request_id,
            surface=surface,
            user_id_hash=user_id_hash,
            session_id=session_id,
            algorithm_version=algorithm_version,
            ranking_version=ranking_version,
            query=query,
            item=item,
            fallback_rank=index,
            is_synthetic=is_synthetic,
        )
        for index, item in enumerate(items, start=1)
    ]

    if recommendation_logs_collection is None:
        from src.mongodb import get_recommendation_logs_collection

        recommendation_logs_collection = get_recommendation_logs_collection()

    result = recommendation_logs_collection.bulk_write(
        [_snapshot_operation(doc) for doc in docs],
        ordered=False,
    )
    inserted = int(getattr(result, "upserted_count", 0))
    existing = int(getattr(result, "matched_count", 0))
    return {
        "ok": True,
        "request_id": request_id,
        "surface": surface,
        "attempted": len(docs),
        "inserted": inserted,
        "existing": existing,
        "algorithm_version": algorithm_version,
        "ranking_version": ranking_version,
    }


def impression_idempotency_key(request_id: str, item_id: str) -> str:
    return f"imp:{_required_text(request_id, 'request_id')}:{_required_text(item_id, 'item_id')}"


def _find_existing_event(collection: Any, doc: dict[str, Any]) -> dict[str, Any] | None:
    existing = collection.find_one({"event_id": doc["event_id"]})
    if existing:
        return existing
    idempotency_key = doc.get("idempotency_key")
    if idempotency_key:
        existing = collection.find_one({"idempotency_key": idempotency_key})
        if existing:
            return existing
    if doc.get("event_type") == IMPRESSION_EVENT_TYPE and doc.get("request_id"):
        return collection.find_one(
            {
                "request_id": doc["request_id"],
                "item_id": doc["item_id"],
                "event_type": IMPRESSION_EVENT_TYPE,
            }
        )
    return None


def log_clickstream_event(
    *,
    user_id_hash: str,
    session_id: str,
    item_id: str,
    event_type: str,
    surface: str,
    event_id: str | None = None,
    request_id: str | None = None,
    idempotency_key: str | None = None,
    query_text: str = "",
    rank_position: int | None = None,
    dwell_time_ms: int | None = None,
    is_synthetic: bool = False,
    client: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    clickstream_events_collection: Any | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_event_logging:
        return {"ok": True, "skipped": True, "reason": "event logging disabled"}

    item_id = _required_text(item_id, "item_id")
    event_type = _required_text(event_type, "event_type")
    surface = _required_text(surface, "surface")
    request_id = request_id.strip() if isinstance(request_id, str) and request_id.strip() else None

    if event_type == IMPRESSION_EVENT_TYPE:
        if request_id is None:
            raise ValueError("request_id is required for impression events")
        idempotency_key = idempotency_key or impression_idempotency_key(request_id, item_id)
    elif surface in ATTRIBUTED_SURFACES and request_id is None:
        raise ValueError(f"request_id is required for {surface} {event_type} events")

    doc = ClickstreamEventDocument(
        event_id=event_id or f"evt_{uuid4().hex}",
        idempotency_key=idempotency_key,
        request_id=request_id,
        user_id_hash=user_id_hash,
        session_id=session_id,
        surface=surface,
        event_type=event_type,
        item_id=item_id,
        query_text=query_text,
        rank_position=rank_position,
        dwell_time_ms=dwell_time_ms,
        is_synthetic=is_synthetic,
        client=_optional_dict(client, "client"),
        metadata=_optional_dict(metadata, "metadata"),
    )
    payload = to_mongo_dict(doc)

    if clickstream_events_collection is None:
        from src.mongodb import get_clickstream_events_collection

        clickstream_events_collection = get_clickstream_events_collection()

    try:
        result = clickstream_events_collection.insert_one(payload)
    except DuplicateKeyError:
        existing = _find_existing_event(clickstream_events_collection, payload)
        if existing is None:
            raise
        return {
            "ok": True,
            "inserted": False,
            "idempotent": True,
            "event_id": existing.get("event_id", payload["event_id"]),
            "event_type": payload["event_type"],
            "request_id": payload.get("request_id"),
            "item_id": payload["item_id"],
        }

    return {
        "ok": True,
        "inserted": True,
        "idempotent": False,
        "inserted_id": str(getattr(result, "inserted_id", "")),
        "event_id": payload["event_id"],
        "event_type": payload["event_type"],
        "request_id": payload.get("request_id"),
        "item_id": payload["item_id"],
    }
