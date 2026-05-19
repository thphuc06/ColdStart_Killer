from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.validation import MVP_REQUIRED_COLUMNS, validate_mvp_dataframe, validate_required_columns


def _valid_row() -> dict:
    row = {column: "" for column in MVP_REQUIRED_COLUMNS}
    row.update(
        {
            "parent_asin": "B001",
            "title": "Good product",
            "store": "Demo Store",
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
            "description_words": 80,
            "features_words": 80,
            "details_words": 0,
            "combined_words": 160,
            "quality_score": 0.8,
            "quality_tier": "tier_B",
            "content_richness": 0.8,
            "description_text": "description",
            "features_text": "features",
            "details_text": "",
            "product_text_for_llm": "Title: Good product\nDescription: description",
            "primary_image_url": "https://example.com/image.jpg",
            "image_urls": ["https://example.com/image.jpg"],
            "images_count": 1,
            "source_category": "All_Beauty",
        }
    )
    return row


def test_validate_required_columns_detects_missing() -> None:
    df = pd.DataFrame([{"parent_asin": "B001"}])
    missing = validate_required_columns(df)
    assert "title" in missing


def test_validate_mvp_dataframe_accepts_valid_row() -> None:
    df = pd.DataFrame([_valid_row()])
    result = validate_mvp_dataframe(df, min_combined_words=150)
    assert result["ok"]
    assert not result["errors"]


def test_validate_mvp_dataframe_rejects_empty_product_text() -> None:
    row = _valid_row()
    row["product_text_for_llm"] = ""
    df = pd.DataFrame([row])
    result = validate_mvp_dataframe(df, min_combined_words=150)
    assert not result["ok"]
    assert any("product_text_for_llm" in error for error in result["errors"])


def test_validate_mvp_dataframe_rejects_empty_dataframe() -> None:
    df = pd.DataFrame(columns=MVP_REQUIRED_COLUMNS)
    result = validate_mvp_dataframe(df, min_combined_words=150)
    assert not result["ok"]
    assert any("empty" in error for error in result["errors"])
