from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.indexing import build_item_doc_from_mvp_row


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

