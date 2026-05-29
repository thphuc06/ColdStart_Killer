from __future__ import annotations

import json

from scripts import run_personalization_evaluation as eval_script
from src.evaluation.personalization_eval import persist_evaluation_run


def _run_data() -> dict:
    return {
        "config": {
            "run_id": "unit_eval_run",
            "created_at": "2026-05-25T00:00:00+00:00",
            "algorithm_version": "algo_eval",
            "ranking_version": "rank_eval",
            "synthetic_data": True,
            "evaluation_data_mode": "synthetic_demo",
            "data_label": "synthetic/demo evaluation; metrics must be interpreted with explicit synthetic/demo caveats.",
            "user_count": 2,
            "event_count": 10,
            "evaluated_user_count": 2,
            "extra_metadata": {
                "live_state_counts": {
                    "items": 3000,
                    "clickstream_events": 10,
                    "user_profiles": 2,
                }
            },
        },
        "baseline_summaries": [
            {
                "baseline": "profile_plus_cf",
                "evaluated_user_count": 2,
                "hit_rate_at_10": 0.5,
                "recall_at_20": 0.4,
                "map_at_20": 0.3,
                "ndcg_at_20": 0.3,
                "mrr_at_10": 0.3,
                "deliberate_map_at_20": 0.2,
                "deliberate_ndcg_at_20": 0.2,
                "coverage": 0.2,
                "cold_start_exposure_at_20": 0.1,
                "cf_supported_recommendation_count": 3,
                "cf_supported_recommendation_rate": 0.15,
                "negative_reexposure_rate": 0.0,
            }
        ],
        "comparisons": [
            {
                "comparison": "profile_plus_cf_vs_profile_only",
                "hit_rate_at_10_delta": 0.1,
                "recall_at_20_delta": 0.1,
                "map_at_20_delta": 0.1,
                "ndcg_at_20_delta": 0.1,
                "cf_supported_count_delta": 1,
            }
        ],
        "cf_qualified_gate": {"decision": "needs_more_evidence"},
        "cf_diagnostics": {
            "min_support": 2,
            "current_directional_edge_count": 10,
            "qualified_directional_edge_count": 4,
            "current_build_stats": {"large": "not persisted in compact metrics"},
        },
        "cohort_diagnostics": {
            "evaluated_user_count": 2,
            "cold_start_user_count": 1,
            "sparse_user_count": 1,
            "deliberate_intent_user_count": 1,
            "negative_feedback_user_count": 0,
            "qualified_cf_source_user_count": 1,
        },
        "per_user_metrics": [{"user_id_hash": "u_should_not_be_persisted", "recommended_item_ids": ["A", "B"]}],
    }


class FakeInsertResult:
    inserted_id = "inserted_1"


class FakeCollection:
    def __init__(self) -> None:
        self.inserted: list[dict] = []

    def insert_one(self, doc: dict):
        self.inserted.append(dict(doc))
        return FakeInsertResult()


def test_persist_evaluation_run_writes_compact_caveated_document_to_fake_collection() -> None:
    collection = FakeCollection()

    result = persist_evaluation_run(_run_data(), evaluation_runs_collection=collection)

    assert result == {"ok": True, "inserted_id": "inserted_1", "run_id": "unit_eval_run"}
    assert len(collection.inserted) == 1
    doc = collection.inserted[0]
    assert doc["run_type"] == "personalization_eval"
    assert doc["algorithm_version"] == "algo_eval"
    assert doc["ranking_version"] == "rank_eval"
    assert doc["synthetic_data"] is True
    assert doc["evaluation_data_mode"] == "synthetic_demo"
    assert "Synthetic/demo behavior data" in doc["caveat"]
    assert doc["live_state_counts"]["items"] == 3000
    assert doc["metrics"]["baseline_count"] == 1
    assert doc["metrics"]["cohort_diagnostics"]["sparse_user_count"] == 1
    assert doc["artifacts"]["written"] is False
    assert "per_user_metrics" not in doc
    serialized = json.dumps(doc)
    assert "MONGODB_URI" not in serialized
    assert "mongodb+srv" not in serialized
    assert "u_should_not_be_persisted" not in serialized


def test_write_evaluation_run_requires_confirmation_before_loading_live_inputs(capsys) -> None:
    result = eval_script.main(["--write-evaluation-run"])

    captured = capsys.readouterr()
    assert result == 1
    assert "requires --confirm EVAL_RUN_WRITE" in captured.err


def test_write_evaluation_run_rejects_wrong_confirmation(capsys) -> None:
    result = eval_script.main(["--write-evaluation-run", "--confirm", "WRONG"])

    captured = capsys.readouterr()
    assert result == 1
    assert "requires --confirm EVAL_RUN_WRITE" in captured.err


def test_dry_run_cannot_be_combined_with_evaluation_run_write(capsys) -> None:
    result = eval_script.main(["--dry-run", "--write-evaluation-run", "--confirm", eval_script.EVALUATION_RUN_CONFIRMATION])

    captured = capsys.readouterr()
    assert result == 1
    assert "--dry-run cannot be combined with --write-evaluation-run" in captured.err


def test_cli_dry_run_does_not_call_persist(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        eval_script,
        "load_live_personalization_inputs",
        lambda: {
            "items": [],
            "clickstream_events": [],
            "recommendation_logs": [],
            "item_stats": [],
            "live_state_counts": {"items": 0},
        },
    )
    monkeypatch.setattr(eval_script, "evaluate_personalization", lambda **_kwargs: _run_data())

    def fail_persist(*_args, **_kwargs):
        raise AssertionError("persist_evaluation_run must not run during --dry-run")

    monkeypatch.setattr(eval_script, "persist_evaluation_run", fail_persist)

    result = eval_script.main(["--dry-run", "--no-artifacts"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Dry-run: evaluation_runs write skipped." in captured.out
    assert "artifacts: skipped" in captured.out


def test_cli_write_evaluation_run_with_confirmation_persists_without_artifacts_by_default(monkeypatch, capsys) -> None:
    persist_calls = []

    monkeypatch.setattr(
        eval_script,
        "load_live_personalization_inputs",
        lambda: {
            "items": [],
            "clickstream_events": [],
            "recommendation_logs": [],
            "item_stats": [],
            "live_state_counts": {"items": 0},
        },
    )
    monkeypatch.setattr(eval_script, "evaluate_personalization", lambda **_kwargs: _run_data())
    monkeypatch.setattr(
        eval_script,
        "persist_evaluation_run",
        lambda run_data, artifact_paths=None: persist_calls.append((run_data, artifact_paths))
        or {"ok": True, "inserted_id": "inserted_cli", "run_id": "unit_eval_run"},
    )

    result = eval_script.main(["--write-evaluation-run", "--confirm", eval_script.EVALUATION_RUN_CONFIRMATION])

    captured = capsys.readouterr()
    assert result == 0
    assert persist_calls[0][1] is None
    assert "evaluation_runs write: inserted run_id=unit_eval_run" in captured.out
    assert "artifacts: skipped" in captured.out
