from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from scripts import compare_fusion_strategies as compare_script
from src.evaluation.fusion_comparison import (
    FusionComparisonConfig,
    FusionComparisonError,
    build_catalog_backed_query_fixture,
    compare_query_across_modes,
    compute_top_k_overlap,
    run_fusion_comparison,
    safe_run_search_mode,
    write_fusion_comparison_artifact,
)
from src.search_pipeline import run_search


def _fixture(raw_query: str) -> dict:
    return {
        "original_query": raw_query,
        "language_detected": "en",
        "english_query": raw_query,
        "hype_search_query_en": f"user looking for {raw_query}",
        "bm25_search_query_en": raw_query,
        "hard_filters": {},
        "query_embedding": [0.0] * 1024,
    }


def _process_query(raw_query: str) -> dict:
    return _fixture(raw_query)


class _FakeItemHypeProfilesCollection:
    def __init__(self) -> None:
        self.write_calls: list[str] = []

    def find_one(self, _query, _projection):
        return {"item_id": "ITEM_1", "item_semantic_embedding": [0.1] * 1024}

    def insert_one(self, *_args, **_kwargs):
        self.write_calls.append("insert_one")

    def update_one(self, *_args, **_kwargs):
        self.write_calls.append("update_one")

    def delete_one(self, *_args, **_kwargs):
        self.write_calls.append("delete_one")


def test_compute_top_k_overlap_handles_matches_and_empty_lists() -> None:
    assert compute_top_k_overlap(["A", "B", "C"], ["B", "C", "D"], k=3) == pytest.approx(2 / 3)
    assert compute_top_k_overlap([], ["A"], k=3) == 0.0
    assert compute_top_k_overlap(["A"], [], k=3) == 0.0


def test_catalog_backed_fixture_uses_read_only_collection() -> None:
    collection = _FakeItemHypeProfilesCollection()

    fixture = build_catalog_backed_query_fixture(
        "sunscreen",
        item_hype_profiles_collection=collection,
    )

    assert fixture["fixture_source"] == "catalog_backed_item_hype_profile"
    assert fixture["source_item_id"] == "ITEM_1"
    assert fixture["hard_filters"] == {}
    assert len(fixture["query_embedding"]) == 1024
    assert collection.write_calls == []


def test_score_fusion_is_reported_not_implemented_without_calling_search() -> None:
    def fail_search(*_args, **_kwargs):
        raise AssertionError("scoreFusion should not call run_search")

    result = safe_run_search_mode(_fixture("query"), mode="scoreFusion", top_k=5, run_search_fn=fail_search)

    assert result["status"] == "not_implemented"
    assert "proposed-only" in result["message"]


def test_rank_fusion_unsupported_skips_when_not_strict() -> None:
    def unsupported_search(*_args, **_kwargs):
        raise RuntimeError("MongoDB rankFusion aggregation failed: Unrecognized pipeline stage name: '$rankFusion'")

    result = safe_run_search_mode(_fixture("query"), mode="rankFusion", top_k=5, run_search_fn=unsupported_search)

    assert result["status"] == "unsupported"
    assert "$rankFusion" in result["message"]


def test_rank_fusion_unsupported_raises_when_strict() -> None:
    def unsupported_search(*_args, **_kwargs):
        raise RuntimeError("MongoDB rankFusion aggregation failed: $rankFusion is not supported")

    with pytest.raises(FusionComparisonError):
        safe_run_search_mode(
            _fixture("query"),
            mode="rankFusion",
            top_k=5,
            run_search_fn=unsupported_search,
            strict=True,
        )


def test_union_with_baseline_ok_and_overlap_summary() -> None:
    def fake_search(_fixture, top_k=10, mode="unionWith"):
        if mode == "unionWith":
            return [
                {"item_id": "A", "score": 0.9, "explanation": "baseline"},
                {"item_id": "B", "score": 0.8, "debug": {"channel": "vector"}},
            ][:top_k]
        if mode == "rankFusion":
            return [
                {"item_id": "B", "score": 0.7},
                {"item_id": "C", "score": 0.6},
            ][:top_k]
        raise AssertionError(f"unexpected mode {mode}")

    report = compare_query_across_modes(
        "sunscreen",
        modes=("unionWith", "rankFusion"),
        top_k=2,
        process_query_fn=_process_query,
        run_search_fn=fake_search,
    )

    union_row = report["modes"][0]
    rank_row = report["modes"][1]
    assert union_row["status"] == "ok"
    assert union_row["top_item_ids"] == ["A", "B"]
    assert union_row["explainable_count"] == 2
    assert rank_row["top_k_overlap_vs_unionWith"] == 0.5


def test_run_fusion_comparison_does_not_write_mongodb_or_change_default() -> None:
    calls = []

    def fake_search(_fixture, top_k=10, mode="unionWith"):
        calls.append(mode)
        return [{"item_id": f"{mode}_A", "score": 1.0}]

    report = run_fusion_comparison(
        config=FusionComparisonConfig(queries=("q1",), modes=("unionWith", "rankFusion", "scoreFusion"), top_k=1),
        process_query_fn=_process_query,
        run_search_fn=fake_search,
    )

    assert report["mongo_write_performed"] is False
    assert report["default_search_unchanged"] is True
    assert report["default_search_mode"] == "unionWith"
    assert calls == ["unionWith", "rankFusion"]


def test_default_run_search_mode_remains_union_with() -> None:
    signature = inspect.signature(run_search)
    assert signature.parameters["mode"].default == "unionWith"


def test_artifact_writing_is_explicit(tmp_path: Path, monkeypatch) -> None:
    report = run_fusion_comparison(
        config=FusionComparisonConfig(queries=("q1",), modes=("unionWith",), top_k=1),
        process_query_fn=_process_query,
        run_search_fn=lambda _fixture, top_k=1, mode="unionWith": [{"item_id": "A", "score": 1.0}],
    )
    artifact_path = write_fusion_comparison_artifact(report, tmp_path)
    assert artifact_path.exists()
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["comparison_type"] == "fusion_comparison"

    def fake_report(*_args, **_kwargs):
        return {
            "summary": {},
            "queries": [],
            "score_fusion_status": "not_implemented",
            "caveat": "comparison only",
        }

    def fail_write(*_args, **_kwargs):
        raise AssertionError("artifact write should require --write-artifacts")

    monkeypatch.setattr(compare_script, "run_fusion_comparison", fake_report)
    monkeypatch.setattr(compare_script, "write_fusion_comparison_artifact", fail_write)

    assert compare_script.main(["--dry-run"]) == 0
