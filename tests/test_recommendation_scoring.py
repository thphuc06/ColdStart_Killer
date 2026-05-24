from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation.scoring import classify_query_type, get_search_weights, rank_normalize, score_candidate_batch


def test_rank_normalize_assigns_descending_reciprocal_ranks() -> None:
    assert rank_normalize([0.9, 0.1, 0.5]) == [1.0, 0.333333, 0.5]
    assert rank_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


def test_classify_query_type_matches_phase9_heuristics() -> None:
    assert classify_query_type("gift ideas") == "exploratory"
    assert classify_query_type("wireless charger under 300k iphone") == "constraint_rich"
    assert classify_query_type("samsung galaxy s22 clear case") == "specific"
    assert classify_query_type("phone accessories") == "broad"
    assert classify_query_type("moisturizing cream dry skin") == "normal"


def test_specific_query_weight_keeps_query_relevance_above_profile_bias() -> None:
    candidates = [
        {
            "item_id": "PHONE_CASE",
            "query_hybrid_score_raw": 0.95,
            "profile_score_raw": -0.30,
            "metadata_score_raw": 0.40,
        },
        {
            "item_id": "SKINCARE",
            "query_hybrid_score_raw": 0.20,
            "profile_score_raw": 0.95,
            "metadata_score_raw": 0.40,
        },
    ]

    ranked = score_candidate_batch(candidates, get_search_weights("specific"))

    assert [candidate["item_id"] for candidate in ranked] == ["PHONE_CASE", "SKINCARE"]
    assert ranked[0]["scores"]["query_hybrid_score"] > ranked[1]["scores"]["query_hybrid_score"]
    assert ranked[0]["final_score"] > ranked[1]["final_score"]


def test_score_candidate_batch_keeps_raw_and_normalized_breakdown() -> None:
    ranked = score_candidate_batch(
        [
            {
                "item_id": "A",
                "semantic_neighbor_score_raw": 0.9,
                "item_item_cf_score_raw": 0.5,
                "profile_score_raw": 0.6,
                "metadata_score_raw": 0.4,
                "cold_start_boost_raw": 0.2,
                "quality_score_raw": 0.7,
            }
        ],
        {"semantic_neighbor": 0.5, "cf": 0.2, "profile": 0.1, "metadata": 0.1, "quality": 0.1},
    )

    breakdown = ranked[0]["score_breakdown"]
    assert breakdown["semantic_neighbor_score_raw"] == 0.9
    assert breakdown["semantic_neighbor_score"] == 1.0
    assert breakdown["item_item_cf_score_raw"] == 0.5
    assert breakdown["item_item_cf_score"] == 1.0
    assert breakdown["final_score"] == ranked[0]["final_score"]