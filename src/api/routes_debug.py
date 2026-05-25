from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from scripts.reset_demo_behavior_data import CATALOG_COLLECTIONS, execute_reset
from src.behavior.incremental_processor import CF_RELEVANT_EVENT_TYPES, process_pending_behavior
from src.behavior.profile_builder import build_user_profiles
from src.behavior.signal_builder import build_user_item_signals
from src.config import configured_model_versions, get_settings
from src.behavior.synthetic_generator import (
    build_synthetic_behavior_plan,
    load_candidates_from_collections,
    write_synthetic_behavior_plan,
)
from src.mongodb import (
    get_clickstream_events_collection,
    get_item_hype_profiles_collection,
    get_item_item_cf_edges_collection,
    get_item_semantic_neighbors_collection,
    get_item_stats_collection,
    get_items_collection,
    get_recommendation_logs_collection,
    get_retrieval_units_collection,
    get_synthetic_personas_collection,
    get_user_item_signals_collection,
    get_user_profiles_collection,
    get_users_collection,
    get_database,
)
from src.recommendation.item_item_cf import build_item_item_cf_edges
from src.recommendation.candidate_sources import clear_catalog_snapshot_cache


router = APIRouter(prefix="/api")


RESET_CONFIRMATION_MESSAGE = "This will clear current demo interactions."


def _safe_list(cursor: Any, limit: int) -> list[dict[str, Any]]:
    return list(cursor.limit(limit)) if hasattr(cursor, "limit") else list(cursor)[:limit]


def _require_reset_confirmation(*, write: bool, full: bool, confirm: str | None) -> None:
    if not write:
        return
    expected = "FULL_DEMO_RESET" if full else "DEMO_RESET"
    if confirm == expected:
        return
    raise HTTPException(
        status_code=400,
        detail={
            "error": "confirmation_required",
            "message": RESET_CONFIRMATION_MESSAGE,
            "expected_confirm": expected,
        },
    )


def _collection_count(collection_getter) -> int:
    return int(collection_getter().count_documents({}))


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _latest_timestamp(values: list[Any]) -> str | None:
    parsed = [(timestamp, _parse_timestamp(timestamp)) for timestamp in values]
    valid = [(timestamp, moment) for timestamp, moment in parsed if moment is not None]
    if not valid:
        return None
    return str(max(valid, key=lambda row: row[1])[0])


def _model_version_from_doc(doc: dict[str, Any] | None) -> str | None:
    if not isinstance(doc, dict):
        return None
    derivation = doc.get("derivation") if isinstance(doc.get("derivation"), dict) else {}
    version = str(derivation.get("model_version") or "").strip()
    return version or None


def _model_version_from_docs(docs: list[dict[str, Any]]) -> str | None:
    versions = sorted({version for version in (_model_version_from_doc(doc) for doc in docs) if version})
    if not versions:
        return None
    if len(versions) == 1:
        return versions[0]
    return "mixed"


def _source_signal_version_from_doc(doc: dict[str, Any] | None) -> str | None:
    if not isinstance(doc, dict):
        return None
    derivation = doc.get("derivation") if isinstance(doc.get("derivation"), dict) else {}
    version = str(derivation.get("source_signal_model_version") or "").strip()
    return version or None


def _source_signal_version_from_docs(docs: list[dict[str, Any]]) -> str | None:
    versions = sorted({version for version in (_source_signal_version_from_doc(doc) for doc in docs) if version})
    if not versions:
        return None
    if len(versions) == 1:
        return versions[0]
    return "mixed"


def _derivation_text(doc: dict[str, Any] | None, field_name: str) -> str | None:
    if not isinstance(doc, dict):
        return None
    derivation = doc.get("derivation") if isinstance(doc.get("derivation"), dict) else {}
    value = str(derivation.get(field_name) or "").strip()
    return value or None


def _derivation_text_from_docs(docs: list[dict[str, Any]], field_name: str) -> str | None:
    values = [_derivation_text(doc, field_name) for doc in docs]
    return _latest_timestamp([value for value in values if value])


def _model_versions_snapshot(
    *,
    profile_doc: dict[str, Any] | None,
    signals: list[dict[str, Any]],
    cf_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    configured = configured_model_versions(get_settings())
    stored = {
        "signal_model_version": _model_version_from_docs(signals),
        "profile_model_version": _model_version_from_doc(profile_doc),
        "cf_model_version": _model_version_from_docs(cf_edges),
        "explanation_version": None,
    }
    stale_version_components = [
        component_name.replace("_model_version", "")
        for component_name, configured_version in configured.items()
        if component_name != "explanation_version"
        and stored.get(component_name) not in {None, configured_version}
    ]
    source_signal_versions = {
        "profile": _source_signal_version_from_doc(profile_doc),
        "cf": _source_signal_version_from_docs(cf_edges),
    }
    for component_name, source_signal_version in source_signal_versions.items():
        if source_signal_version not in {None, configured["signal_model_version"]} and component_name not in stale_version_components:
            stale_version_components.append(component_name)
    return {
        "configured": configured,
        "stored": stored,
        "stale_version_components": stale_version_components,
    }


def _freshness_snapshot(
    *,
    profile_doc: dict[str, Any] | None,
    signals: list[dict[str, Any]],
    events: list[dict[str, Any]],
    cf_edges: list[dict[str, Any]],
    pending_event_count: int,
    cf_lineage_docs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cf_status_docs = cf_lineage_docs if cf_lineage_docs is not None else cf_edges
    latest_event_at = _latest_timestamp([event.get("timestamp") for event in events])
    signal_built_at = _latest_timestamp(
        [
            _derivation_text(signal, "built_at") or signal.get("updated_at")
            for signal in signals
        ]
    )
    profile_built_at = str(profile_doc.get("updated_at") or "") or None if profile_doc else None
    cf_built_at = _latest_timestamp(
        [
            _derivation_text(edge, "built_at") or edge.get("updated_at")
            for edge in cf_status_docs
        ]
    )
    model_versions = _model_versions_snapshot(profile_doc=profile_doc, signals=signals, cf_edges=cf_status_docs)
    latest_event_time = _parse_timestamp(latest_event_at)
    stale_components: list[str] = []
    for name, timestamp in (("signals", signal_built_at), ("profile", profile_built_at)):
        built_time = _parse_timestamp(timestamp)
        if latest_event_time and (built_time is None or built_time < latest_event_time):
            stale_components.append(name)
    if pending_event_count > 0 and "signals" not in stale_components:
        stale_components.append("signals")
    stale_versions = set(model_versions["stale_version_components"])
    signal_state = (
        "stale_version"
        if "signal" in stale_versions
        else ("pending" if "signals" in stale_components else ("current" if signal_built_at else "unknown"))
    )
    profile_state = (
        "stale_version"
        if "profile" in stale_versions
        else ("pending" if "profile" in stale_components else ("current" if profile_built_at else "unknown"))
    )
    cf_source_signal_built_at = _derivation_text_from_docs(cf_status_docs, "source_signal_built_at")
    cf_input_policy = next(
        (
            _derivation_text(edge, "input_policy")
            for edge in cf_status_docs
            if _derivation_text(edge, "input_policy")
        ),
        get_settings().cf_runtime_input_policy,
    )
    pending_cf_relevant = any(
        event.get("processed") is not True
        and str(event.get("event_type") or "").strip() in CF_RELEVANT_EVENT_TYPES
        for event in events
    )
    cf_behind_signals = bool(
        _parse_timestamp(signal_built_at)
        and (
            _parse_timestamp(cf_source_signal_built_at)
            or _parse_timestamp(cf_built_at)
        )
        and _parse_timestamp(signal_built_at)
        > (_parse_timestamp(cf_source_signal_built_at) or _parse_timestamp(cf_built_at))
    )
    if "cf" in stale_versions:
        cf_state = "stale_version"
    elif not cf_built_at:
        cf_state = "unavailable"
    elif pending_cf_relevant or cf_behind_signals:
        cf_state = "refresh_required"
        stale_components.append("cf")
    else:
        cf_state = "current"
    next_actions: list[str] = []
    if signal_state == "pending" or profile_state == "pending":
        next_actions.append("Apply pending behavior to refresh signals and profiles.")
    if cf_state == "refresh_required":
        next_actions.append("Schedule a full CF refresh after behavior processing.")
    if cf_state == "unavailable":
        next_actions.append("CF graph lineage is unavailable for this status check.")
    state = (
        "stale_version"
        if model_versions["stale_version_components"]
        else ("stale" if stale_components else ("current" if latest_event_at else "unknown"))
    )
    return {
        "state": state,
        "latest_event_at": latest_event_at,
        "signal_built_at": signal_built_at,
        "profile_built_at": profile_built_at,
        "cf_built_at": cf_built_at,
        "pending_event_count": pending_event_count,
        "stale_components": stale_components,
        "model_versions": model_versions,
        "components": {
            "signals": {
                "state": signal_state,
                "built_at": signal_built_at,
                "source_event_max_timestamp": _derivation_text_from_docs(signals, "source_event_max_timestamp"),
            },
            "profile": {
                "state": profile_state,
                "built_at": profile_built_at,
                "source_signal_built_at": _derivation_text(profile_doc, "source_signal_built_at"),
            },
            "cf": {
                "state": cf_state,
                "built_at": cf_built_at,
                "source_signal_built_at": cf_source_signal_built_at,
                "input_policy": cf_input_policy,
            },
        },
        "next_actions": next_actions,
    }


@router.get("/debug/user/{user_id}")
def get_debug_user(user_id: str) -> dict[str, Any]:
    user_doc = get_users_collection().find_one({"user_id_hash": user_id}, {"_id": 0})
    profile_doc = get_user_profiles_collection().find_one({"user_id_hash": user_id}, {"_id": 0})
    if not user_doc and not profile_doc:
        raise HTTPException(status_code=404, detail="user not found")

    user_item_signals_collection = get_user_item_signals_collection()
    signals = _safe_list(
        user_item_signals_collection.find({"user_id_hash": user_id}, {"_id": 0}).sort("implicit_score", -1),
        20,
    )
    signal_lineage_docs = _safe_list(
        user_item_signals_collection.find({"user_id_hash": user_id}, {"_id": 0}).sort("updated_at", -1),
        1,
    )
    logs = _safe_list(
        get_recommendation_logs_collection().find({"user_id_hash": user_id}, {"_id": 0}).sort("shown_at", -1),
        20,
    )
    clickstream_events_collection = get_clickstream_events_collection()
    events = _safe_list(
        clickstream_events_collection.find({"user_id_hash": user_id}, {"_id": 0}).sort("timestamp", -1),
        50,
    )
    pending_event_count = int(
        clickstream_events_collection.count_documents({"user_id_hash": user_id, "processed": {"$ne": True}})
    )

    cf_item_ids = [str(signal.get("item_id") or "") for signal in signals[:5] if str(signal.get("item_id") or "")]
    cf_edges: list[dict[str, Any]] = []
    if cf_item_ids:
        cf_edges = _safe_list(
            get_item_item_cf_edges_collection()
            .find({"item_id": {"$in": cf_item_ids}}, {"_id": 0})
            .sort("cf_score", -1),
            20,
        )
    cf_lineage_docs = _safe_list(
        get_item_item_cf_edges_collection().find({}, {"_id": 0, "derivation": 1, "updated_at": 1}).sort("updated_at", -1),
        1,
    )

    return {
        "user": user_doc,
        "profile": profile_doc,
        "signals": signals,
        "recent_logs": logs,
        "recent_events": events,
        "cf_edges": cf_edges,
        "freshness": _freshness_snapshot(
            profile_doc=profile_doc,
            signals=signals + signal_lineage_docs,
            events=events,
            cf_edges=cf_edges,
            pending_event_count=pending_event_count,
            cf_lineage_docs=cf_lineage_docs,
        ),
    }


@router.post("/demo/seed")
def seed_demo_behavior(
    users: int = 40,
    requests_per_user: int = 3,
    items_per_request: int = 10,
    seed: int = 42,
    write: bool = False,
) -> dict[str, Any]:
    candidates = load_candidates_from_collections(
        items_collection=get_items_collection(),
        item_hype_profiles_collection=get_item_hype_profiles_collection(),
    )
    plan = build_synthetic_behavior_plan(
        candidates=candidates,
        users=users,
        requests_per_user=requests_per_user,
        items_per_request=items_per_request,
        seed=seed,
    )
    result: dict[str, Any] = {
        "mode": "write" if write else "dry-run",
        "summary": plan["summary"],
        "samples": plan["samples"],
    }
    if write:
        result["write_result"] = write_synthetic_behavior_plan(
            plan=plan,
            synthetic_personas_collection=get_synthetic_personas_collection(),
            recommendation_logs_collection=get_recommendation_logs_collection(),
            clickstream_events_collection=get_clickstream_events_collection(),
        )
    return result


@router.get("/demo/status")
def get_demo_status() -> dict[str, Any]:
    counts = {
        "users": _collection_count(get_users_collection),
        "recommendation_logs": _collection_count(get_recommendation_logs_collection),
        "clickstream_events": _collection_count(get_clickstream_events_collection),
        "user_item_signals": _collection_count(get_user_item_signals_collection),
        "user_profiles": _collection_count(get_user_profiles_collection),
        "item_stats": _collection_count(get_item_stats_collection),
        "item_item_cf_edges": _collection_count(get_item_item_cf_edges_collection),
        "item_hype_profiles": _collection_count(get_item_hype_profiles_collection),
        "item_semantic_neighbors": _collection_count(get_item_semantic_neighbors_collection),
        "synthetic_personas": _collection_count(get_synthetic_personas_collection),
    }
    return {
        "ok": True,
        "protected_collections": sorted(CATALOG_COLLECTIONS),
        "counts": counts,
        "model_versions": configured_model_versions(get_settings()),
        "cf_evidence_available": counts["item_item_cf_edges"] > 0,
        "precomputed_cf_note": (
            "Existing item_item_cf_edges may come from seeded/precomputed synthetic behavior. "
            "Use full reset + rebuild to replay the complete event -> signal -> profile -> CF pipeline."
        ),
    }


@router.post("/demo/reset")
def reset_demo_behavior(write: bool = False, full: bool = False, confirm: str | None = None) -> dict[str, Any]:
    _require_reset_confirmation(write=write, full=full, confirm=confirm)
    try:
        result = execute_reset(get_database(), full=full, write=write, confirm=confirm)
    except RuntimeError as exc:
        expected = "FULL_DEMO_RESET" if full else "DEMO_RESET"
        raise HTTPException(
            status_code=400,
            detail={
                "error": "confirmation_required",
                "message": str(exc),
                "expected_confirm": expected,
            },
        ) from exc
    if write:
        clear_catalog_snapshot_cache()
    return result


@router.post("/debug/process-events")
def process_events(limit: int | None = None, rebuild_item_stats: bool = True, write: bool = False) -> dict[str, Any]:
    clickstream_events_collection = get_clickstream_events_collection()
    if write and limit is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "partial_signal_write_blocked",
                "message": "Writing full signals with a limit is unsafe because new events can arrive during rebuild.",
                "limit_events": limit,
            },
        )
    result = build_user_item_signals(
        clickstream_events_collection=clickstream_events_collection,
        recommendation_logs_collection=get_recommendation_logs_collection(),
        user_item_signals_collection=get_user_item_signals_collection() if write else None,
        item_stats_collection=get_item_stats_collection() if write and rebuild_item_stats else None,
        write=write,
        rebuild_item_stats=rebuild_item_stats,
        limit_events=limit,
    )
    if write and rebuild_item_stats and result.get("ok"):
        clear_catalog_snapshot_cache()
    return result


@router.post("/debug/apply-pending-behavior")
def apply_pending_behavior(
    max_events: int = 100,
    rebuild_item_stats: bool = True,
    write: bool = False,
) -> dict[str, Any]:
    try:
        result = process_pending_behavior(
            clickstream_events_collection=get_clickstream_events_collection(),
            recommendation_logs_collection=get_recommendation_logs_collection(),
            user_item_signals_collection=get_user_item_signals_collection() if write else None,
            item_stats_collection=get_item_stats_collection() if write and rebuild_item_stats else None,
            user_profiles_collection=get_user_profiles_collection() if write else None,
            item_hype_profiles_collection=get_item_hype_profiles_collection() if write else None,
            items_collection=get_items_collection() if write else None,
            retrieval_units_collection=get_retrieval_units_collection() if write else None,
            write=write,
            rebuild_item_stats=rebuild_item_stats,
            max_events=max_events,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if write and rebuild_item_stats and result.get("ok"):
        clear_catalog_snapshot_cache()
    return result


@router.post("/debug/rebuild-profiles")
def rebuild_profiles(limit_users: int | None = None, write: bool = False) -> dict[str, Any]:
    if write and limit_users is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "partial_profile_write_blocked",
                "message": "Writing profiles for a limited user subset would leave mixed derived state.",
                "limit_users": limit_users,
            },
        )
    return build_user_profiles(
        user_item_signals_collection=get_user_item_signals_collection(),
        clickstream_events_collection=get_clickstream_events_collection(),
        recommendation_logs_collection=get_recommendation_logs_collection(),
        item_hype_profiles_collection=get_item_hype_profiles_collection(),
        items_collection=get_items_collection(),
        retrieval_units_collection=get_retrieval_units_collection(),
        user_profiles_collection=get_user_profiles_collection() if write else None,
        write=write,
        limit_users=limit_users,
    )


@router.post("/debug/rebuild-cf")
def rebuild_cf(
    limit_users: int | None = None,
    min_support: int = 2,
    max_items_per_user: int = 30,
    top_neighbors_per_item: int = 50,
    input_policy: str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    if write and limit_users is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "partial_cf_write_blocked",
                "message": "Writing CF edges for a limited user subset would leave mixed derived state.",
                "limit_users": limit_users,
            },
        )
    try:
        return build_item_item_cf_edges(
            user_item_signals_collection=get_user_item_signals_collection(),
            items_collection=get_items_collection(),
            item_item_cf_edges_collection=get_item_item_cf_edges_collection() if write else None,
            write=write,
            limit_users=limit_users,
            min_support=min_support,
            max_items_per_user=max_items_per_user,
            top_neighbors_per_item=top_neighbors_per_item,
            input_policy=input_policy,
            replace_existing=bool(write and limit_users is None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
