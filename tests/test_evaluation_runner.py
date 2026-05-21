"""Tests for evaluation runner."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.evaluation.contracts import EvaluationQuery, RunConfig
from src.evaluation.runner import (
    FIXTURE_SCHEMA_VERSION,
    _build_fake_results,
    build_fake_fixture,
    load_or_build_fixtures,
    run_evaluation,
)
from src.evaluation.reporting import (
    decide_claim_status,
    generate_metrics_summary_md,
    write_evaluation_outputs,
)


class TestBuildFakeFixture:
    def test_returns_valid_fixture(self) -> None:
        query = EvaluationQuery(query_id="q1", raw_query="test query", language="en", topic="skincare")
        fixture = build_fake_fixture(query)
        assert fixture["original_query"] == "test query"
        assert len(fixture["query_embedding"]) == 1024
        assert "bm25_search_query_en" in fixture


class TestBuildFakeResults:
    def test_returns_results(self) -> None:
        results = _build_fake_results("q1", "hybrid_union", 10)
        assert len(results) == 3
        assert results[0].query_id == "q1"
        assert results[0].variant == "hybrid_union"
        assert results[0].rank == 1


class TestLoadOrBuildFixtures:
    def test_build_fake_fixtures(self) -> None:
        queries = [
            EvaluationQuery(query_id="q1", raw_query="test", language="en", topic="skincare"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_path = Path(tmpdir) / "fixtures.json"
            fixtures, failures = load_or_build_fixtures(
                queries, fixture_path, use_cache=False, use_fake=True,
            )
            assert "q1" in fixtures
            assert len(failures) == 0


class TestRunEvaluation:
    def test_smoke_test_with_fake_results(self) -> None:
        queries = [
            EvaluationQuery(query_id="q1", raw_query="test query", language="en", topic="skincare"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = RunConfig(
                run_id="smoke",
                queries_path="test.json",
                output_dir=tmpdir,
                variants=["hybrid_union", "title_only"],
                top_k=10,
            )
            run_data = run_evaluation(
                config=config,
                queries=queries,
                judgments=[],
                use_fake_results=True,
            )
            assert "config" in run_data
            assert "results" in run_data
            assert "per_query_metrics" in run_data
            assert len(run_data["results"]) > 0


class TestReporting:
    def test_generate_markdown_report(self) -> None:
        run_data = {
            "config": {"run_id": "test", "k_values": [10], "relevance_threshold": 2, "variants": ["hybrid_union"]},
            "variant_summaries": [
                {"variant": "hybrid_union", "query_count": 10, "ndcg_at_10": 0.75},
            ],
            "failures": [],
            "latency": [],
        }
        md = generate_metrics_summary_md(run_data)
        assert "# Evaluation Report" in md
        assert "hybrid_union" in md

    def test_write_outputs(self) -> None:
        run_data = {
            "config": {"run_id": "test"},
            "results": [],
            "per_query_metrics": [],
            "variant_summaries": [],
            "latency": [],
            "failures": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_evaluation_outputs(run_data, tmpdir)
            assert "manifest" in paths
            manifest = json.loads(Path(paths["manifest"]).read_text())
            assert manifest["run_id"] == "test"


class TestClaimStatus:
    def test_hybrid_beats_title(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8},
            {"variant": "title_only", "ndcg_at_10": 0.3},
        ]
        claims = decide_claim_status(summaries, {}, [])
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "supported"

    def test_title_unavailable(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8},
        ]
        failures = [{"variant": "title_only", "error_type": "variant_unavailable"}]
        claims = decide_claim_status(summaries, {}, failures)
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "needs_more_evidence"
