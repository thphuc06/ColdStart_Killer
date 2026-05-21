from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.retrieval_output import REQUIRED_OUTPUT_FIELDS
from src.search_pipeline import atlas_search_compound, bm25_subpipeline, build_union_with_pipeline, run_search


MOCK_FIXTURE = {
    "original_query": "gift for oily skin under 300k",
    "hype_search_query_en": "birthday skincare gift for oily skin",
    "bm25_search_query_en": "skincare gift oily skin moisturizer toner serum",
    "hard_filters": {
        "price_max": 300000,
        "in_stock": True,
        "is_cold_item": True,
        "price_bucket": "100k_300k",
    },
    "query_embedding": [0.0] * 1024,
}


class MockCollection:
    def __init__(self) -> None:
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return [
            {
                "item_id": "B001",
                "title": "Hydrating Gel Moisturizer",
                "score": 0.92,
                "matched_intent": "birthday skincare gift for oily skin",
                "matched_fact": "The moisturizer is suitable for oily skin.",
                "rank_vector": 3,
                "rank_bm25": 7,
                "fusion_score": 0.85,
                "is_cold_item": True,
                "interaction_count": 0,
                "debug": {
                    "raw_vector_score": 0.78,
                    "raw_bm25_score": 11.2,
                },
            }
        ]


def test_build_union_with_pipeline_returns_list() -> None:
    pipeline = build_union_with_pipeline(MOCK_FIXTURE, top_k=10)
    assert isinstance(pipeline, list)
    assert pipeline
    assert "$vectorSearch" in pipeline[0]
    assert any("$unionWith" in stage for stage in pipeline)


def test_atlas_search_compound_does_not_use_exact_language_filter() -> None:
    compound = atlas_search_compound("fast charger", {"in_stock": True})
    assert "filter" not in compound


def test_bm25_subpipeline_filters_retrieval_units_after_search() -> None:
    pipeline = bm25_subpipeline("fast charger", {"in_stock": True}, channel_limit=5)
    assert pipeline[0]["$search"]["index"] == "text_index"
    assert pipeline[1] == {"$match": {"unit_type": "proposition", "language": "en", "in_stock": True}}
    assert pipeline[2] == {"$limit": 5}


def test_run_search_with_mock_collection_returns_required_output_fields() -> None:
    collection = MockCollection()
    results = run_search(MOCK_FIXTURE, top_k=10, mode="unionWith", collection=collection)
    assert isinstance(results, list)
    assert results
    for field in REQUIRED_OUTPUT_FIELDS:
        assert field in results[0]
    assert results[0]["cold_start_note"]
    assert collection.pipeline is not None
