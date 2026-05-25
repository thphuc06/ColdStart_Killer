from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from scripts.reset_demo_behavior_data import CATALOG_COLLECTIONS, execute_reset
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
) -> dict[str, Any]:
    latest_event_at = _latest_timestamp([event.get("timestamp") for event in events])
    signal_built_at = _latest_timestamp([signal.get("updated_at") for signal in signals])
    profile_built_at = str(profile_doc.get("updated_at") or "") or None if profile_doc else None
    cf_built_at = _latest_timestamp([edge.get("updated_at") for edge in cf_edges])
    model_versions = _model_versions_snapshot(profile_doc=profile_doc, signals=signals, cf_edges=cf_edges)
    latest_event_time = _parse_timestamp(latest_event_at)
    stale_components: list[str] = []
    for name, timestamp in (("signals", signal_built_at), ("profile", profile_built_at)):
        built_time = _parse_timestamp(timestamp)
        if latest_event_time and (built_time is None or built_time < latest_event_time):
            stale_components.append(name)
    if pending_event_count > 0 and "signals" not in stale_components:
        stale_components.append("signals")
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
    }


@router.get("/debug/user/{user_id}")
def get_debug_user(user_id: str) -> dict[str, Any]:
    user_doc = get_users_collection().find_one({"user_id_hash": user_id}, {"_id": 0})
    profile_doc = get_user_profiles_collection().find_one({"user_id_hash": user_id}, {"_id": 0})
    if not user_doc and not profile_doc:
        raise HTTPException(status_code=404, detail="user not found")

    signals = _safe_list(
        get_user_item_signals_collection().find({"user_id_hash": user_id}, {"_id": 0}).sort("implicit_score", -1),
        20,
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

    return {
        "user": user_doc,
        "profile": profile_doc,
        "signals": signals,
        "recent_logs": logs,
        "recent_events": events,
        "cf_edges": cf_edges,
        "freshness": _freshness_snapshot(
            profile_doc=profile_doc,
            signals=signals,
            events=events,
            cf_edges=cf_edges,
            pending_event_count=pending_event_count,
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
        total_events = int(clickstream_events_collection.count_documents({}))
        if limit < total_events:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "partial_signal_write_blocked",
                    "message": "Writing signals from a limited event subset would overwrite complete aggregates.",
                    "limit_events": limit,
                    "total_events": total_events,
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
    return build_item_item_cf_edges(
        user_item_signals_collection=get_user_item_signals_collection(),
        items_collection=get_items_collection(),
        item_item_cf_edges_collection=get_item_item_cf_edges_collection() if write else None,
        write=write,
        limit_users=limit_users,
        min_support=min_support,
        max_items_per_user=max_items_per_user,
        top_neighbors_per_item=top_neighbors_per_item,
        replace_existing=bool(write and limit_users is None),
    )
