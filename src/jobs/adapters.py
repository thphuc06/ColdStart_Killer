from __future__ import annotations

from typing import Any, Callable

from scripts.create_behavior_indexes import build_plan
from scripts.reset_demo_behavior_data import CATALOG_COLLECTIONS, build_reset_targets, rebuild_order_for_reset

from .registry import get_job_definition


JobAdapter = Callable[[dict[str, Any]], dict[str, Any]]


def _manual_command_summary(job_type: str, params: dict[str, Any]) -> dict[str, Any]:
    definition = get_job_definition(job_type)
    return {
        "adapter_mode": "manual_command",
        "executed": False,
        "command": definition.command if definition else None,
        "message": "This registry entry documents a safe dry-run command. Run the script directly for full live dry-run output.",
        "params": params,
    }


def create_behavior_indexes_dry_run(params: dict[str, Any]) -> dict[str, Any]:
    event_ttl_days = int(params.get("event_ttl_days") or 0)
    plan = build_plan(event_ttl_days=event_ttl_days)
    return {
        "adapter_mode": "in_process_dry_run",
        "executed": True,
        "mode": "dry-run",
        "collections": plan["collections"],
        "index_count": len(plan["indexes"]),
        "ttl_enabled": plan["ttl_enabled"],
    }


def reset_demo_behavior_dry_run(reset_mode: str) -> JobAdapter:
    def adapter(params: dict[str, Any]) -> dict[str, Any]:
        full = reset_mode == "full"
        return {
            "adapter_mode": "metadata_dry_run",
            "executed": False,
            "mode": reset_mode,
            "protected_collections": list(CATALOG_COLLECTIONS),
            "target_collections": [target.collection for target in build_reset_targets(full=full)],
            "rebuild_order": rebuild_order_for_reset(full=full),
            "message": "No delete/drop operations were executed. Run reset_demo_behavior_data.py dry-run for live counts.",
            "params": params,
        }

    return adapter


def fusion_comparison_dry_run(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "adapter_mode": "manual_command",
        "executed": False,
        "command": "python scripts/compare_fusion_strategies.py --dry-run",
        "message": "Fusion comparison can perform live read/search work. This registry dry-run records the safe command without running it automatically.",
        "params": params,
    }


_ADAPTERS: dict[str, JobAdapter] = {
    "create_behavior_indexes_dry_run": create_behavior_indexes_dry_run,
    "reset_demo_behavior_soft_dry_run": reset_demo_behavior_dry_run("soft"),
    "reset_demo_behavior_full_dry_run": reset_demo_behavior_dry_run("full"),
    "fusion_comparison_dry_run": fusion_comparison_dry_run,
}


def get_adapter_for_job(job_type: str) -> JobAdapter:
    return _ADAPTERS.get(job_type, lambda params: _manual_command_summary(job_type, params))
