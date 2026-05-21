"""Tests for evaluation metrics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from src.evaluation.contracts import EvaluationResult
from src.evaluation.metrics import (
    aggregate_metrics,
    binary_relevant,
    compute_query_metrics,
    dcg,
    ndcg,
)


class TestBinaryRelevant:
    def test_threshold_2(self) -> None:
        assert binary_relevant(3, 2) is True
        assert binary_relevant(2, 2) is True
        assert binary_relevant(1, 2) is False
        assert binary_relevant(0, 2) is False

    def test_threshold_1(self) -> None:
        assert binary_relevant(1, 1) is True
        assert binary_relevant(0, 1) is False


class TestDCG:
    def test_basic(self) -> None:
        import math
        # DCG of [3, 2, 1] = 3/log2(2) + 2/log2(3) + 1/log2(4)
        result = dcg([3, 2, 1])
        expected = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
        assert abs(result - expected) < 1e-10

    def test_empty(self) -> None:
        assert dcg([]) == 0.0

    def test_single(self) -> None:
        assert dcg([3]) == 3.0  # 3 / log2(2) = 3 / 1.0


class TestNDCG:
    def test_perfect_ranking(self) -> None:
        assert ndcg([3, 2, 1], [3, 2, 1]) == 1.0

    def test_worst_ranking(self) -> None:
        result = ndcg([1, 2, 3], [3, 2, 1])
        assert result is not None
        assert result < 1.0

    def test_zero_ideal(self) -> None:
        assert ndcg([0, 0, 0], [0, 0, 0]) is None


class TestComputeQueryMetrics:
    def _make_results(self, items: list[str], variant: str = "hybrid_union") -> list[EvaluationResult]:
        return [
            EvaluationResult(
                query_id="q1", variant=variant, rank=i + 1,
                item_id=item, score=1.0 / (i + 1),
            )
            for i, item in enumerate(items)
        ]

    def test_perfect_recall(self) -> None:
        results = self._make_results(["B1", "B2", "B3"])
        judgments = {"B1": 3, "B2": 2, "B3": 1}
        metrics = compute_query_metrics(results, judgments, k_values=[3], relevance_threshold=2)
        assert metrics["precision_at_3"] == round(2 / 3, 4)
        assert metrics["recall_at_3"] == 1.0  # 2 relevant out of 2 retrieved
        assert metrics["hit_rate_at_3"] == 1

    def test_no_judgments(self) -> None:
        results = self._make_results(["B1", "B2"])
        metrics = compute_query_metrics(results, {}, k_values=[5], relevance_threshold=2)
        assert metrics["has_judgments"] is False
        assert metrics["judged_result_count"] == 0
        assert metrics["precision_at_5"] == 0.0

    def test_mrr(self) -> None:
        results = self._make_results(["B1", "B2", "B3"])
        judgments = {"B2": 3}  # First relevant at rank 2
        metrics = compute_query_metrics(results, judgments, k_values=[3], relevance_threshold=2)
        assert metrics["mrr_at_3"] == 0.5  # 1/2

    def test_cold_start_metrics(self) -> None:
        results = [
            EvaluationResult(
                query_id="q1", variant="hybrid_union", rank=1,
                item_id="B1", score=0.9, is_cold_item=True,
            ),
            EvaluationResult(
                query_id="q1", variant="hybrid_union", rank=2,
                item_id="B2", score=0.8, is_cold_item=False,
            ),
        ]
        judgments = {"B1": 3, "B2": 2}
        metrics = compute_query_metrics(results, judgments, k_values=[10], relevance_threshold=2)
        assert metrics["cold_item_count"] == 1
        assert metrics["cold_relevant_rate_at_10"] == 1.0  # 1 cold relevant / 1 cold total


class TestAggregateMetrics:
    def test_basic_aggregation(self) -> None:
        rows = [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8, "query_id": "q1"},
            {"variant": "hybrid_union", "ndcg_at_10": 0.6, "query_id": "q2"},
            {"variant": "title_only", "ndcg_at_10": 0.4, "query_id": "q1"},
        ]
        summaries = aggregate_metrics(rows, ["variant"])
        hybrid = next(s for s in summaries if s["variant"] == "hybrid_union")
        assert hybrid["query_count"] == 2
        assert hybrid["ndcg_at_10"] == 0.7  # (0.8 + 0.6) / 2

    def test_null_handling(self) -> None:
        rows = [
            {"variant": "v1", "ndcg_at_10": None, "query_id": "q1"},
            {"variant": "v1", "ndcg_at_10": 0.5, "query_id": "q2"},
        ]
        summaries = aggregate_metrics(rows, ["variant"])
        assert summaries[0]["ndcg_at_10"] == 0.5
        assert summaries[0]["ndcg_at_10_null_count"] == 1
