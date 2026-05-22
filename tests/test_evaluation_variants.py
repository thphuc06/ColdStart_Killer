"""Tests for evaluation variants."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.search_pipeline import build_union_with_pipeline, build_union_with_pipeline_parametrized
from src.evaluation.variants import EVALUATION_VARIANTS, run_variant


MOCK_FIXTURE = {
    "original_query": "test query",
    "hype_search_query_en": "user looking for test query for everyday use",
    "bm25_search_query_en": "test query",
    "hard_filters": {"in_stock": True},
    "query_embedding": [0.0] * 1024,
}


class MockCollection:
    """Mock that returns realistic results for testing."""

    def __init__(self) -> None:
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return [
            {
                "item_id": "B001",
                "title": "Test Product",
                "score": 0.92,
                "matched_intent": "test intent",
                "matched_fact": "test fact",
                "rank_vector": 1,
                "rank_bm25": 2,
                "fusion_score": 0.85,
                "is_cold_item": True,
                "interaction_count": 0,
                "brand": "TestBrand",
                "category_id": "cat1",
                "price_vnd": 100000,
                "price_bucket": "100k_300k",
                "debug": {
                    "raw_vector_score": 0.78,
                    "raw_bm25_score": 11.2,
                    "matched_channels": ["vector", "bm25"],
                    "vector_contribution": 0.5,
                    "bm25_contribution": 0.35,
                    "multi_channel_bonus": 0.05,
                    "cold_start_boost": 0.03,
                    "content_richness_bonus": 0.01,
                },
            }
        ]


class TestVariantConstants:
    def test_required_variants_exist(self) -> None:
        assert "title_only" in EVALUATION_VARIANTS
        assert "vector_only" in EVALUATION_VARIANTS
        assert "bm25_only" in EVALUATION_VARIANTS
        assert "hybrid_union" in EVALUATION_VARIANTS
        assert "hybrid_no_cold_boost" in EVALUATION_VARIANTS


class TestRunVariant:
    def test_unknown_variant_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown variant"):
            run_variant(MOCK_FIXTURE, "not_a_variant", "q1", 10)

    def test_hybrid_union_with_mock(self) -> None:
        coll = MockCollection()
        results, failure = run_variant(
            MOCK_FIXTURE, "hybrid_union", "q001", 10,
            collection=coll,
        )
        assert failure is None
        assert len(results) == 1
        assert results[0].query_id == "q001"
        assert results[0].variant == "hybrid_union"
        assert results[0].item_id == "B001"
        assert coll.pipeline is not None

    def test_hybrid_no_cold_boost_disables_boost_before_sort(self) -> None:
        coll = MockCollection()
        results, failure = run_variant(
            MOCK_FIXTURE, "hybrid_no_cold_boost", "q001", 10,
            collection=coll,
        )
        assert failure is None
        assert len(results) == 1
        assert results[0].score == 0.92
        assert results[0].variant == "hybrid_no_cold_boost"
        assert coll.pipeline is not None

        bonus_stage_idx = next(
            i for i, stage in enumerate(coll.pipeline)
            if "$addFields" in stage and "cold_start_boost" in stage["$addFields"]
        )
        score_stage_idx = next(
            i for i, stage in enumerate(coll.pipeline)
            if "$addFields" in stage and "score" in stage["$addFields"]
        )
        sort_stage_idx = next(i for i, stage in enumerate(coll.pipeline) if "$sort" in stage)
        limit_stage_idx = next(i for i, stage in enumerate(coll.pipeline) if "$limit" in stage)

        assert coll.pipeline[bonus_stage_idx]["$addFields"]["cold_start_boost"] == 0
        assert bonus_stage_idx < score_stage_idx < sort_stage_idx < limit_stage_idx
        score_components = coll.pipeline[score_stage_idx]["$addFields"]["score"]["$add"]
        assert "$cold_start_boost" not in score_components

    def test_production_pipeline_matches_parametrized_defaults(self) -> None:
        assert build_union_with_pipeline(MOCK_FIXTURE, top_k=10) == build_union_with_pipeline_parametrized(
            MOCK_FIXTURE,
            top_k=10,
        )

    def test_title_only_with_mock(self) -> None:
        coll = MockCollection()
        results, failure = run_variant(
            MOCK_FIXTURE, "title_only", "q001", 10,
            items_collection=coll,
        )
        # title_only uses items_collection, not collection
        assert failure is None

    def test_failure_returns_failure_record(self) -> None:
        class FailingCollection:
            def aggregate(self, pipeline):
                raise RuntimeError("connection failed")

        results, failure = run_variant(
            MOCK_FIXTURE, "hybrid_union", "q001", 10,
            collection=FailingCollection(),
        )
        assert results == []
        assert failure is not None
        assert failure.stage == "search"
        assert failure.recoverable is True
