from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from .dataset_loading import MAX_PER_CATEGORY, MIN_COMBINED_WORDS, MVP_TARGET_N, load_target_metadata
from .normalize_amazon import normalize_record
from .config import PROJECT_ROOT
from .utils import ensure_directory, write_json
from .validation import MVP_REQUIRED_COLUMNS, validate_mvp_dataframe


ANALYSIS_DIR = PROJECT_ROOT / "analysis"
CONTROL_CSV = ANALYSIS_DIR / "mvp_3000_items.csv"
DIVERSE_CSV = ANALYSIS_DIR / "mvp_3000_items_diverse.csv"
SELECTION_REPORT_JSON = ANALYSIS_DIR / "mvp_3000_selection_report.json"
DATA_AUDIT_MD = ANALYSIS_DIR / "data_audit_report.md"
DATA_PROFILE_JSON = ANALYSIS_DIR / "data_profile.json"
NEEDS_ENRICHMENT_CSV = ANALYSIS_DIR / "needs_enrichment_items.csv"


def _string_present(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().ne("")


def add_scoring_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["has_description"] = out["description_words"].fillna(0).astype(float) > 0
    out["has_features"] = out["features_words"].fillna(0).astype(float) > 0
    out["has_details"] = out["details_words"].fillna(0).astype(float) > 0
    out["price_present"] = out["price_usd"].notna() & (out["price_usd"].astype(float) > 0)
    out["images_present"] = out["primary_image_url"].notna() & _string_present(out["primary_image_url"])
    out["store_present_score"] = _string_present(out["store"])
    out["quality_score"] = (
        (out["combined_words"].fillna(0).astype(float) / 300).clip(upper=1.0) * 0.35
        + out["has_description"].astype(float) * 0.20
        + out["has_features"].astype(float) * 0.15
        + out["has_details"].astype(float) * 0.10
        + out["price_present"].astype(float) * 0.10
        + out["images_present"].astype(float) * 0.05
        + out["store_present_score"].astype(float) * 0.05
    ).round(6)
    return out


def rank_sort(df: pd.DataFrame) -> pd.DataFrame:
    out = add_scoring_columns(df)
    return out.sort_values(
        by=["quality_score", "images_present", "combined_words", "content_richness", "title_words"],
        ascending=[False, False, False, False, False],
        kind="mergesort",
    ).reset_index(drop=True)


def _eligible(df: pd.DataFrame, min_combined_words: int) -> pd.DataFrame:
    ranked = rank_sort(df)
    mask = (
        _string_present(ranked["parent_asin"])
        & _string_present(ranked["title"])
        & _string_present(ranked["store"])
        & _string_present(ranked["main_category"])
        & ranked["price_usd"].notna()
        & (ranked["price_usd"].astype(float) > 0)
        & ((ranked["description_words"].fillna(0) > 0) | (ranked["features_words"].fillna(0) > 0))
        & (ranked["combined_words"].fillna(0).astype(int) >= min_combined_words)
        & _string_present(ranked["product_text_for_llm"])
    )
    eligible = ranked.loc[mask].copy()
    eligible = eligible.sort_values(
        by=["parent_asin", "combined_words", "quality_score"],
        ascending=[True, False, False],
        kind="mergesort",
    ).drop_duplicates("parent_asin", keep="first")
    return rank_sort(eligible)


def _prefer_image_coverage(
    selected: pd.DataFrame,
    eligible: pd.DataFrame,
    target_n: int,
    protected_parent_asins: set[str] | None = None,
) -> pd.DataFrame:
    if selected.empty:
        return selected
    target_images = math.ceil(min(len(selected), target_n) * 0.95)
    current_images = int(selected["images_present"].sum())
    if current_images >= target_images:
        return selected

    image_pool = eligible[eligible["images_present"] & ~eligible["parent_asin"].isin(selected["parent_asin"])]
    if current_images + len(image_pool) < target_images:
        return selected

    protected_parent_asins = protected_parent_asins or set()
    replaceable_mask = ~selected["images_present"] & ~selected["parent_asin"].astype(str).isin(protected_parent_asins)
    no_image_selected = selected[replaceable_mask].sort_values(
        by=["quality_score", "combined_words"], ascending=[True, True]
    )
    if no_image_selected.empty:
        return selected
    selected = selected.copy()
    replacements_needed = min(target_images - current_images, len(no_image_selected))
    replacements = image_pool.head(replacements_needed)
    drop_ids = set(no_image_selected.head(replacements_needed)["parent_asin"])
    selected = selected[~selected["parent_asin"].isin(drop_ids)]
    selected = pd.concat([selected, replacements], ignore_index=True)
    return rank_sort(selected).head(target_n)


def build_quality_control_subset(df: pd.DataFrame, target_n: int = MVP_TARGET_N) -> pd.DataFrame:
    selected_threshold = MIN_COMBINED_WORDS
    warnings = []
    selected = pd.DataFrame()
    for threshold in [MIN_COMBINED_WORDS, 120, 100, 80]:
        eligible = _eligible(df, threshold)
        selected = eligible.head(target_n).copy()
        selected = _prefer_image_coverage(selected, eligible, target_n)
        selected_threshold = threshold
        if len(selected) >= target_n:
            break
        warnings.append(f"Only {len(selected)} rows available at threshold {threshold}")
    selected.attrs["selected_threshold"] = selected_threshold
    selected.attrs["warnings"] = warnings
    return selected.reset_index(drop=True)


def build_diverse_subset(
    df: pd.DataFrame,
    target_n: int = MVP_TARGET_N,
    min_combined_words: int = MIN_COMBINED_WORDS,
    max_per_category: int = MAX_PER_CATEGORY,
) -> pd.DataFrame:
    selected_threshold = min_combined_words
    warnings = []
    final = pd.DataFrame()

    thresholds = [min_combined_words, 120, 100, 80]
    thresholds = list(dict.fromkeys(thresholds))
    for threshold in thresholds:
        eligible = _eligible(df, threshold)
        if eligible.empty:
            final = eligible.copy()
            selected_threshold = threshold
            warnings.append(f"No rows available at threshold {threshold}")
            continue
        category_counts = eligible["category_id"].value_counts()
        small_categories = set(category_counts[category_counts <= max_per_category].index)
        large_categories = set(category_counts[category_counts > max_per_category].index)

        small_first = rank_sort(eligible[eligible["category_id"].isin(small_categories)])
        if len(small_first) >= target_n:
            final = small_first.head(target_n).copy()
            protected_ids = set()
        else:
            large_parts = []
            for _, group in eligible[eligible["category_id"].isin(large_categories)].groupby("category_id", sort=False):
                large_parts.append(rank_sort(group).head(max_per_category))
            large_pool = rank_sort(pd.concat(large_parts, ignore_index=True)) if large_parts else pd.DataFrame()
            remaining_slots = target_n - len(small_first)
            large_selected = large_pool.head(remaining_slots).copy()
            final = pd.concat([small_first, large_selected], ignore_index=True)
            final = final.drop_duplicates("parent_asin", keep="first")
            protected_ids = set(small_first["parent_asin"].astype(str))

        final = _prefer_image_coverage(final, eligible, target_n, protected_parent_asins=protected_ids)
        selected_threshold = threshold
        if len(final) >= target_n:
            break
        warnings.append(f"Only {len(final)} rows available at threshold {threshold}")

    if len(final) < target_n:
        warnings.append(f"Saved best available {len(final)} rows; target was {target_n}")

    final.attrs["selected_threshold"] = selected_threshold
    final.attrs["warnings"] = warnings
    return final.reset_index(drop=True)


def category_summary(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    grouped = (
        df.groupby(["category_id", "main_category"], dropna=False)
        .agg(
            rows=("parent_asin", "count"),
            avg_quality_score=("quality_score", "mean"),
            avg_combined_words=("combined_words", "mean"),
            image_coverage=("primary_image_url", lambda s: float(s.notna().mean())),
        )
        .reset_index()
        .sort_values(["rows", "avg_quality_score"], ascending=[False, False])
    )
    return [
        {
            "category_id": str(row["category_id"]),
            "main_category": str(row["main_category"]),
            "rows": int(row["rows"]),
            "avg_quality_score": round(float(row["avg_quality_score"]), 6),
            "avg_combined_words": round(float(row["avg_combined_words"]), 2),
            "image_coverage": round(float(row["image_coverage"]), 6),
        }
        for _, row in grouped.iterrows()
    ]


def _csv_columns(df: pd.DataFrame) -> list[str]:
    return [column for column in MVP_REQUIRED_COLUMNS if column in df.columns]


def _profile_dataframe(df: pd.DataFrame, load_report: dict[str, Any]) -> dict[str, Any]:
    if df.empty:
        return {"rows": 0, "load_report": load_report}
    return {
        "rows": int(len(df)),
        "unique_parent_asin": int(df["parent_asin"].nunique()),
        "category_count": int(df["category_id"].nunique()),
        "price_coverage": float(df["price_usd"].notna().mean()),
        "image_coverage": float(df["primary_image_url"].notna().mean()),
        "description_coverage": float((df["description_words"] > 0).mean()),
        "features_coverage": float((df["features_words"] > 0).mean()),
        "avg_combined_words": float(df["combined_words"].mean()),
        "quality_tiers": {str(k): int(v) for k, v in df["quality_tier"].value_counts(dropna=False).items()},
        "source_categories": {str(k): int(v) for k, v in df["source_category"].value_counts(dropna=False).items()},
        "load_report": load_report,
    }


def _audit_markdown(
    normalized_df: pd.DataFrame,
    control_df: pd.DataFrame,
    diverse_df: pd.DataFrame,
    load_report: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    diverse_threshold = diverse_df.attrs.get("selected_threshold", MIN_COMBINED_WORDS)
    image_coverage = float(diverse_df["primary_image_url"].notna().mean()) if len(diverse_df) else 0.0
    failures = load_report.get("failures", [])
    failure_lines = "\n".join(f"- {item['source']}: {item['error']}" for item in failures) or "- None recorded"
    warnings = validation.get("warnings", []) + diverse_df.attrs.get("warnings", [])
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) or "- None"
    return f"""# ColdStart Killer Data Audit Report

## Source Loading

- Combined raw records: {load_report.get("row_counts", {}).get("combined", 0)}
- All_Beauty source: {load_report.get("sources", {}).get("all_beauty")}
- Cell Phones source: {load_report.get("sources", {}).get("cell_phones")}

## Failures and Fallbacks

{failure_lines}

## Normalized Profile

- Normalized rows: {len(normalized_df)}
- Unique parent_asin: {normalized_df["parent_asin"].nunique() if len(normalized_df) else 0}
- Category count: {normalized_df["category_id"].nunique() if len(normalized_df) else 0}

## MVP Outputs

- Quality-control rows: {len(control_df)}
- Diverse rows: {len(diverse_df)}
- Diverse unique parent_asin: {diverse_df["parent_asin"].nunique() if len(diverse_df) else 0}
- Selected combined-word threshold: {diverse_threshold}
- Image coverage: {image_coverage:.2%}

## Validation

- OK: {validation.get("ok")}
- Errors: {json.dumps(validation.get("errors", []), ensure_ascii=False)}

## Warnings

{warning_lines}

Reviews are optional audit metadata only in this phase and are not used as retrieval features.
"""


def write_mvp_outputs(
    normalized_df: pd.DataFrame,
    control_df: pd.DataFrame,
    diverse_df: pd.DataFrame,
    load_report: dict[str, Any],
    output_dir: str | Path = ANALYSIS_DIR,
) -> None:
    output_dir = ensure_directory(output_dir)
    control_path = output_dir / CONTROL_CSV.name
    diverse_path = output_dir / DIVERSE_CSV.name
    report_path = output_dir / SELECTION_REPORT_JSON.name
    audit_path = output_dir / DATA_AUDIT_MD.name
    profile_path = output_dir / DATA_PROFILE_JSON.name
    enrichment_path = output_dir / NEEDS_ENRICHMENT_CSV.name

    control_df.to_csv(control_path, index=False, columns=_csv_columns(control_df))
    diverse_df.to_csv(diverse_path, index=False, columns=_csv_columns(diverse_df))

    needs_enrichment = normalized_df[normalized_df["needs_enrichment"] == True].copy()
    needs_enrichment.to_csv(enrichment_path, index=False)

    selected_threshold = diverse_df.attrs.get("selected_threshold", MIN_COMBINED_WORDS)
    validation = validate_mvp_dataframe(diverse_df, min_combined_words=selected_threshold)
    report = {
        "target_n": MVP_TARGET_N,
        "quality_control_rows": int(len(control_df)),
        "diverse_rows": int(len(diverse_df)),
        "diverse_unique_parent_asin": int(diverse_df["parent_asin"].nunique()) if len(diverse_df) else 0,
        "selected_threshold": selected_threshold,
        "max_per_category": MAX_PER_CATEGORY,
        "image_coverage": float(diverse_df["primary_image_url"].notna().mean()) if len(diverse_df) else 0.0,
        "category_summary": category_summary(diverse_df),
        "warnings": control_df.attrs.get("warnings", []) + diverse_df.attrs.get("warnings", []) + validation["warnings"],
        "validation": validation,
        "load_report": load_report,
    }
    write_json(report_path, report)
    write_json(profile_path, _profile_dataframe(normalized_df, load_report))
    audit_path.write_text(
        _audit_markdown(normalized_df, control_df, diverse_df, load_report, validation),
        encoding="utf-8",
    )


def build_3k_mvp_dataset() -> dict:
    records, load_report = load_target_metadata()
    normalized = []
    for record in records:
        category_key = record.get("_source_category") or record.get("main_category") or "unknown"
        normalized.append(normalize_record(record, category_key=category_key))
    normalized_df = pd.DataFrame(normalized)
    if normalized_df.empty:
        ensure_directory(ANALYSIS_DIR)
        write_json(SELECTION_REPORT_JSON, {"target_n": MVP_TARGET_N, "diverse_rows": 0, "load_report": load_report})
        return {"ok": False, "message": "No records loaded", "load_report": load_report}

    normalized_df = add_scoring_columns(normalized_df)
    control_df = build_quality_control_subset(normalized_df, target_n=MVP_TARGET_N)
    diverse_df = build_diverse_subset(
        normalized_df,
        target_n=MVP_TARGET_N,
        min_combined_words=MIN_COMBINED_WORDS,
        max_per_category=MAX_PER_CATEGORY,
    )
    write_mvp_outputs(normalized_df, control_df, diverse_df, load_report)
    return {
        "ok": len(diverse_df) > 0,
        "normalized_rows": len(normalized_df),
        "quality_control_rows": len(control_df),
        "diverse_rows": len(diverse_df),
        "selected_threshold": diverse_df.attrs.get("selected_threshold", MIN_COMBINED_WORDS),
        "image_coverage": float(diverse_df["primary_image_url"].notna().mean()) if len(diverse_df) else 0.0,
        "outputs": {
            "control_csv": str(CONTROL_CSV),
            "diverse_csv": str(DIVERSE_CSV),
            "report_json": str(SELECTION_REPORT_JSON),
            "audit_md": str(DATA_AUDIT_MD),
        },
    }
