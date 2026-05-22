"""Tests for evaluation runner."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.evaluation.contracts import EvaluationQuery, RelevanceJudgment, RunConfig
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

    def test_run_config_contains_reproducibility_metadata(self) -> None:
        queries = [
            EvaluationQuery(query_id="q1", raw_query="test query", language="en", topic="skincare"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = RunConfig(
                run_id="smoke",
                queries_path="test.json",
                judgments_path="judgments.json",
                output_dir=tmpdir,
                variants=["hybrid_union"],
                top_k=10,
                use_cached_fixtures=False,
            )
            run_data = run_evaluation(
                config=config,
                queries=queries,
                judgments=[],
                use_fake_results=True,
            )
            enriched = run_data["config"]
            assert enriched["query_count"] == 1
            assert enriched["judgment_count"] == 0
            assert enriched["mongodb_source"] == "fake_results"
            assert enriched["mongodb_live"] is False
            assert enriched["fixture_source"] == "fake"
            assert enriched["warm_cache"] is False
            assert enriched["plan_version"] == "v2.0"
            assert enriched["code_version"] == "2.0.0"
            assert enriched["python_version"]
            assert enriched["platform"]

    def test_run_config_exposes_vietnamese_slice_metrics(self) -> None:
        queries = [
            EvaluationQuery(
                query_id="q_vi",
                raw_query="kem chống nắng",
                language="vi",
                topic="skincare",
                slices=["vietnamese", "beauty"],
            ),
        ]
        judgments = [
            RelevanceJudgment(query_id="q_vi", item_id="FAKE_hybrid_union_0", relevance=3),
            RelevanceJudgment(query_id="q_vi", item_id="FAKE_title_only_0", relevance=1),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = RunConfig(
                run_id="smoke",
                queries_path="test.json",
                judgments_path="judgments.json",
                output_dir=tmpdir,
                variants=["hybrid_union", "title_only"],
                top_k=10,
                use_cached_fixtures=False,
            )
            run_data = run_evaluation(
                config=config,
                queries=queries,
                judgments=judgments,
                use_fake_results=True,
            )
            enriched = run_data["config"]
            assert enriched["vietnamese_hybrid_ndcg_at_10"] is not None
            assert enriched["vietnamese_title_ndcg_at_10"] is not None


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

    def test_generate_markdown_report_has_p2_sections(self) -> None:
        run_data = {
            "config": {
                "run_id": "test",
                "variants": ["hybrid_union", "title_only"],
                "judged_query_count": 6,
                "positive_judged_query_count": 4,
                "total_query_count": 6,
            },
            "results": [
                {"query_id": "q1", "variant": "hybrid_union", "matched_intent": "intent", "matched_fact": ""},
            ],
            "variant_summaries": [
                {"variant": "hybrid_union", "query_count": 6, "judged_query_count": 6, "ndcg_at_10": 0.7},
                {"variant": "title_only", "query_count": 6, "judged_query_count": 6, "ndcg_at_10": 0.4},
            ],
            "slice_summaries": [
                {
                    "variant": "hybrid_union",
                    "slice": "english",
                    "query_count": 6,
                    "judged_query_count": 5,
                    "ndcg_at_10": 0.7,
                },
                {
                    "variant": "title_only",
                    "slice": "english",
                    "query_count": 6,
                    "judged_query_count": 5,
                    "ndcg_at_10": 0.4,
                },
            ],
            "failures": [
                {
                    "variant": "hybrid_union",
                    "query_id": "q1",
                    "error_type": "aggregation_failed",
                    "error": "boom",
                    "next_file_to_inspect": "src/search_pipeline.py",
                    "next_function_to_inspect": "build_union_with_pipeline",
                    "details": {"mongo_code": 123},
                },
            ],
            "latency": [],
        }
        md = generate_metrics_summary_md(run_data)
        assert "### Language Slices" in md
        assert "| Slice | Queries | Judged | Confidence | Hybrid NDCG@10 | Title NDCG@10 | Delta |" in md
        assert "## Failure Dashboard" in md
        assert "mongo_code: 123" in md
        assert "## Explanation Coverage" in md
        assert "Less than 50% of results have full explanations" in md


class TestClaimStatus:
    def test_hybrid_beats_title(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8, "recall_at_10": 0.7, "mrr_at_10": 0.6},
            {"variant": "title_only", "ndcg_at_10": 0.3, "recall_at_10": 0.2, "mrr_at_10": 0.1},
        ]
        config = {"judged_query_count": 30, "positive_judged_query_count": 20}
        claims = decide_claim_status(summaries, config, [])
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "supported"

    def test_claim_status_requires_judgment_gates(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8, "recall_at_10": 0.7, "mrr_at_10": 0.6},
            {"variant": "title_only", "ndcg_at_10": 0.3, "recall_at_10": 0.2, "mrr_at_10": 0.1},
        ]
        claims = decide_claim_status(summaries, {}, [])
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "needs_more_evidence"
        assert "Insufficient judgments" in title_claim.blocker

    def test_null_metrics_return_needs_more_evidence(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8, "recall_at_10": None, "mrr_at_10": 0.6},
            {"variant": "title_only", "ndcg_at_10": 0.3, "recall_at_10": 0.2, "mrr_at_10": 0.1},
        ]
        config = {"judged_query_count": 30, "positive_judged_query_count": 20}
        claims = decide_claim_status(summaries, config, [])
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "needs_more_evidence"
        assert title_claim.blocker == "Some comparison metrics are null"

    def test_title_unavailable(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8},
        ]
        failures = [{"variant": "title_only", "error_type": "variant_unavailable"}]
        claims = decide_claim_status(summaries, {}, failures)
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "needs_more_evidence"

    def test_vietnamese_robustness_supported_when_slice_beats_title(self) -> None:
        config = {
            "judged_query_count": 30,
            "positive_judged_query_count": 20,
            "vietnamese_judged_query_count": 5,
            "vietnamese_hybrid_ndcg_at_10": 0.7,
            "vietnamese_title_ndcg_at_10": 0.4,
        }
        claims = decide_claim_status([], config, [])
        vi_claim = next(c for c in claims if c.claim == "Vietnamese robustness")
        assert vi_claim.status == "supported"
        assert "hybrid Vietnamese NDCG@10" in vi_claim.evidence


class TestRunEvaluationScript:
    def test_hackathon_impact_report_is_generated_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "run_evaluation.py"),
                "--queries", str(ROOT / "evaluation" / "queries" / "retrieval_queries_seed.json"),
                "--judgments", str(ROOT / "evaluation" / "judgments" / "retrieval_judgments_seed.json"),
                "--out", tmpdir,
                "--use-fake-results",
                "--variants", "hybrid_union", "title_only",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            report_path = Path(tmpdir) / "hackathon_impact_report.md"
            assert report_path.exists()
            assert "Hackathon Impact Report" in report_path.read_text(encoding="utf-8")
