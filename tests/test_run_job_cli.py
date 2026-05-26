from __future__ import annotations

from types import SimpleNamespace

from scripts.run_job import parse_args
import scripts.run_job as run_job_module


def test_parse_args_defaults_to_dry_run() -> None:
    args = parse_args(["--job", "fusion_comparison_dry_run"])

    assert args.dry_run is True


def test_parse_args_can_disable_dry_run_for_live_write_request() -> None:
    args = parse_args(["--job", "run_evaluation_write", "--write", "--no-dry-run", "--confirm", "EVAL_RUN_WRITE"])

    assert args.write is True
    assert args.dry_run is False
    assert args.confirm == "EVAL_RUN_WRITE"


def test_main_forwards_no_dry_run_flag_to_runner(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_registered_job(job_type: str, **kwargs):
        captured["job_type"] = job_type
        captured.update(kwargs)
        return {"job_run_id": "jobrun_1", "status": "succeeded"}

    monkeypatch.setattr(run_job_module, "get_settings", lambda: SimpleNamespace(job_run_confirmation="CONFIRM"))
    monkeypatch.setattr(run_job_module, "run_registered_job", fake_run_registered_job)

    exit_code = run_job_module.main([
        "--job",
        "run_evaluation_write",
        "--write",
        "--no-dry-run",
        "--confirm",
        "CONFIRM",
    ])

    assert exit_code == 0
    assert captured["job_type"] == "run_evaluation_write"
    assert captured["write"] is True
    assert captured["dry_run"] is False


def test_main_forwards_default_dry_run_flag_to_runner(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_registered_job(job_type: str, **kwargs):
        captured["job_type"] = job_type
        captured.update(kwargs)
        return {"job_run_id": "jobrun_2", "status": "dry_run_completed"}

    monkeypatch.setattr(run_job_module, "get_settings", lambda: SimpleNamespace(job_run_confirmation="CONFIRM"))
    monkeypatch.setattr(run_job_module, "run_registered_job", fake_run_registered_job)

    exit_code = run_job_module.main(["--job", "fusion_comparison_dry_run"])

    assert exit_code == 0
    assert captured["job_type"] == "fusion_comparison_dry_run"
    assert captured["write"] is False
    assert captured["dry_run"] is True