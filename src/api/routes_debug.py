from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from scripts.reset_demo_behavior_data import CATALOG_COLLECTIONS, execute_reset
from src.behavior.profile_builder import build_user_profiles
from src.behavior.signal_builder import build_user_item_signals
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
    events = _safe_list(
        get_clickstream_events_collection().find({"user_id_hash": user_id}, {"_id": 0}).sort("timestamp", -1),
        50,
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
    return result


@router.post("/debug/process-events")
def process_events(limit: int = 500, rebuild_item_stats: bool = True, write: bool = False) -> dict[str, Any]:
    result = build_user_item_signals(
        clickstream_events_collection=get_clickstream_events_collection(),
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
