from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.cache.keys import make_cache_key
from src.cache.service import get_cache_backend, get_or_compute
from src.config import get_settings
from src.jobs.registry import get_job_definition, get_job_registry_payload
from src.jobs.runner import JobRejectedError, run_registered_job, sanitize_job_params
from src.jobs.schemas import JobRunRequest
from src.mongodb import get_job_runs_collection

from .request_guards import require_admin_token


router = APIRouter(prefix="/api/jobs", dependencies=[Depends(require_admin_token)])


def _string_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def sanitize_job_run_document(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(doc, dict):
        return None
    return {
        "id": _string_id(doc.get("_id")),
        "job_run_id": str(doc.get("job_run_id") or ""),
        "job_type": str(doc.get("job_type") or ""),
        "status": str(doc.get("status") or "unknown"),
        "dry_run": bool(doc.get("dry_run", True)),
        "write_requested": bool(doc.get("write_requested", False)),
        "confirm": "provided" if doc.get("confirm") else None,
        "params": sanitize_job_params(doc.get("params") if isinstance(doc.get("params"), dict) else {}),
        "summary": sanitize_job_params(doc.get("summary") if isinstance(doc.get("summary"), dict) else {}),
        "error": sanitize_job_params(doc.get("error")) if doc.get("error") else None,
        "started_at": str(doc.get("started_at") or "") or None,
        "finished_at": str(doc.get("finished_at") or "") or None,
        "created_at": str(doc.get("created_at") or ""),
        "created_by": str(doc.get("created_by") or "unknown"),
        "source": str(doc.get("source") or "jobs_v1"),
        "version": str(doc.get("version") or "job_registry_v1"),
    }


def _newest_cursor(collection: Any, limit: int):
    cursor = collection.find({})
    if hasattr(cursor, "sort"):
        cursor = cursor.sort("created_at", -1)
    if hasattr(cursor, "limit"):
        cursor = cursor.limit(limit)
    return cursor


def _jobs_registry_cache_ttl() -> int:
    return max(1, min(get_settings().cache_default_ttl_seconds, 600))


def _jobs_runs_cache_ttl() -> int:
    return max(1, min(get_settings().cache_default_ttl_seconds, 30))


@router.get("/registry")
def get_jobs_registry() -> dict[str, Any]:
    settings = get_settings()
    key = make_cache_key(
        "jobs",
        {
            "registry": True,
            "enabled": settings.enable_job_runs,
            "trigger_api_enabled": settings.enable_job_trigger_api,
        },
        version=settings.cache_key_version,
    )

    def compute() -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": settings.enable_job_runs,
            "trigger_api_enabled": settings.enable_job_trigger_api,
            "jobs": get_job_registry_payload(),
        }

    return get_or_compute(cache=get_cache_backend(), key=key, ttl_seconds=_jobs_registry_cache_ttl(), compute_fn=compute)


@router.get("/runs")
def list_job_runs(limit: int = Query(20, ge=1)) -> dict[str, Any]:
    settings = get_settings()
    capped_limit = min(int(limit), settings.job_run_max_history)
    key = make_cache_key(
        "jobs",
        {"runs_limit": capped_limit, "enabled": settings.enable_job_runs},
        version=settings.cache_key_version,
    )

    def compute() -> dict[str, Any]:
        if not settings.enable_job_runs:
            return {"ok": True, "enabled": False, "empty": True, "runs": [], "limit": capped_limit}
        collection = get_job_runs_collection()
        runs = [
            sanitized
            for sanitized in (sanitize_job_run_document(doc) for doc in _newest_cursor(collection, capped_limit))
            if sanitized is not None
        ]
        return {"ok": True, "enabled": True, "empty": len(runs) == 0, "runs": runs, "limit": capped_limit}

    return get_or_compute(cache=get_cache_backend(), key=key, ttl_seconds=_jobs_runs_cache_ttl(), compute_fn=compute)


@router.get("/runs/{job_run_id}")
def get_job_run(job_run_id: str) -> dict[str, Any]:
    settings = get_settings()
    key = make_cache_key(
        "jobs",
        {"job_run_id": job_run_id, "enabled": settings.enable_job_runs},
        version=settings.cache_key_version,
    )

    def compute() -> dict[str, Any]:
        if not settings.enable_job_runs:
            return {"ok": True, "enabled": False, "run": None}
        collection = get_job_runs_collection()
        doc = collection.find_one({"job_run_id": job_run_id})
        sanitized = sanitize_job_run_document(doc)
        if sanitized is None:
            raise HTTPException(status_code=404, detail={"error": "not_found", "job_run_id": job_run_id})
        return {"ok": True, "enabled": True, "run": sanitized}

    return get_or_compute(cache=get_cache_backend(), key=key, ttl_seconds=_jobs_runs_cache_ttl(), compute_fn=compute)


@router.post("/run")
def run_job(request: JobRunRequest) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_job_trigger_api:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "job_trigger_api_disabled",
                "message": "Job trigger API is disabled by default. Use CLI dry-runs or enable explicitly for local admin use.",
            },
        )
    definition = get_job_definition(request.job_type)
    if definition is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_job_type", "job_type": request.job_type})
    if request.write:
        raise HTTPException(
            status_code=400,
            detail={"error": "write_jobs_disabled_from_api", "job_type": request.job_type},
        )
    collection = get_job_runs_collection() if settings.enable_job_runs else None
    try:
        run = run_registered_job(
            request.job_type,
            params=request.params,
            dry_run=request.dry_run,
            write=request.write,
            confirm=request.confirm,
            collection=collection,
            created_by="debug_admin",
            track=settings.enable_job_runs,
            allow_non_triggerable=False,
            api_trigger=True,
            global_confirmation=settings.job_run_confirmation,
        )
    except JobRejectedError as exc:
        raise HTTPException(status_code=400, detail={"error": "job_rejected", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": "job_failed", "message": str(sanitize_job_params(str(exc)))}) from exc
    get_cache_backend().clear_namespace("jobs")
    return {"ok": True, "run": sanitize_job_run_document(run)}
