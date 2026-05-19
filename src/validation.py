from __future__ import annotations

import math
from typing import Any

import pandas as pd


MVP_REQUIRED_COLUMNS = [
    "parent_asin",
    "title",
    "store",
    "brand_candidate",
    "brand_source",
    "main_category",
    "category_id",
    "category_path",
    "price_usd",
    "price_vnd",
    "price_parse_status",
    "price_bucket",
    "title_words",
    "description_words",
    "features_words",
    "details_words",
    "combined_words",
    "quality_score",
    "quality_tier",
    "content_richness",
    "description_text",
    "features_text",
    "details_text",
    "product_text_for_llm",
    "primary_image_url",
    "image_urls",
    "images_count",
    "source_category",
]


def validate_required_columns(df: pd.DataFrame, required: list[str] | None = None) -> list[str]:
    required_columns = required or MVP_REQUIRED_COLUMNS
    return [column for column in required_columns if column not in df.columns]


def assert_required_columns(df: pd.DataFrame, required: list[str] | None = None) -> None:
    missing = validate_required_columns(df, required)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


def validate_mvp_dataframe(df: pd.DataFrame, min_combined_words: int = 150) -> dict[str, Any]:
    missing = validate_required_columns(df)
    errors = []
    warnings = []
    if missing:
        errors.append(f"Missing required columns: {missing}")
        return {"ok": False, "errors": errors, "warnings": warnings}
    if len(df) == 0:
        errors.append("MVP dataframe is empty")
        return {"ok": False, "errors": errors, "warnings": warnings, "image_coverage": 0.0}

    if df["parent_asin"].isna().any() or (df["parent_asin"].astype(str).str.strip() == "").any():
        errors.append("parent_asin must be present for all rows")
    if df["parent_asin"].nunique() != len(df):
        errors.append("parent_asin values must be unique")
    if (df["combined_words"] < min_combined_words).any():
        errors.append(f"combined_words must be >= {min_combined_words}")
    if df["price_usd"].isna().any() or (df["price_usd"].astype(float) <= 0).any():
        errors.append("price_usd must be present and non-zero")
    for column in ("title", "store", "main_category", "product_text_for_llm"):
        if df[column].isna().any() or (df[column].astype(str).str.strip() == "").any():
            errors.append(f"{column} must be present for all rows")
    image_coverage = float(df["primary_image_url"].notna().mean()) if len(df) else 0.0
    if image_coverage < 0.95:
        warnings.append(f"Image coverage is {image_coverage:.2%}, below the 95% demo target")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "image_coverage": image_coverage}


def validate_embedding_vector(vector: list[float], dimensions: int = 1024, norm_tolerance: float = 0.01) -> None:
    if len(vector) != dimensions:
        raise ValueError(f"Expected embedding dimension {dimensions}, got {len(vector)}")
    if any(math.isnan(float(value)) for value in vector):
        raise ValueError("Embedding contains NaN")
    if any(math.isinf(float(value)) for value in vector):
        raise ValueError("Embedding contains inf")
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if abs(norm - 1.0) > norm_tolerance:
        raise ValueError(f"Expected normalized embedding norm near 1.0, got {norm:.6f}")
