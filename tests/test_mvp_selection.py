from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mvp_selection import add_scoring_columns, build_diverse_subset, build_quality_control_subset


def _row(idx: int, category: str = "All Beauty", combined_words: int = 180, image: bool = True) -> dict:
    return {
        "parent_asin": f"B{idx:04d}",
        "title": f"Product {idx}",
        "store": "Demo Store",
        "brand_candidate": "Demo",
        "brand_source": "store_fallback",
        "main_category": category,
        "category_id": category.lower().replace(" ", "_"),
        "category_path": [category],
        "price_usd": 12.0,
        "price_vnd": 300000,
        "price_parse_status": "parsed",
        "price_bucket": "300k_500k",
        "title_words": 2,
        "description_words": combined_words // 2,
        "features_words": combined_words // 2,
        "details_words": 0,
        "combined_words": combined_words,
        "quality_tier": "tier_B",
        "content_richness": 0.8,
        "description_text": "description " * (combined_words // 2),
        "features_text": "feature " * (combined_words // 2),
        "details_text": "",
        "product_text_for_llm": "Title: Product\nFeatures:\nfeature\nDescription:\ndescription",
        "primary_image_url": "https://example.com/image.jpg" if image else None,
        "image_urls": ["https://example.com/image.jpg"] if image else [],
        "images_count": 1 if image else 0,
        "source_category": category,
    }


def test_add_scoring_columns_quality_score() -> None:
    df = pd.DataFrame([_row(1)])
    scored = add_scoring_columns(df)
    assert "quality_score" in scored.columns
    assert scored.loc[0, "quality_score"] > 0.5


def test_build_quality_control_deduplicates_parent_asin() -> None:
    rows = [_row(1, combined_words=180), _row(1, combined_words=260), _row(2, combined_words=180)]
    df = pd.DataFrame(rows)
    selected = build_quality_control_subset(df, target_n=2)
    assert len(selected) == 2
    assert selected["parent_asin"].nunique() == 2
    assert selected.loc[selected["parent_asin"] == "B0001", "combined_words"].iloc[0] == 260


def test_build_diverse_subset_respects_category_cap() -> None:
    rows = [_row(idx, "All Beauty") for idx in range(20)]
    rows += [_row(100 + idx, "Cell Phones") for idx in range(20)]
    df = pd.DataFrame(rows)
    selected = build_diverse_subset(df, target_n=10, min_combined_words=150, max_per_category=6)
    assert len(selected) == 10
    assert selected["parent_asin"].nunique() == 10
    assert selected.groupby("category_id").size().max() <= 6


def test_build_diverse_subset_keeps_small_categories_first() -> None:
    rows = [_row(idx, "Dominant", combined_words=300) for idx in range(20)]
    rows += [_row(100, "Small One", combined_words=160), _row(101, "Small Two", combined_words=160)]
    df = pd.DataFrame(rows)
    selected = build_diverse_subset(df, target_n=8, min_combined_words=150, max_per_category=6)
    categories = set(selected["category_id"])
    assert "small_one" in categories
    assert "small_two" in categories
    assert selected.groupby("category_id").size().max() <= 6
