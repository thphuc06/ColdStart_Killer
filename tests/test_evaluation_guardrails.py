"""Tests for evaluation guardrails.

Covers: import safety, read-only enforcement, constant mutation protection,
and result status validation.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


class TestImportSafety:
    """Importing evaluation modules must have no side effects."""

    def test_contracts_import_safe(self) -> None:
        importlib.import_module("src.evaluation.contracts")

    def test_dataset_import_safe(self) -> None:
        importlib.import_module("src.evaluation.dataset")

    def test_metrics_import_safe(self) -> None:
        importlib.import_module("src.evaluation.metrics")

    def test_diagnostics_import_safe(self) -> None:
        importlib.import_module("src.evaluation.diagnostics")

    def test_variants_import_safe(self) -> None:
        importlib.import_module("src.evaluation.variants")

    def test_runner_import_safe(self) -> None:
        importlib.import_module("src.evaluation.runner")

    def test_reporting_import_safe(self) -> None:
        importlib.import_module("src.evaluation.reporting")


class TestReadOnlyEnforcement:
    """Evaluation runner must never call MongoDB write methods."""

    def test_read_only_mock_collection(self) -> None:
        class ReadOnlyMockCollection:
            def aggregate(self, pipeline):
                return [{
                    "item_id": "B001", "title": "Test",
                    "score": 0.9, "matched_intent": "", "matched_fact": "",
                    "rank_vector": 1, "rank_bm25": None,
                    "fusion_score": 0.85, "is_cold_item": False,
                    "interaction_count": 5,
                    "debug": {"raw_vector_score": 0.78, "raw_bm25_score": 0.0},
                }]

            def insert_one(self, *a, **kw): raise RuntimeError("Write attempted")
            def insert_many(self, *a, **kw): raise RuntimeError("Write attempted")
            def update_one(self, *a, **kw): raise RuntimeError("Write attempted")
            def update_many(self, *a, **kw): raise RuntimeError("Write attempted")
            def replace_one(self, *a, **kw): raise RuntimeError("Write attempted")
            def delete_one(self, *a, **kw): raise RuntimeError("Write attempted")
            def delete_many(self, *a, **kw): raise RuntimeError("Write attempted")
            def bulk_write(self, *a, **kw): raise RuntimeError("Write attempted")
            def create_index(self, *a, **kw): raise RuntimeError("Write attempted")
            def drop_index(self, *a, **kw): raise RuntimeError("Write attempted")

        from src.evaluation.variants import run_variant

        coll = ReadOnlyMockCollection()
        fixture = {
            "original_query": "test",
            "hype_search_query_en": "test",
            "bm25_search_query_en": "test",
            "hard_filters": {"in_stock": True},
            "query_embedding": [0.0] * 1024,
        }
        results, failure = run_variant(fixture, "hybrid_union", "q1", 10, collection=coll)
        # Should succeed with aggregate only — no writes triggered
        assert failure is None
        assert len(results) > 0


class TestConstantMutationProtection:
    """hybrid_no_cold_boost must not mutate global COLD_START_BOOST."""

    def test_cold_start_boost_unchanged_after_ablation(self) -> None:
        from src.search_pipeline import COLD_START_BOOST
        from src.evaluation.variants import run_variant

        original = COLD_START_BOOST

        class MockColl:
            def aggregate(self, pipeline):
                return [{
                    "item_id": "B001", "title": "T", "score": 0.9,
                    "matched_intent": "", "matched_fact": "",
                    "rank_vector": 1, "rank_bm25": None,
                    "fusion_score": 0.85, "is_cold_item": True,
                    "interaction_count": 0,
                    "debug": {
                        "raw_vector_score": 0.78, "raw_bm25_score": 0.0,
                        "cold_start_boost": 0.03,
                    },
                }]

        fixture = {
            "original_query": "test",
            "hype_search_query_en": "test",
            "bm25_search_query_en": "test",
            "hard_filters": {"in_stock": True},
            "query_embedding": [0.0] * 1024,
        }
        run_variant(fixture, "hybrid_no_cold_boost", "q1", 10, collection=MockColl())

        from src.search_pipeline import COLD_START_BOOST as after
        assert after == original, "COLD_START_BOOST was mutated!"


class TestResultStatusValidation:
    def test_valid_statuses(self) -> None:
        from src.evaluation.contracts import VALID_RESULT_STATUSES
        assert "ok" in VALID_RESULT_STATUSES
        assert "ok_empty" in VALID_RESULT_STATUSES
        assert "failed" in VALID_RESULT_STATUSES
        assert "skipped" in VALID_RESULT_STATUSES

    def test_cold_item_defaults(self) -> None:
        from src.evaluation.contracts import EvaluationResult
        r = EvaluationResult(
            query_id="q1", variant="v1", rank=1,
            item_id="B1", score=0.5,
        )
        assert r.is_cold_item is None  # default is None, not True
