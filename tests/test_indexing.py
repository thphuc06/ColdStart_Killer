from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.indexing import build_item_doc_from_mvp_row, first_uninserted_index_from_mongodb, index_items_from_dataframe


def test_build_item_doc_preserves_component_source_text() -> None:
    row = {
        "parent_asin": "B001",
        "title": "Hydrating Facial Cleanser",
        "store": "Demo",
        "brand_candidate": "Demo",
        "brand_source": "store_fallback",
        "main_category": "All Beauty",
        "category_id": "all_beauty",
        "category_path": ["All Beauty"],
        "price_usd": 12.0,
        "price_vnd": 300000,
        "price_parse_status": "parsed",
        "price_bucket": "300k_500k",
        "title_words": 3,
        "description_words": 8,
        "features_words": 6,
        "details_words": 4,
        "combined_words": 18,
        "quality_score": 0.8,
        "quality_tier": "tier_B",
        "content_richness": 0.8,
        "description_text": "A gentle cleanser for daily use.",
        "features_text": "Fragrance free\nFor sensitive skin",
        "details_text": "Size: 200 ml",
        "product_text_for_llm": "Title: Hydrating Facial Cleanser",
        "primary_image_url": "https://example.com/image.jpg",
        "image_urls": ["https://example.com/image.jpg"],
        "images_count": 1,
        "source_category": "All_Beauty",
    }
    item = build_item_doc_from_mvp_row(row)
    assert item["source_text"]["description_text"] == "A gentle cleanser for daily use."
    assert "Fragrance free" in item["source_text"]["features_text"]
    assert item["source_text"]["details_text"] == "Size: 200 ml"


def test_index_items_from_dataframe_supports_start_index(monkeypatch) -> None:
    rows = []
    for idx in range(5):
        row = {
            "parent_asin": f"B00{idx}",
            "title": f"Product {idx}",
            "store": "Demo",
            "brand_candidate": "Demo",
            "brand_source": "store_fallback",
            "main_category": "All Beauty",
            "category_id": "all_beauty",
            "category_path": ["All Beauty"],
            "price_usd": 12.0,
            "price_vnd": 300000,
            "price_parse_status": "parsed",
            "price_bucket": "300k_500k",
            "title_words": 2,
            "description_words": 8,
            "features_words": 6,
            "details_words": 4,
            "combined_words": 18,
            "quality_score": 0.8,
            "quality_tier": "tier_B",
            "content_richness": 0.8,
            "description_text": "A gentle cleanser for daily use.",
            "features_text": "Fragrance free",
            "details_text": "Size: 200 ml",
            "product_text_for_llm": f"Title: Product {idx}",
            "primary_image_url": "https://example.com/image.jpg",
            "image_urls": ["https://example.com/image.jpg"],
            "images_count": 1,
            "source_category": "All_Beauty",
        }
        rows.append(row)

    seen_item_ids = []

    def fake_props(item):
        seen_item_ids.append(item["_id"])
        return [{"proposition_type": "spec", "raw_text": "Fact", "confidence": 0.8, "source_field": "mixed"}]

    monkeypatch.setattr("src.indexing.extract_propositions_llm", fake_props)
    monkeypatch.setattr(
        "src.indexing.generate_hype_queries_llm",
        lambda item, props: [{"aspect": "function", "raw_text": "query", "confidence": 0.8}],
    )
    monkeypatch.setattr("src.indexing.embed_texts", lambda texts: [[0.0] * 1024 for _ in texts])

    result = index_items_from_dataframe(
        pd.DataFrame(rows),
        start_index=2,
        limit=2,
        dry_run=True,
        sleep_seconds=0,
    )

    assert seen_item_ids == ["B002", "B003"]
    assert result["start_index"] == 2
    assert result["end_index_exclusive"] == 4
    assert result["item_count"] == 2


def test_first_uninserted_index_from_mongodb_stops_at_first_gap(monkeypatch) -> None:
    df = pd.DataFrame({"parent_asin": ["B001", "B002", "B003", "B004"]})

    class FakeCollection:
        def find(self, query, projection):
            return [{"_id": "B001"}, {"_id": "B002"}, {"_id": "B004"}]

    monkeypatch.setattr("src.indexing.get_items_collection", lambda: FakeCollection())

    assert first_uninserted_index_from_mongodb(df) == 2

