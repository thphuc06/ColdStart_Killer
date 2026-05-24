from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def apply_diversity_rerank(
    candidates: list[dict[str, Any]],
    *,
    top_k: int,
    max_per_category: int = 5,
    max_per_brand: int = 3,
    cold_start_target_rank: int = 10,
) -> list[dict[str, Any]]:
    if top_k <= 0 or not candidates:
        return []

    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    brand_counts: dict[str, int] = {}

    for candidate in candidates:
        row = dict(candidate)
        category_id = str(row.get("category_id") or "")
        brand = str(row.get("brand") or "")
        category_count = category_counts.get(category_id, 0)
        brand_count = brand_counts.get(brand, 0)
        diversity_adjustment = round(-0.02 * category_count - 0.015 * brand_count, 6)

        row.setdefault("scores", {})
        row.setdefault("score_breakdown", {})
        row["scores"]["diversity_adjustment"] = diversity_adjustment
        row["score_breakdown"]["diversity_adjustment"] = diversity_adjustment
        row["final_score"] = round(_safe_float(row.get("final_score"), 0.0) + diversity_adjustment, 6)
        row["scores"]["final_score"] = row["final_score"]
        row["score_breakdown"]["final_score"] = row["final_score"]

        if category_id and category_count >= max_per_category:
            deferred.append(row)
            continue
        if brand and brand_count >= max_per_brand:
            deferred.append(row)
            continue

        selected.append(row)
        if category_id:
            category_counts[category_id] = category_count + 1
        if brand:
            brand_counts[brand] = brand_count + 1
        if len(selected) >= top_k:
            break

    if len(selected) < top_k:
        for row in deferred:
            selected.append(row)
            if len(selected) >= top_k:
                break

    selected = selected[:top_k]
    check_top = min(cold_start_target_rank, len(selected))
    has_cold_in_top = any(bool(row.get("is_cold_item")) for row in selected[:check_top])
    if not has_cold_in_top:
        cold_candidate = next(
            (row for row in candidates if bool(row.get("is_cold_item")) and row.get("item_id") not in {item.get("item_id") for item in selected[:check_top]}),
            None,
        )
        if cold_candidate is not None and selected:
            insert_at = max(0, check_top - 1)
            replacement = dict(cold_candidate)
            replacement.setdefault("scores", {})
            replacement.setdefault("score_breakdown", {})
            replacement["scores"]["diversity_adjustment"] = replacement["scores"].get("diversity_adjustment", 0.0)
            replacement["score_breakdown"]["diversity_adjustment"] = replacement["score_breakdown"].get(
                "diversity_adjustment", 0.0
            )
            selected.insert(insert_at, replacement)
            deduped: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for row in selected:
                item_id = str(row.get("item_id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                deduped.append(row)
                if len(deduped) >= top_k:
                    break
            selected = deduped

    return selected[:top_k]