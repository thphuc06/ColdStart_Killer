from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.personalization_eval import (
    PersonalizationEvalConfig,
    _build_cf_edges,
    _build_train_signals,
    _qualified_cf_gate,
    compute_ranking_metrics,
    evaluate_personalization,
    temporal_split_events,
    write_personalization_outputs,
)
from scripts.run_personalization_evaluation import _build_terminal_summary, _should_write_artifacts
from src.recommendation.item_item_cf import compute_item_item_cf_edges


BASE_TS = datetime(2026, 5, 24, 9, 0, tzinfo=UTC)


def _event(
    user_id_hash: str,
    item_id: str,
    event_type: str,
    minute_offset: int,
) -> dict:
    return {
        "event_id": f"evt_{user_id_hash}_{item_id}_{event_type}_{minute_offset}",
        "user_id_hash": user_id_hash,
        "item_id": item_id,
        "event_type": event_type,
        "timestamp": (BASE_TS + timedelta(minutes=minute_offset)).isoformat(),
    }


def _item(
    item_id: str,
    *,
    title: str,
    brand: str,
    category_id: str,
    cold: bool = False,
    price_bucket: str = "100k_300k",
) -> dict:
    return {
        "_id": item_id,
        "title_en": title,
        "brand": brand,
        "category_id": category_id,
        "price_bucket": price_bucket,
        "cold_start": {"is_cold_item": cold, "interaction_count": 0 if cold else 10},
    }


def test_temporal_split_events_uses_first_70_percent_for_training() -> None:
    events = [
        _event("u1", "A", "impression", 0),
        _event("u1", "A", "click", 1),
        _event("u1", "B", "impression", 2),
        _event("u1", "B", "click", 3),
        _event("u1", "C", "impression", 4),
        _event("u1", "C", "click", 5),
        _event("u1", "D", "impression", 6),
        _event("u1", "D", "click", 7),
        _event("u1", "E", "click", 8),
        _event("u1", "F", "impression", 9),
    ]

    split = temporal_split_events(events, train_ratio=0.7)

    assert len(split.train_events) == 7
    assert [event["item_id"] for event in split.train_events][-1] == "D"
    assert [event["item_id"] for event in split.held_out_events] == ["D", "E", "F"]
    assert split.train_positive_item_ids == ["A", "B", "C"]
    assert split.held_out_positive_item_ids == ["D", "E"]
    assert split.held_out_deliberate_item_ids == []


def test_compute_ranking_metrics_returns_expected_core_metrics() -> None:
    items_by_id = {
        "A": _item("A", title="Phone Case", brand="CaseCo", category_id="phones"),
        "B": _item("B", title="Charging Cable", brand="ChargeCo", category_id="phones"),
        "C": _item("C", title="Face Serum", brand="GlowCo", category_id="beauty"),
        "D": _item("D", title="Earbuds", brand="AudioCo", category_id="audio", cold=True),
    }

    metrics = compute_ranking_metrics(
        recommended_item_ids=["A", "B", "C", "D"],
        held_out_positive_item_ids=["B", "D"],
        items_by_id=items_by_id,
        popularity_by_item={"A": 10, "B": 1, "C": 5, "D": 0},
        cf_supported_item_ids={"D"},
        hit_rate_k=10,
        recall_k=20,
        map_k=20,
    )

    assert metrics["hit_rate_at_10"] == 1.0
    assert metrics["recall_at_20"] == 1.0
    assert metrics["map_at_20"] == 0.5
    assert metrics["ndcg_at_20"] > 0
    assert metrics["mrr_at_10"] == 0.5
    assert metrics["cold_start_exposure_at_20"] == 0.25
    assert metrics["cf_supported_recommendation_count"] == 1
    assert 0.0 < metrics["diversity_at_20"] <= 1.0
    assert 0.0 <= metrics["novelty_at_20"] <= 1.0


def test_compute_ranking_metrics_reports_negative_reexposure() -> None:
    metrics = compute_ranking_metrics(
        recommended_item_ids=["HIDDEN", "OK"],
        held_out_positive_item_ids=["OK"],
        items_by_id={
            "HIDDEN": _item("HIDDEN", title="Hidden", brand="B", category_id="c"),
            "OK": _item("OK", title="Okay", brand="B", category_id="c"),
        },
        negative_item_ids={"HIDDEN"},
    )

    assert metrics["negative_reexposure_count"] == 1
    assert metrics["negative_reexposure_rate"] == 0.5


def test_evaluate_personalization_compares_required_baselines_and_cf_lift() -> None:
    items = [
        _item("A1", title="Phone Case", brand="CaseCo", category_id="phones"),
        _item("A2", title="Charging Cable", brand="ChargeCo", category_id="phones"),
        _item("A3", title="Screen Protector", brand="CaseCo", category_id="phones"),
        _item("A4", title="Phone Stand", brand="StandCo", category_id="phones", cold=True),
        _item("B1", title="Face Serum", brand="GlowCo", category_id="beauty"),
        _item("B2", title="Gentle Cleanser", brand="PureCo", category_id="beauty"),
        _item("B3", title="Lipstick Gift", brand="GlowCo", category_id="beauty"),
    ]

    events = [
        _event("u_eval_phone", "A1", "impression", 0),
        _event("u_eval_phone", "A1", "click", 1),
        _event("u_eval_phone", "A3", "impression", 2),
        _event("u_eval_phone", "B1", "impression", 3),
        _event("u_eval_phone", "A2", "click", 4),
        _event("u_eval_phone", "A2", "add_to_cart", 5),
        _event("u_support_phone_1", "A1", "impression", 10),
        _event("u_support_phone_1", "A1", "click", 11),
        _event("u_support_phone_1", "A2", "impression", 12),
        _event("u_support_phone_1", "A2", "click", 13),
        _event("u_support_phone_1", "B1", "impression", 14),
        _event("u_support_phone_1", "B3", "impression", 15),
        _event("u_support_phone_2", "A1", "impression", 20),
        _event("u_support_phone_2", "A1", "click", 21),
        _event("u_support_phone_2", "A2", "impression", 22),
        _event("u_support_phone_2", "A2", "click", 23),
        _event("u_support_phone_2", "A4", "impression", 24),
        _event("u_support_phone_2", "B1", "impression", 25),
        _event("u_eval_beauty", "B1", "impression", 30),
        _event("u_eval_beauty", "B1", "click", 31),
        _event("u_eval_beauty", "B3", "impression", 32),
        _event("u_eval_beauty", "A1", "impression", 33),
        _event("u_eval_beauty", "B2", "click", 34),
        _event("u_eval_beauty", "B2", "add_to_cart", 35),
        _event("u_support_beauty_1", "B1", "impression", 40),
        _event("u_support_beauty_1", "B1", "click", 41),
        _event("u_support_beauty_1", "B2", "impression", 42),
        _event("u_support_beauty_1", "B2", "click", 43),
        _event("u_support_beauty_1", "A1", "impression", 44),
        _event("u_support_beauty_1", "A3", "impression", 45),
        _event("u_support_beauty_2", "B1", "impression", 50),
        _event("u_support_beauty_2", "B1", "click", 51),
        _event("u_support_beauty_2", "B2", "impression", 52),
        _event("u_support_beauty_2", "B2", "click", 53),
        _event("u_support_beauty_2", "A4", "impression", 54),
        _event("u_support_beauty_2", "A1", "impression", 55),
    ]

    config = PersonalizationEvalConfig(
        run_id="unit_phase12",
        top_k=5,
        synthetic_data=True,
        algorithm_version="algo_v1",
        ranking_version="rank_v1",
    )
    run_data = evaluate_personalization(
        items=items,
        clickstream_events=events,
        config=config,
    )

    baselines = {row["baseline"] for row in run_data["baseline_summaries"]}
    assert baselines == {
        "content_only",
        "exploration_only",
        "popularity",
        "profile_only",
        "profile_plus_cf",
        "profile_plus_qualified_cf",
    }

    summary_by_baseline = {
        row["baseline"]: row
        for row in run_data["baseline_summaries"]
    }
    assert summary_by_baseline["popularity"]["evaluated_user_count"] >= 2
    assert summary_by_baseline["profile_plus_cf"]["cf_supported_recommendation_count"] > 0
    assert run_data["cf_diagnostics"]["min_support"] == 2
    assert "current_build_stats" in run_data["cf_diagnostics"]
    assert summary_by_baseline["profile_plus_cf"]["negative_reexposure_rate"] == 0.0
    assert "profile_plus_qualified_cf_vs_profile_plus_cf" in {
        row["comparison"] for row in run_data["comparisons"]
    }
    assert run_data["cf_qualified_gate"]["decision"] in {"adopt", "reject", "needs_more_evidence"}

    phone_profile_only = next(
        row
        for row in run_data["per_user_metrics"]
        if row["user_id_hash"] == "u_eval_phone" and row["baseline"] == "profile_only"
    )
    phone_profile_cf = next(
        row
        for row in run_data["per_user_metrics"]
        if row["user_id_hash"] == "u_eval_phone" and row["baseline"] == "profile_plus_cf"
    )
    assert phone_profile_only["recommended_item_ids"][0] != "A2"
    assert phone_profile_cf["recommended_item_ids"][0] == "A2"

    assert run_data["config"]["algorithm_version"] == "algo_v1"
    assert run_data["config"]["ranking_version"] == "rank_v1"
    assert "synthetic/demo" in run_data["config"]["data_label"]


def test_write_personalization_outputs_writes_reproducible_artifacts_and_caveats() -> None:
    items = [
        _item("A1", title="Phone Case", brand="CaseCo", category_id="phones"),
        _item("A2", title="Charging Cable", brand="ChargeCo", category_id="phones"),
        _item("B1", title="Face Serum", brand="GlowCo", category_id="beauty"),
        _item("B2", title="Gentle Cleanser", brand="PureCo", category_id="beauty"),
    ]
    events = [
        _event("u_eval", "A1", "impression", 0),
        _event("u_eval", "A1", "click", 1),
        _event("u_eval", "B1", "impression", 2),
        _event("u_eval", "A2", "click", 3),
        _event("u_support", "A1", "impression", 4),
        _event("u_support", "A1", "click", 5),
        _event("u_support", "A2", "impression", 6),
        _event("u_support", "A2", "click", 7),
    ]

    run_data = evaluate_personalization(
        items=items,
        clickstream_events=events,
        config=PersonalizationEvalConfig(
            run_id="artifact_test",
            synthetic_data=True,
            algorithm_version="algo_v2",
            ranking_version="rank_v2",
        ),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = write_personalization_outputs(run_data, tmpdir)
        manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
        summary_md = Path(paths["metrics_summary"]).read_text(encoding="utf-8")

    assert manifest["run_id"] == "artifact_test"
    assert Path(paths["config"]).name == "config.json"
    assert Path(paths["baseline_summaries"]).name == "baseline_summaries.json"
    assert "synthetic/demo" in summary_md
    assert "profile_plus_cf" in summary_md
    assert "profile_plus_qualified_cf" in summary_md
    assert "Qualified CF Gate" in summary_md
    assert "popularity" in summary_md


def test_personalization_eval_reports_data_mode_and_user_cohorts() -> None:
    items = [
        _item("A", title="Phone Case", brand="CaseCo", category_id="phones"),
        _item("B", title="Hidden Charger", brand="ChargeCo", category_id="phones"),
        _item("C", title="Screen Protector", brand="CaseCo", category_id="phones"),
        _item("D", title="Phone Stand", brand="StandCo", category_id="phones"),
        _item("E", title="Wireless Earbuds", brand="AudioCo", category_id="audio"),
    ]
    events = [
        _event("u_sparse_negative", "A", "click", 0),
        _event("u_sparse_negative", "B", "hide", 1),
        _event("u_sparse_negative", "C", "click", 2),
        _event("u_sparse_negative", "D", "add_to_cart", 3),
        _event("u_dense", "A", "click", 10),
        _event("u_dense", "B", "click", 11),
        _event("u_dense", "C", "add_to_cart", 12),
        _event("u_dense", "D", "click", 13),
        _event("u_dense", "E", "add_to_cart", 14),
    ]

    run_data = evaluate_personalization(
        items=items,
        clickstream_events=events,
        config=PersonalizationEvalConfig(run_id="cohort_test", synthetic_data=True),
    )
    cohorts = run_data["cohort_diagnostics"]

    assert run_data["config"]["evaluation_data_mode"] == "synthetic_demo"
    assert cohorts["evaluated_user_count"] == 2
    assert cohorts["cold_start_user_count"] == 1
    assert cohorts["sparse_user_count"] == 1
    assert cohorts["deliberate_intent_user_count"] == 2
    assert cohorts["negative_feedback_user_count"] == 1
    assert cohorts["qualified_cf_source_user_count"] == 1
    assert "synthetic/demo" in cohorts["caveat"]

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = write_personalization_outputs(run_data, tmpdir)
        summary_md = Path(paths["metrics_summary"]).read_text(encoding="utf-8")

    assert "## Cohort Diagnostics" in summary_md
    assert "negative_feedback_user_count" in summary_md


def test_cli_artifact_policy_makes_dry_run_filesystem_dry_by_default() -> None:
    assert _should_write_artifacts(Namespace(dry_run=True, write_artifacts=False, no_artifacts=False)) is False
    assert _should_write_artifacts(Namespace(dry_run=True, write_artifacts=True, no_artifacts=False)) is True
    assert _should_write_artifacts(Namespace(dry_run=False, write_artifacts=False, no_artifacts=False)) is False
    assert _should_write_artifacts(Namespace(dry_run=False, write_artifacts=True, no_artifacts=False)) is True
    assert _should_write_artifacts(Namespace(dry_run=False, write_artifacts=False, no_artifacts=True)) is False


def test_terminal_summary_exposes_observability_metrics_and_caveat() -> None:
    items = [
        _item("A1", title="Phone Case", brand="CaseCo", category_id="phones"),
        _item("A2", title="Charging Cable", brand="ChargeCo", category_id="phones"),
        _item("B1", title="Face Serum", brand="GlowCo", category_id="beauty"),
        _item("B2", title="Gentle Cleanser", brand="PureCo", category_id="beauty"),
    ]
    events = [
        _event("u_eval", "A1", "click", 0),
        _event("u_eval", "B1", "impression", 1),
        _event("u_eval", "A2", "click", 2),
        _event("u_support", "A1", "click", 3),
        _event("u_support", "A2", "click", 4),
    ]
    run_data = evaluate_personalization(
        items=items,
        clickstream_events=events,
        config=PersonalizationEvalConfig(
            run_id="summary_test",
            synthetic_data=True,
            algorithm_version="algo_summary",
            ranking_version="rank_summary",
        ),
    )

    summary = _build_terminal_summary(
        run_data,
        live_state_counts={"items": 4, "clickstream_events": 5},
        artifact_paths=None,
        artifacts_skipped_reason="test no artifacts",
    )

    assert "synthetic/demo" in summary
    assert "indicative only" in summary
    assert "algo_summary" in summary
    assert "rank_summary" in summary
    assert "profile_only" in summary
    assert "profile_plus_cf" in summary
    assert "profile_plus_qualified_cf" in summary
    assert "popularity" in summary
    assert "coverage=" in summary
    assert "cold@20=" in summary
    assert "cf_count=" in summary
    assert "cf_qualified_gate:" in summary
    assert "artifacts: skipped" in summary


def test_evaluator_current_cf_accepts_click_only_but_qualified_cf_requires_deliberate_seed() -> None:
    click_only = {
        "u1": _build_train_signals([_event("u1", "A", "click", 0), _event("u1", "B", "click", 1)]),
        "u2": _build_train_signals([_event("u2", "A", "click", 2), _event("u2", "B", "click", 3)]),
    }
    deliberate = {
        "u1": _build_train_signals([_event("u1", "A", "add_to_cart", 10), _event("u1", "B", "add_to_cart", 11)]),
        "u2": _build_train_signals([_event("u2", "A", "add_to_cart", 12), _event("u2", "B", "add_to_cart", 13)]),
    }

    assert "B" in _build_cf_edges(click_only, qualified=False)["A"]
    assert _build_cf_edges(click_only, qualified=True) == {}
    assert "B" in _build_cf_edges(deliberate, qualified=True)["A"]


def test_evaluator_cf_edges_match_runtime_computation_on_same_fixture() -> None:
    train_signals = {
        "u1": _build_train_signals([_event("u1", "A", "add_to_cart", 10), _event("u1", "B", "add_to_cart", 11)]),
        "u2": _build_train_signals([_event("u2", "A", "add_to_cart", 12), _event("u2", "B", "add_to_cart", 13)]),
    }
    flat_signals = [signal for signals in train_signals.values() for signal in signals]
    runtime = compute_item_item_cf_edges(
        signal_docs=flat_signals,
        existing_item_ids={"A", "B"},
        input_policy="qualified_deliberate",
        min_support=2,
        updated_at=max(str(signal["last_interaction_at"]) for signal in flat_signals),
    )
    runtime_edges = {
        edge["item_id"]: {edge["neighbor_item_id"]: edge["cf_score"]}
        for edge in runtime["edge_docs"]
    }

    assert _build_cf_edges(train_signals, qualified=True) == runtime_edges


def test_evaluator_uses_production_dwell_tiers_for_seed_eligibility() -> None:
    signals = _build_train_signals(
        [
            {**_event("u1", "SHORT", "view_detail", 0), "dwell_time_ms": 4_000},
            {**_event("u1", "LONG", "view_detail", 1), "dwell_time_ms": 30_000},
        ]
    )
    by_item = {signal["item_id"]: signal for signal in signals}

    assert by_item["SHORT"]["seed_eligible"] is False
    assert by_item["LONG"]["seed_eligible"] is True


def test_qualified_cf_gate_needs_more_evidence_for_tiny_eval_slice() -> None:
    summary_by_baseline = {
        "profile_plus_cf": {
            "evaluated_user_count": 2,
            "deliberate_evaluated_user_count": 1,
            "recall_at_20": 1.0,
            "map_at_20": 1.0,
            "ndcg_at_20": 1.0,
            "deliberate_recall_at_20": 1.0,
            "deliberate_ndcg_at_20": 1.0,
            "deliberate_mrr_at_10": 1.0,
        },
        "profile_plus_qualified_cf": {
            "evaluated_user_count": 2,
            "deliberate_evaluated_user_count": 1,
            "cf_supported_recommendation_count": 2,
            "negative_reexposure_rate": 0.0,
            "recall_at_20": 1.0,
            "map_at_20": 1.0,
            "ndcg_at_20": 1.0,
            "deliberate_recall_at_20": 1.0,
            "deliberate_ndcg_at_20": 1.0,
            "deliberate_mrr_at_10": 1.0,
        },
    }

    gate = _qualified_cf_gate(summary_by_baseline, qualified_directional_edge_count=2)

    assert gate["decision"] == "needs_more_evidence"
    assert "evaluated_user_count 2 < 10" in gate["reason"]
    assert gate["evidence"]["evaluated_user_count"] == 2
    assert gate["minimums"]["evaluated_user_count"] == 10


def test_qualified_cf_gate_adopts_only_with_sufficient_clean_evidence() -> None:
    summary_by_baseline = {
        "profile_plus_cf": {
            "evaluated_user_count": 12,
            "deliberate_evaluated_user_count": 6,
            "recall_at_20": 0.5,
            "map_at_20": 0.4,
            "ndcg_at_20": 0.4,
            "deliberate_recall_at_20": 0.5,
            "deliberate_ndcg_at_20": 0.4,
            "deliberate_mrr_at_10": 0.4,
        },
        "profile_plus_qualified_cf": {
            "evaluated_user_count": 12,
            "deliberate_evaluated_user_count": 6,
            "cf_supported_recommendation_count": 8,
            "negative_reexposure_rate": 0.0,
            "recall_at_20": 0.5,
            "map_at_20": 0.4,
            "ndcg_at_20": 0.4,
            "deliberate_recall_at_20": 0.5,
            "deliberate_ndcg_at_20": 0.4,
            "deliberate_mrr_at_10": 0.4,
        },
    }

    gate = _qualified_cf_gate(summary_by_baseline, qualified_directional_edge_count=8)

    assert gate["decision"] == "adopt"
    assert gate["evidence"]["qualified_directional_edge_count"] == 8
