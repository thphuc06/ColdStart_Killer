from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .adapters import get_adapter_for_job
from .registry import get_job_definition


SENSITIVE_KEY_PARTS = ("password", "secret", "token", "uri", "api_key", "apikey", "key")
MAX_STRING_LENGTH = 500
MAX_LIST_ITEMS = 20
MAX_DICT_ITEMS = 50
JOB_REGISTRY_VERSION = "job_registry_v1"
SECRET_ASSIGNMENT_RE = re.compile(r"(?i)(password|secret|token|api_key|apikey|mongodb_uri|uri)\s*=\s*[^,\s]+")


class JobRejectedError(ValueError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def sanitize_job_params(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DICT_ITEMS:
                sanitized["__truncated__"] = True
                break
            sanitized[str(key)] = "[redacted]" if _is_sensitive_key(str(key)) else sanitize_job_params(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        output = [sanitize_job_params(item) for item in list(value)[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            output.append({"__truncated__": True})
        return output
    if isinstance(value, str):
        redacted = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", value)
        return redacted if len(redacted) <= MAX_STRING_LENGTH else f"{redacted[:MAX_STRING_LENGTH]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _compact_summary(summary: Any) -> dict[str, Any]:
    if isinstance(summary, dict):
        return sanitize_job_params(summary)
    return {"value": sanitize_job_params(summary)}


def build_job_run_document(
    *,
    job_type: str,
    dry_run: bool,
    write_requested: bool,
    params: dict[str, Any] | None = None,
    confirm: str | None = None,
    created_by: str = "system",
) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "job_run_id": f"jobrun_{uuid.uuid4().hex}",
        "job_type": job_type,
        "status": "queued",
        "dry_run": bool(dry_run),
        "write_requested": bool(write_requested),
        "confirm": "provided" if confirm else None,
        "params": sanitize_job_params(params or {}),
        "summary": {},
        "error": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now,
        "created_by": created_by,
        "source": "jobs_v1",
        "version": JOB_REGISTRY_VERSION,
    }


def _update_job_run(collection: Any | None, job_run_id: str, fields: dict[str, Any]) -> None:
    if collection is None:
        return
    collection.update_one({"job_run_id": job_run_id}, {"$set": fields})


def _validate_run_request(
    *,
    job_type: str,
    dry_run: bool,
    write: bool,
    confirm: str | None,
    allow_non_triggerable: bool,
    api_trigger: bool,
    global_confirmation: str | None,
) -> None:
    definition = get_job_definition(job_type)
    if definition is None:
        raise JobRejectedError(f"Unknown job_type: {job_type}")
    if api_trigger and not definition.triggerable_from_api:
        raise JobRejectedError(f"Job is not triggerable from API: {job_type}")
    if not allow_non_triggerable and not definition.triggerable_from_api:
        raise JobRejectedError(f"Job is manual-only: {job_type}")
    if write:
        if not definition.write_capable:
            raise JobRejectedError(f"Job is not write-capable: {job_type}")
        expected = definition.confirmation_required or global_confirmation
        if not expected or confirm != expected:
            raise JobRejectedError(f"Confirmation required for {job_type}.")
    if not dry_run and not write:
        raise JobRejectedError("Non-dry-run jobs must explicitly request write.")


def run_registered_job(
    job_type: str,
    *,
    params: dict[str, Any] | None = None,
    dry_run: bool = True,
    write: bool = False,
    confirm: str | None = None,
    collection: Any | None = None,
    adapter_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    created_by: str = "system",
    track: bool = True,
    allow_non_triggerable: bool = True,
    api_trigger: bool = False,
    global_confirmation: str | None = None,
) -> dict[str, Any]:
    run_params = copy.deepcopy(params or {})
    _validate_run_request(
        job_type=job_type,
        dry_run=dry_run,
        write=write,
        confirm=confirm,
        allow_non_triggerable=allow_non_triggerable,
        api_trigger=api_trigger,
        global_confirmation=global_confirmation,
    )
    document = build_job_run_document(
        job_type=job_type,
        dry_run=dry_run,
        write_requested=write,
        params=run_params,
        confirm=confirm,
        created_by=created_by,
    )
    tracking_collection = collection if track else None
    if tracking_collection is not None:
        tracking_collection.insert_one(copy.deepcopy(document))
    started_at = utc_now_iso()
    document.update({"status": "running", "started_at": started_at})
    _update_job_run(tracking_collection, document["job_run_id"], {"status": "running", "started_at": started_at})
    try:
        adapter = adapter_fn or get_adapter_for_job(job_type)
        summary = _compact_summary(adapter(run_params))
        finished_at = utc_now_iso()
        status = "dry_run_completed" if dry_run else "succeeded"
        document.update({"status": status, "summary": summary, "finished_at": finished_at})
        _update_job_run(
            tracking_collection,
            document["job_run_id"],
            {"status": status, "summary": summary, "finished_at": finished_at},
        )
        return document
    except Exception as exc:
        finished_at = utc_now_iso()
        error = sanitize_job_params(str(exc))
        document.update({"status": "failed", "error": error, "finished_at": finished_at})
        _update_job_run(
            tracking_collection,
            document["job_run_id"],
            {"status": "failed", "error": error, "finished_at": finished_at},
        )
        raise
