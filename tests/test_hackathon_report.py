"""Tests for hackathon impact report generation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.evaluation.hackathon_report import generate_hackathon_report


def test_qualitative_examples_use_highest_delta_and_raw_query() -> None:
    run_data = {
        "config": {"run_id": "demo"},
        "queries": [
            {"query_id": "q1", "raw_query": "vitamin C serum for dark spots"},
            {"query_id": "q2", "raw_query": "USB-C fast charger for iPhone 15"},
            {"query_id": "q3", "raw_query": "kem chống nắng dưới 300k"},
        ],
        "variant_summaries": [
            {"variant": "hybrid_union", "ndcg_at_10": 0.8, "hit_rate_at_10": 1.0, "mrr_at_10": 1.0},
            {"variant": "title_only", "ndcg_at_10": 0.2, "hit_rate_at_10": 0.5, "mrr_at_10": 0.5},
        ],
        "per_query_metrics": [
            {"query_id": "q1", "variant": "hybrid_union", "ndcg_at_10": 0.9},
            {"query_id": "q1", "variant": "title_only", "ndcg_at_10": 0.1},
            {"query_id": "q2", "variant": "hybrid_union", "ndcg_at_10": 0.8},
            {"query_id": "q2", "variant": "title_only", "ndcg_at_10": 0.4},
            {"query_id": "q3", "variant": "hybrid_union", "ndcg_at_10": 0.7},
            {"query_id": "q3", "variant": "title_only", "ndcg_at_10": 0.5},
        ],
        "results": [
            {
                "query_id": "q1",
                "variant": "hybrid_union",
                "rank": 1,
                "title": "Brightening Vitamin C Serum",
                "score": 0.9,
                "matched_intent": "fade dark spots",
                "matched_fact": "contains vitamin C",
            },
            {"query_id": "q1", "variant": "title_only", "rank": 1, "title": "Generic Serum", "score": 0.4},
            {
                "query_id": "q2",
                "variant": "hybrid_union",
                "rank": 1,
                "title": "USB-C PD iPhone Charger",
                "score": 0.8,
                "matched_intent": "fast charge iPhone 15",
                "matched_fact": "USB-C power delivery",
            },
            {"query_id": "q2", "variant": "title_only", "rank": 1, "title": "Cable Organizer", "score": 0.3},
            {
                "query_id": "q3",
                "variant": "hybrid_union",
                "rank": 1,
                "title": "Sunscreen Under 300k",
                "score": 0.7,
                "matched_intent": "budget sunscreen",
                "matched_fact": "price below 300k",
            },
            {"query_id": "q3", "variant": "title_only", "rank": 1, "title": "Body Lotion", "score": 0.2},
        ],
    }

    report = generate_hackathon_report(run_data)

    assert '### Example 1: "vitamin C serum for dark spots"' in report
    assert '### Example 2: "USB-C fast charger for iPhone 15"' in report
    assert '### Example 3: "kem chống nắng dưới 300k"' in report
    assert "Why hybrid is better" in report
    assert "Intent match" in report
    assert "Fact match" in report
