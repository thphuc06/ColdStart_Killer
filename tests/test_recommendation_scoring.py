from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recommendation.scoring import classify_query_type, get_search_weights, rank_normalize, score_candidate_batch
from src.recommendation.diversity import apply_diversity_rerank
from src.recommendation.explanations import build_result_card


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


def test_non_positive_profile_similarity_does_not_create_a_profile_boost() -> None:
    ranked = score_candidate_batch(
        [{"item_id": "UNRELATED", "profile_score_raw": -0.30}],
        {"profile": 1.0},
    )

    candidate = ranked[0]
    assert candidate["score_breakdown"]["profile_score"] == 0.0
    assert candidate["contributions"]["profile"] == 0.0
    assert candidate["final_score"] == 0.0


def test_profile_reason_requires_weighted_contribution_to_rank() -> None:
    candidate = score_candidate_batch(
        [
            {
                "item_id": "BEAUTY",
                "profile_score_raw": 0.85,
                "profile_interest_label": "gentle skincare",
            }
        ],
        {"profile": 0.0, "quality": 1.0},
    )[0]

    card = build_result_card(
        candidate,
        request_id="req_profile_gate",
        rank_position=1,
        surface="home",
        algorithm_version="algorithm_test",
        ranking_version="ranking_test",
    )

    assert candidate["contributions"]["profile"] == 0.0
    assert "Profile" not in card["reason_badges"]
    assert all("gentle skincare interest" not in reason for reason in card["explanations"])
    assert card["debug"]["profile_interest_label"] == ""


def test_profile_reason_requires_material_contribution_threshold() -> None:
    candidate = score_candidate_batch(
        [
            {
                "item_id": "BEAUTY_LOW_SIGNAL",
                "profile_score_raw": 0.04,
                "profile_interest_label": "gentle skincare",
            }
        ],
        {"profile": 1.0},
    )[0]

    card = build_result_card(
        candidate,
        request_id="req_profile_threshold",
        rank_position=1,
        surface="home",
        algorithm_version="algorithm_test",
        ranking_version="ranking_test",
    )

    assert candidate["contributions"]["profile"] == 0.04
    assert "Profile" not in card["reason_badges"]
    assert all("gentle skincare interest" not in reason for reason in card["explanations"])


def test_primary_reason_uses_largest_material_weighted_contribution() -> None:
    card = build_result_card(
        {
            "item_id": "BEAUTY_PROFILE_PRIMARY",
            "profile_interest_label": "sensitive skin",
            "matched_aspects": ["gentle cleansing"],
            "matched_channels": ["profile", "semantic_neighbor"],
            "candidate_sources": ["profile", "semantic_neighbor"],
            "contributions": {"profile": 0.32, "semantic_neighbor": 0.08, "quality": 0.04},
            "final_score": 0.44,
        },
        request_id="req_primary_profile",
        rank_position=1,
        surface="home",
        algorithm_version="algorithm_test",
        ranking_version="ranking_test",
    )

    assert card["attribution"]["primary_reason_channel"] == "profile"
    assert card["attribution"]["primary_reason_contribution"] == 0.32
    assert card["attribution"]["material_reason_channels"] == ["profile", "semantic_neighbor"]
    assert card["explanations"][0] == "Boosted because it matches your sensitive skin interest."
    assert card["reason_badges"][0] == "Profile"
    assert "Semantic similar" in card["reason_badges"]


def test_raw_evidence_without_material_contribution_does_not_claim_reason() -> None:
    card = build_result_card(
        {
            "item_id": "QUALITY_ONLY",
            "matched_intent": "smartphone display",
            "matched_fact": "AMOLED touchscreen",
            "matched_channels": ["vector", "bm25", "cf"],
            "candidate_sources": ["query_hybrid", "cf", "quality"],
            "cf_evidence": {"support": 3, "cf_score": 0.8},
            "contributions": {"query_hybrid": 0.0, "cf": 0.0, "quality": 0.2},
            "final_score": 0.2,
        },
        request_id="req_generic",
        rank_position=1,
        surface="home",
        algorithm_version="algorithm_test",
        ranking_version="ranking_test",
    )

    assert card["attribution"]["primary_reason_channel"] == "generic"
    assert card["attribution"]["material_reason_channels"] == []
    assert card["explanations"] == ["Recommended from the current ranking blend."]
    assert "Collaborative Filtering" not in card["reason_badges"]
    assert "HyPE semantic" not in card["reason_badges"]
    assert "BM25 fact" not in card["reason_badges"]


def test_forced_cold_insertion_is_explained_without_changing_rerank_policy() -> None:
    candidates = [
        {
            "item_id": "WARM",
            "category_id": "beauty",
            "brand": "Brand",
            "is_cold_item": False,
            "final_score": 0.8,
            "scores": {"final_score": 0.8},
            "score_breakdown": {"final_score": 0.8},
            "contributions": {"quality": 0.8},
        },
        {
            "item_id": "COLD",
            "category_id": "beauty",
            "brand": "NewBrand",
            "is_cold_item": True,
            "interaction_count": 0,
            "final_score": 0.1,
            "scores": {"final_score": 0.1},
            "score_breakdown": {"final_score": 0.1},
            "contributions": {"cold_explore": 0.01},
        },
    ]

    reranked = apply_diversity_rerank(candidates, top_k=1, cold_start_target_rank=1)
    assert reranked[0]["item_id"] == "COLD"
    assert reranked[0]["forced_cold_insertion"] is True
    assert reranked[0]["contributions"]["diversity_adjustment"] == 0.0

    card = build_result_card(
        reranked[0],
        request_id="req_forced_cold",
        rank_position=1,
        surface="home",
        algorithm_version="algorithm_test",
        ranking_version="ranking_test",
    )
    assert card["attribution"]["primary_reason_channel"] == "cold_explore"
    assert card["attribution"]["forced_cold_insertion"] is True
    assert card["explanations"][0] == "Included to ensure newer items receive exploration exposure in this feed."
    assert "Exploration" in card["reason_badges"]
    assert all("HyPE/vector" not in reason and "BM25" not in reason for reason in card["explanations"])


def test_diversity_adjustment_is_included_in_attribution_without_score_change() -> None:
    reranked = apply_diversity_rerank(
        [
            {
                "item_id": "A",
                "category_id": "beauty",
                "brand": "Brand",
                "final_score": 0.8,
                "scores": {"final_score": 0.8},
                "score_breakdown": {"final_score": 0.8},
                "contributions": {"quality": 0.8},
            },
            {
                "item_id": "B",
                "category_id": "beauty",
                "brand": "Brand",
                "final_score": 0.7,
                "scores": {"final_score": 0.7},
                "score_breakdown": {"final_score": 0.7},
                "contributions": {"quality": 0.7},
            },
        ],
        top_k=2,
    )

    assert [item["item_id"] for item in reranked] == ["A", "B"]
    assert reranked[1]["contributions"]["diversity_adjustment"] == -0.035
    assert reranked[1]["final_score"] == 0.665
