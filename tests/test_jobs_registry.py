from __future__ import annotations

from src.jobs.registry import get_job_definition, get_job_registry


def test_registry_contains_expected_job_types() -> None:
    job_types = {job.job_type for job in get_job_registry()}
    assert "process_pending_behavior" in job_types
    assert "run_personalization_evaluation" in job_types
    assert "create_behavior_indexes_dry_run" in job_types
    assert "reset_demo_behavior_soft_dry_run" in job_types
    assert "reset_demo_behavior_full_dry_run" in job_types
    assert "seller_draft_index_preview" in job_types
    assert "web_enrichment_request_preview" in job_types
    assert "fusion_comparison_dry_run" in job_types


def test_registry_has_no_duplicate_job_types() -> None:
    job_types = [job.job_type for job in get_job_registry()]
    assert len(job_types) == len(set(job_types))


def test_registry_entries_are_dry_run_first() -> None:
    for job in get_job_registry():
        assert job.dry_run_default is True


def test_write_capable_jobs_have_confirmation_and_are_not_api_triggerable() -> None:
    write_jobs = [job for job in get_job_registry() if job.write_capable]
    assert write_jobs
    for job in write_jobs:
        assert job.confirmation_required
        assert job.triggerable_from_api is False


def test_get_job_definition_does_not_execute_job() -> None:
    job = get_job_definition("fusion_comparison_dry_run")
    assert job is not None
    assert job.command == "python scripts/compare_fusion_strategies.py --dry-run"
