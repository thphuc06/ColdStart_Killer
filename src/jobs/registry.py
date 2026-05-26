from __future__ import annotations

from .schemas import JobDefinition


_JOB_DEFINITIONS: tuple[JobDefinition, ...] = (
    JobDefinition(
        job_type="process_pending_behavior",
        label="Process pending behavior",
        description="Dry-run wrapper for pending behavior processing. Existing scripts remain the source of truth.",
        category="behavior",
        command="python scripts/process_pending_behavior.py --dry-run",
    ),
    JobDefinition(
        job_type="run_personalization_evaluation",
        label="Personalization evaluation dry-run",
        description="Runs or previews personalization evaluation without persisting evaluation_runs.",
        category="evaluation",
        command="python scripts/run_personalization_evaluation.py --dry-run --no-artifacts",
    ),
    JobDefinition(
        job_type="create_behavior_indexes_dry_run",
        label="Behavior index plan",
        description="Builds the MongoDB index plan without creating indexes.",
        category="maintenance",
        adapter="create_behavior_indexes_dry_run",
        command="python scripts/create_behavior_indexes.py --dry-run",
        triggerable_from_api=True,
    ),
    JobDefinition(
        job_type="reset_demo_behavior_soft_dry_run",
        label="Soft reset dry-run",
        description="Summarizes the protected collections and soft reset targets without deleting data.",
        category="maintenance",
        adapter="reset_demo_behavior_soft_dry_run",
        command="python scripts/reset_demo_behavior_data.py --soft --dry-run",
    ),
    JobDefinition(
        job_type="reset_demo_behavior_full_dry_run",
        label="Full reset dry-run",
        description="Summarizes the protected collections and full reset targets without deleting data.",
        category="maintenance",
        adapter="reset_demo_behavior_full_dry_run",
        command="python scripts/reset_demo_behavior_data.py --full --dry-run",
    ),
    JobDefinition(
        job_type="seller_draft_index_preview",
        label="Seller draft indexing preview",
        description="Tracks seller draft index-preview workflow. Catalog writes stay behind seller confirmation.",
        category="seller",
        command="POST /api/seller/drafts/{draft_id}/index-preview",
    ),
    JobDefinition(
        job_type="web_enrichment_request_preview",
        label="Web enrichment preview",
        description="Tracks web enrichment preview workflow without applying seller field suggestions.",
        category="enrichment",
        command="POST /api/enrichment/seller-drafts/{draft_id}/preview",
    ),
    JobDefinition(
        job_type="fusion_comparison_dry_run",
        label="Fusion comparison dry-run",
        description="Compares or previews fusion strategy evaluation while keeping production search defaults unchanged.",
        category="evaluation",
        command="python scripts/compare_fusion_strategies.py --dry-run",
        triggerable_from_api=True,
    ),
    JobDefinition(
        job_type="run_evaluation_write",
        label="Persist evaluation run",
        description="Optional future/write job for evaluation_runs persistence. Not triggerable from the API in this batch.",
        category="evaluation",
        write_capable=True,
        confirmation_required="EVAL_RUN_WRITE",
        triggerable_from_api=False,
        command="python scripts/run_personalization_evaluation.py --write-evaluation-run --confirm EVAL_RUN_WRITE",
        current_status="manual_only",
    ),
    JobDefinition(
        job_type="seller_approve_index",
        label="Approve seller draft indexing",
        description="Optional write job that can add seller catalog items only through the seller approve-index endpoint.",
        category="seller",
        write_capable=True,
        confirmation_required="INDEX_SELLER_DRAFT",
        triggerable_from_api=False,
        command="POST /api/seller/drafts/{draft_id}/approve-index?write=true&confirm=INDEX_SELLER_DRAFT",
        current_status="manual_only",
    ),
    JobDefinition(
        job_type="web_enrichment_apply",
        label="Apply web enrichment",
        description="Optional write job that applies selected enrichment suggestions only to seller draft fields.",
        category="enrichment",
        write_capable=True,
        confirmation_required="APPLY_WEB_ENRICHMENT",
        triggerable_from_api=False,
        command="POST /api/enrichment/requests/{request_id}/apply?confirm=APPLY_WEB_ENRICHMENT",
        current_status="manual_only",
    ),
)


def get_job_registry() -> list[JobDefinition]:
    job_types = [job.job_type for job in _JOB_DEFINITIONS]
    if len(job_types) != len(set(job_types)):
        raise RuntimeError("Duplicate job_type values in job registry.")
    return list(_JOB_DEFINITIONS)


def get_job_definition(job_type: str) -> JobDefinition | None:
    normalized = str(job_type or "").strip()
    return next((job for job in get_job_registry() if job.job_type == normalized), None)


def get_job_registry_payload() -> list[dict[str, object]]:
    return [job.to_dict() for job in get_job_registry()]
