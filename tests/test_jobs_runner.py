from __future__ import annotations

import pytest

from src.jobs.runner import JobRejectedError, build_job_run_document, run_registered_job, sanitize_job_params


class FakeJobRunsCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []
        self.updates: list[tuple[dict, dict]] = []

    def insert_one(self, doc):
        self.docs.append(doc)

    def update_one(self, query, update):
        self.updates.append((query, update))
        for doc in self.docs:
            if doc["job_run_id"] == query["job_run_id"]:
                doc.update(update.get("$set", {}))
                break


def test_build_job_run_document_shape_sanitizes_params() -> None:
    doc = build_job_run_document(
        job_type="fusion_comparison_dry_run",
        dry_run=True,
        write_requested=False,
        params={"query": "coffee maker", "api_key": "secret-value"},
        created_by="test",
    )
    assert doc["job_run_id"].startswith("jobrun_")
    assert doc["status"] == "queued"
    assert doc["dry_run"] is True
    assert doc["params"]["api_key"] == "[redacted]"
    assert doc["source"] == "jobs_v1"


def test_dry_run_job_succeeds_with_fake_adapter() -> None:
    collection = FakeJobRunsCollection()
    run = run_registered_job(
        "fusion_comparison_dry_run",
        params={"queries": ["sunscreen"]},
        collection=collection,
        adapter_fn=lambda params: {"received": params, "token": "hidden"},
        created_by="test",
    )
    assert run["status"] == "dry_run_completed"
    assert run["summary"]["received"]["queries"] == ["sunscreen"]
    assert run["summary"]["token"] == "[redacted]"
    assert len(collection.docs) == 1
    assert collection.updates[-1][1]["$set"]["status"] == "dry_run_completed"


def test_failing_job_marks_failed_and_sanitizes_error() -> None:
    collection = FakeJobRunsCollection()

    def failing_adapter(_params):
        raise RuntimeError("failed with token=abc123")

    with pytest.raises(RuntimeError):
        run_registered_job(
            "fusion_comparison_dry_run",
            collection=collection,
            adapter_fn=failing_adapter,
            created_by="test",
        )
    assert collection.docs[0]["status"] == "failed"
    assert "abc123" not in collection.docs[0]["error"]
    assert "token=[redacted]" in collection.docs[0]["error"]


def test_write_job_without_confirmation_is_rejected_before_insert() -> None:
    collection = FakeJobRunsCollection()
    with pytest.raises(JobRejectedError):
        run_registered_job("run_evaluation_write", write=True, dry_run=False, collection=collection)
    assert collection.docs == []


def test_write_job_wrong_confirmation_is_rejected() -> None:
    with pytest.raises(JobRejectedError):
        run_registered_job(
            "run_evaluation_write",
            write=True,
            dry_run=False,
            confirm="WRONG",
            collection=FakeJobRunsCollection(),
        )


def test_params_sanitizer_redacts_nested_secrets() -> None:
    sanitized = sanitize_job_params(
        {
            "nested": {"MONGODB_URI": "mongodb+srv://secret", "safe": "ok"},
            "items": [{"password": "hidden"}],
        }
    )
    assert sanitized["nested"]["MONGODB_URI"] == "[redacted]"
    assert sanitized["nested"]["safe"] == "ok"
    assert sanitized["items"][0]["password"] == "[redacted]"


def test_manual_only_job_rejected_when_non_triggerable_not_allowed() -> None:
    with pytest.raises(JobRejectedError):
        run_registered_job(
            "process_pending_behavior",
            collection=FakeJobRunsCollection(),
            allow_non_triggerable=False,
            api_trigger=True,
        )
