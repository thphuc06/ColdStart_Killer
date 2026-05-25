from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.mongodb import get_evaluation_runs_collection


router = APIRouter(prefix="/api/evaluation")

MAX_EVALUATION_RUN_LIMIT = 50
EVALUATION_EMPTY_MESSAGE = (
    "No persisted evaluation runs yet. Run "
    "scripts/run_personalization_evaluation.py --write-evaluation-run --confirm EVAL_RUN_WRITE "
    "after human approval."
)

RAW_HEAVY_FIELDS = {
    "per_user_metrics",
    "raw_events",
    "events",
    "user_histories",
    "clickstream_events",
    "recommendation_logs",
}


def _string_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def sanitize_evaluation_run_document(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(doc, dict):
        return None
    compact = {key: value for key, value in doc.items() if key not in RAW_HEAVY_FIELDS and not key.startswith("_raw")}
    artifacts = compact.get("artifacts") if isinstance(compact.get("artifacts"), dict) else {}
    sanitized = {
        "id": _string_id(compact.get("_id")),
        "run_id": str(compact.get("run_id") or ""),
        "run_type": str(compact.get("run_type") or "personalization_eval"),
        "algorithm_version": str(compact.get("algorithm_version") or "unknown"),
        "ranking_version": str(compact.get("ranking_version") or "unknown"),
        "data_label": str(compact.get("data_label") or "synthetic_demo"),
        "synthetic_data": bool(compact.get("synthetic_data", True)),
        "metrics": compact.get("metrics") if isinstance(compact.get("metrics"), dict) else {},
        "baseline_summaries": compact.get("baseline_summaries")
        if isinstance(compact.get("baseline_summaries"), list)
        else [],
        "comparisons": compact.get("comparisons") if isinstance(compact.get("comparisons"), list) else [],
        "live_state_counts": compact.get("live_state_counts") if isinstance(compact.get("live_state_counts"), dict) else {},
        "caveat": str(compact.get("caveat") or "Synthetic/demo behavior data, not production traffic."),
        "evaluated_user_count": int(compact.get("evaluated_user_count") or 0),
        "artifacts": {
            "written": bool(artifacts.get("written", False)),
            "path": artifacts.get("path"),
        },
        "created_at": str(compact.get("created_at") or ""),
    }
    if not sanitized["run_id"]:
        sanitized["run_id"] = sanitized["id"] or "unknown"
    return sanitized


def _newest_cursor(collection: Any, limit: int):
    cursor = collection.find({})
    if hasattr(cursor, "sort"):
        cursor = cursor.sort("created_at", -1)
    if hasattr(cursor, "limit"):
        cursor = cursor.limit(limit)
    return cursor


@router.get("/runs/latest")
def get_latest_evaluation_run() -> dict[str, Any]:
    collection = get_evaluation_runs_collection()
    doc = None
    cursor = _newest_cursor(collection, 1)
    for candidate in cursor:
        doc = candidate
        break
    latest = sanitize_evaluation_run_document(doc)
    if latest is None:
        return {"ok": True, "empty": True, "latest": None, "message": EVALUATION_EMPTY_MESSAGE}
    return {"ok": True, "empty": False, "latest": latest}


@router.get("/runs")
def list_evaluation_runs(limit: int = Query(10, ge=1)) -> dict[str, Any]:
    capped_limit = min(int(limit), MAX_EVALUATION_RUN_LIMIT)
    collection = get_evaluation_runs_collection()
    runs = [
        sanitized
        for sanitized in (
            sanitize_evaluation_run_document(doc)
            for doc in _newest_cursor(collection, capped_limit)
        )
        if sanitized is not None
    ]
    return {
        "ok": True,
        "empty": len(runs) == 0,
        "runs": runs,
        "limit": capped_limit,
        "message": EVALUATION_EMPTY_MESSAGE if not runs else None,
    }


@router.get("/runs/{run_id}")
def get_evaluation_run(run_id: str) -> dict[str, Any]:
    collection = get_evaluation_runs_collection()
    doc = collection.find_one({"run_id": run_id})
    sanitized = sanitize_evaluation_run_document(doc)
    if sanitized is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "run_id": run_id})
    return {"ok": True, "run": sanitized}
