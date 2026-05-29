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
from src.evaluation.golden_runs import get_golden_run_profile, list_golden_run_profiles
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
    write_judge_report_pack,
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
            assert enriched["evaluation_schema_version"]
            assert enriched["artifact_contract_version"]
            assert enriched["input_fingerprints"]["queries"]["path"] == "test.json"
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

    def test_run_data_includes_evidence_quality_diagnostics(self) -> None:
        queries = [
            EvaluationQuery(
                query_id=f"q{i}",
                raw_query=f"test query {i}",
                language="en",
                topic="electronics",
                slices=["english", "compatibility"],
            )
            for i in range(3)
        ]
        judgments = [
            RelevanceJudgment(query_id=f"q{i}", item_id="FAKE_hybrid_union_0", relevance=3)
            for i in range(3)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = RunConfig(
                run_id="diagnostics",
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

        assert run_data["variant_comparisons"]
        assert run_data["variant_comparisons"][0]["significance"] == "directional_only"
        assert "slice_confidence" in run_data
        assert any(row["slice"] == "compatibility" for row in run_data["slice_confidence"])
        assert run_data["latency_summary"]["search_latency_ms"]["sample_count"] > 0
        assert run_data["latency_summary"]["total_latency_ms"]["sample_count"] > 0

    def test_run_data_includes_judgment_audit_by_source_and_slice(self) -> None:
        queries = [
            EvaluationQuery(
                query_id="q_vi",
                raw_query="kem chống nắng",
                language="vi",
                topic="beauty",
                slices=["vietnamese", "price_filter"],
            ),
            EvaluationQuery(
                query_id="q_en",
                raw_query="iphone case",
                language="en",
                topic="electronics",
                slices=["english", "compatibility"],
            ),
        ]
        judgments = [
            RelevanceJudgment(
                query_id="q_vi",
                item_id="FAKE_hybrid_union_0",
                relevance=3,
                judgment_source="human_audited",
                annotator_id="auditor_a",
            ),
            RelevanceJudgment(
                query_id="q_en",
                item_id="FAKE_hybrid_union_0",
                relevance=2,
                judgment_source="ai_assisted",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = RunConfig(
                run_id="audit",
                queries_path="queries.json",
                judgments_path="judgments.json",
                output_dir=tmpdir,
                variants=["hybrid_union"],
                top_k=10,
                use_cached_fixtures=False,
            )
            run_data = run_evaluation(
                config=config,
                queries=queries,
                judgments=judgments,
                use_fake_results=True,
            )

        audit = run_data["judgment_audit"]
        assert audit["source_counts"] == {"human_audited": 1, "ai_assisted": 1}
        assert audit["overall_status"] == "mixed"
        vi_slice = next(row for row in audit["slice_audit"] if row["slice"] == "vietnamese")
        compatibility_slice = next(row for row in audit["slice_audit"] if row["slice"] == "compatibility")
        assert vi_slice["human_audited_query_count"] == 1
        assert vi_slice["audit_status"] == "human_audited"
        assert compatibility_slice["audit_status"] == "ai_assisted"

    def test_coverage_stats_do_not_depend_on_first_variant(self) -> None:
        queries = [
            EvaluationQuery(query_id="q1", raw_query="test one", language="en", topic="skincare"),
            EvaluationQuery(query_id="q2", raw_query="test two", language="en", topic="skincare"),
        ]
        judgments = [
            RelevanceJudgment(query_id="q1", item_id="FAKE_hybrid_union_0", relevance=3),
            RelevanceJudgment(query_id="q2", item_id="FAKE_hybrid_union_0", relevance=3),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = RunConfig(
                run_id="coverage_stats",
                queries_path="queries.json",
                judgments_path="judgments.json",
                output_dir=tmpdir,
                variants=["title_only", "hybrid_union"],
                top_k=10,
                use_cached_fixtures=False,
            )
            run_data = run_evaluation(
                config=config,
                queries=queries,
                judgments=judgments,
                use_fake_results=True,
            )

        coverage = run_data["coverage_stats"]
        assert coverage["judged_query_count"] == 2
        assert coverage["positive_judged_query_count"] == 2
        assert coverage["report_status"] == "insufficient_judgments"


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

    def test_report_shows_judgment_provenance_and_claim_blockers(self) -> None:
        run_data = {
            "config": {
                "run_id": "test",
                "variants": ["hybrid_union", "title_only"],
                "judged_query_count": 30,
                "positive_judged_query_count": 20,
                "total_query_count": 30,
                "judgment_audit": {
                    "overall_status": "mixed",
                    "source_counts": {"human_audited": 5, "ai_assisted": 25},
                    "slice_audit": [
                        {
                            "slice": "price_filter",
                            "query_count": 8,
                            "judged_query_count": 8,
                            "human_audited_query_count": 0,
                            "audit_status": "ai_assisted",
                        }
                    ],
                },
            },
            "variant_summaries": [
                {"variant": "hybrid_union", "query_count": 30, "ndcg_at_10": 0.8, "recall_at_10": 0.7, "mrr_at_10": 0.6},
                {"variant": "title_only", "query_count": 30, "ndcg_at_10": 0.3, "recall_at_10": 0.2, "mrr_at_10": 0.1},
            ],
            "slice_summaries": [],
            "failures": [],
            "latency": [],
        }

        md = generate_metrics_summary_md(run_data)

        assert "## Judgment Provenance" in md
        assert "| human_audited | 5 |" in md
        assert "## Claim Blockers" in md
        assert "paired comparison evidence not supportive" in md
        assert "## What We Can Claim" in md
        assert "## What We Cannot Claim Yet" in md

    def test_ablation_impact_uses_stable_no_cold_variant_name_for_paired_evidence(self) -> None:
        run_data = {
            "config": {"run_id": "test", "variants": ["hybrid_union", "hybrid_no_cold_boost"]},
            "variant_summaries": [
                {"variant": "hybrid_union", "query_count": 30, "ndcg_at_10": 0.8},
                {"variant": "hybrid_no_cold_boost", "query_count": 30, "ndcg_at_10": 0.7},
            ],
            "variant_comparisons": [
                {
                    "comparison": "hybrid_union_vs_hybrid_no_cold_boost",
                    "metric": "ndcg_at_10",
                    "significance": "positive",
                    "blockers": [],
                }
            ],
            "failures": [],
            "latency": [],
        }

        md = generate_metrics_summary_md(run_data)

        assert "| hybrid vs no_cold_boost |" in md
        assert "| hybrid vs no_cold_boost | +0.1 | N/A | N/A | positive |" in md
        assert "missing paired comparison" not in md


class TestGoldenRuns:
    def test_golden_run_profiles_are_stable_and_reproducible(self) -> None:
        assert list_golden_run_profiles() == ["smoke", "judge_demo", "live_regression"]
        smoke = get_golden_run_profile("smoke")
        judge_demo = get_golden_run_profile("judge_demo")
        live_regression = get_golden_run_profile("live_regression")

        assert smoke["use_fake_results"] is True
        assert smoke["purpose"] == "ci_smoke"
        assert judge_demo["purpose"] == "judge_facing_demo"
        assert live_regression["mongodb_live_required"] is True
        assert smoke["queries_path"] == "evaluation/queries/retrieval_queries_seed.json"
        assert smoke["judgments_path"] == "evaluation/judgments/retrieval_judgments_seed.json"
        assert "input_fingerprints" in smoke["reproducibility_requirements"]

    def test_golden_run_script_prints_reproducible_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "run_golden_evaluation.py"),
                "--profile", "smoke",
                "--out-root", tmpdir,
                "--print-command",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

        assert result.returncode == 0, result.stderr
        assert "scripts/run_evaluation.py" in result.stdout
        assert "--use-fake-results" in result.stdout
        assert "evaluation/queries/retrieval_queries_seed.json" in result.stdout


class TestJudgeReportPack:
    def test_write_judge_report_pack_adds_executive_summary_and_manifest(self) -> None:
        run_data = {
            "config": {
                "run_id": "judge_pack",
                "judged_query_count": 30,
                "positive_judged_query_count": 20,
                "variants": ["hybrid_union", "title_only"],
            },
            "variant_summaries": [
                {"variant": "hybrid_union", "query_count": 30, "ndcg_at_10": 0.8, "recall_at_10": 0.7, "mrr_at_10": 0.6},
                {"variant": "title_only", "query_count": 30, "ndcg_at_10": 0.3, "recall_at_10": 0.2, "mrr_at_10": 0.1},
            ],
            "variant_comparisons": [
                {
                    "comparison": "hybrid_union_vs_title_only",
                    "metric": metric,
                    "scope": "overall",
                    "significance": "positive",
                    "blockers": [],
                }
                for metric in ("ndcg_at_10", "recall_at_10", "mrr_at_10")
            ],
            "failures": [],
            "latency": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_judge_report_pack(run_data, tmpdir)
            summary = Path(paths["executive_summary"]).read_text(encoding="utf-8")
            manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))

        assert Path(paths["executive_summary"]).name == "judge_facing_executive_summary.md"
        assert "## What We Can Claim" in summary
        assert "## What We Cannot Claim Yet" in summary
        assert "metrics_summary.md" in summary
        assert "hackathon_impact_report.md" in summary
        assert "evaluation_upgrade_report_vi.md" in summary
        assert manifest["artifact_contract_version"] == "1.0"
        assert "metrics_summary.md" in manifest["expected_pack_files"]
        assert "evaluation_upgrade_report_vi.md" not in manifest["expected_pack_files"]
        assert "evaluation_upgrade_report_vi.md" in manifest["optional_static_pack_files"]
        assert manifest["missing_required_files"] == []


class TestClaimStatus:
    def test_hybrid_beats_title(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8, "recall_at_10": 0.7, "mrr_at_10": 0.6},
            {"variant": "title_only", "ndcg_at_10": 0.3, "recall_at_10": 0.2, "mrr_at_10": 0.1},
        ]
        config = {
            "judged_query_count": 30,
            "positive_judged_query_count": 20,
            "variant_comparisons": [
                {
                    "comparison": "hybrid_union_vs_title_only",
                    "metric": "ndcg_at_10",
                    "significance": "positive",
                    "mean_delta": 0.5,
                    "paired_query_count": 30,
                    "blockers": [],
                },
                {
                    "comparison": "hybrid_union_vs_title_only",
                    "metric": "recall_at_10",
                    "significance": "positive",
                    "mean_delta": 0.5,
                    "paired_query_count": 30,
                    "blockers": [],
                },
                {
                    "comparison": "hybrid_union_vs_title_only",
                    "metric": "mrr_at_10",
                    "significance": "positive",
                    "mean_delta": 0.5,
                    "paired_query_count": 30,
                    "blockers": [],
                },
            ],
        }
        claims = decide_claim_status(summaries, config, [])
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "supported"

    def test_raw_metric_win_without_paired_evidence_needs_more_evidence(self) -> None:
        summaries = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8, "recall_at_10": 0.7, "mrr_at_10": 0.6},
            {"variant": "title_only", "ndcg_at_10": 0.3, "recall_at_10": 0.2, "mrr_at_10": 0.1},
        ]
        config = {"judged_query_count": 30, "positive_judged_query_count": 20}
        claims = decide_claim_status(summaries, config, [])
        title_claim = next(c for c in claims if "title" in c.claim.lower())
        assert title_claim.status == "needs_more_evidence"
        assert "paired comparison" in title_claim.blocker

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
            "slice_confidence": [
                {
                    "slice": "vietnamese",
                    "variant": "hybrid_union",
                    "confidence": "medium",
                    "blockers": [],
                }
            ],
            "slice_variant_comparisons": [
                {
                    "comparison": "hybrid_union_vs_title_only",
                    "metric": "ndcg_at_10",
                    "scope": "slice:vietnamese",
                    "significance": "positive",
                    "blockers": [],
                }
            ],
        }
        claims = decide_claim_status([], config, [])
        vi_claim = next(c for c in claims if c.claim == "Vietnamese robustness")
        assert vi_claim.status == "supported"
        assert "hybrid Vietnamese NDCG@10" in vi_claim.evidence

    def test_slice_quality_claims_need_slice_paired_evidence(self) -> None:
        config = {
            "judged_query_count": 30,
            "positive_judged_query_count": 20,
            "slice_confidence": [
                {
                    "slice": "price_filter",
                    "variant": "hybrid_union",
                    "confidence": "medium",
                    "judged_query_count": 6,
                    "blockers": [],
                }
            ],
            "slice_metrics": {
                "price_filter": {
                    "hybrid_union": {"ndcg_at_10": 0.7},
                    "title_only": {"ndcg_at_10": 0.4},
                }
            },
        }

        claims = decide_claim_status([], config, [])
        price_claim = next(c for c in claims if c.claim == "Price-filter retrieval quality")

        assert price_claim.status == "needs_more_evidence"
        assert "slice paired comparison" in price_claim.blocker

    def test_latency_claims_separate_search_and_total_path(self) -> None:
        config = {
            "use_cached_fixtures": False,
            "mongodb_live": True,
            "latency_sample_count": 25,
            "latency_summary": {
                "search_latency_ms": {"sample_count": 25, "p50": 20.0, "p95": 45.0, "confidence": "medium"},
                "total_latency_ms": {"sample_count": 25, "p50": 500.0, "p95": 900.0, "confidence": "medium"},
            },
        }
        claims = decide_claim_status([], config, [])
        claim_by_name = {claim.claim: claim for claim in claims}

        assert claim_by_name["Live search latency evidence"].status == "supported"
        assert "search P95=45.0ms" in claim_by_name["Live search latency evidence"].evidence
        assert claim_by_name["Live total path latency evidence"].status == "supported"
        assert "total path P95=900.0ms" in claim_by_name["Live total path latency evidence"].evidence
        assert "Live end-to-end latency" not in claim_by_name


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

    def test_allow_stale_fixtures_flag_is_wired_to_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "run"
            out_dir.mkdir(parents=True, exist_ok=True)
            stale_cache = {
                "fixture_schema_version": "0.0",
                "fixtures": {
                    "q1": {
                        "original_query": "test query",
                        "language_detected": "en",
                        "english_query": "test query",
                        "hype_search_query_en": "user looking for test query",
                        "bm25_search_query_en": "test query",
                        "hard_filters": {},
                        "query_embedding": [0.0] * 1024,
                    }
                },
            }
            (out_dir / "query_fixtures.json").write_text(
                json.dumps(stale_cache),
                encoding="utf-8",
            )

            cmd = [
                sys.executable,
                str(ROOT / "scripts" / "run_evaluation.py"),
                "--queries", str(ROOT / "evaluation" / "queries" / "retrieval_queries_seed.json"),
                "--judgments", str(ROOT / "evaluation" / "judgments" / "retrieval_judgments_seed.json"),
                "--out", str(out_dir),
                "--use-fake-results",
                "--use-cached-fixtures",
                "--allow-stale-fixtures",
                "--variants", "hybrid_union",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            assert result.returncode == 0, result.stderr
            failures = json.loads((out_dir / "failures.json").read_text(encoding="utf-8"))
            assert not any(f.get("error_type") == "stale_fixture_schema" for f in failures)
