from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.schemas import (
    ClickstreamEventDocument,
    RecommendationLogDocument,
    UserItemSignalDocument,
    UserProfileDocument,
)
from src.recommendation.schemas import (
    EMBEDDING_DIM,
    ItemHypeProfileDocument,
    ItemItemCFEdgeDocument,
    ItemSemanticNeighborsDocument,
    SemanticNeighbor,
)


def test_recommendation_log_contract_accepts_snapshot_fields() -> None:
    log = RecommendationLogDocument(
        request_id="req_001",
        surface="search",
        user_id_hash="u_demo",
        session_id="sess_001",
        algorithm_version="rec_v1_profile_cf_hype",
        ranking_version="rank_v1_default_weights",
        query={"query_type": "specific", "query_embedding": [0.0] * EMBEDDING_DIM},
        item_id="B001",
        rank_position=1,
        attribution={
            "matched_interest_embedding": [0.0] * EMBEDDING_DIM,
            "matched_neighbor_embedding": [0.0] * EMBEDDING_DIM,
            "primary_reason_channel": "profile",
            "primary_reason_contribution": 0.24,
            "material_reason_channels": ["profile", "semantic_neighbor"],
            "forced_cold_insertion": False,
        },
    )
    dumped = log.model_dump(by_alias=True)
    assert dumped["request_id"] == "req_001"
    assert dumped["scores"]["final_score"] == 0.0
    assert dumped["attribution"]["candidate_sources"] == []
    assert dumped["attribution"]["primary_reason_channel"] == "profile"
    assert dumped["attribution"]["material_reason_channels"] == ["profile", "semantic_neighbor"]
    assert len(dumped["query"]["query_embedding"]) == EMBEDDING_DIM
    assert dumped["is_synthetic"] is False


def test_clickstream_event_contract_supports_impression_idempotency_key() -> None:
    event = ClickstreamEventDocument(
        event_id="evt_001",
        idempotency_key="imp:req_001:B001",
        request_id="req_001",
        user_id_hash="u_demo",
        session_id="sess_001",
        surface="home",
        event_type="impression",
        item_id="B001",
    )
    dumped = event.model_dump(by_alias=True)
    assert dumped["event_type"] == "impression"
    assert dumped["processed"] is False
    assert dumped["idempotency_key"] == "imp:req_001:B001"


def test_clickstream_event_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        ClickstreamEventDocument(
            event_id="evt_001",
            user_id_hash="u_demo",
            session_id="sess_001",
            surface="home",
            event_type="double_click",
            item_id="B001",
        )


def test_user_item_signal_and_profile_contracts_are_behavior_derived_shapes() -> None:
    signal = UserItemSignalDocument(user_id_hash="u_demo", item_id="B001", implicit_score=2.5)
    profile = UserProfileDocument(user_id_hash="u_demo", profile_status="warming")
    assert signal.preference is False
    assert signal.event_counts.click == 0
    assert signal.derivation.model_version == ""
    assert profile.profile_quality.num_events == 0
    assert profile.interest_vectors == []
    assert profile.derivation.partial_build is False


def test_item_hype_profile_validates_embedding_dimension_and_finiteness() -> None:
    profile = ItemHypeProfileDocument(
        item_id="B001",
        item_semantic_embedding=[0.0] * EMBEDDING_DIM,
        num_hype_units=5,
    )
    assert len(profile.item_semantic_embedding) == EMBEDDING_DIM

    with pytest.raises(ValidationError):
        ItemHypeProfileDocument(item_id="B001", item_semantic_embedding=[0.0] * 10)

    bad_embedding = [0.0] * EMBEDDING_DIM
    bad_embedding[3] = float("nan")
    with pytest.raises(ValidationError):
        ItemHypeProfileDocument(item_id="B001", item_semantic_embedding=bad_embedding)


def test_recommendation_neighbor_and_cf_edge_contracts_are_distinct() -> None:
    semantic_neighbors = ItemSemanticNeighborsDocument(
        item_id="B001",
        neighbors=[SemanticNeighbor(neighbor_item_id="B002", neighbor_score=0.84)],
    )
    cf_edge = ItemItemCFEdgeDocument(
        item_id="B001",
        neighbor_item_id="B002",
        cf_score=0.61,
        support=3,
        co_click_count=2,
    )
    assert semantic_neighbors.neighbors[0].source == "hype_unit_vector_search"
    assert cf_edge.support == 3
    assert "Users who interacted" in cf_edge.explanation
    assert cf_edge.derivation.model_version == ""
