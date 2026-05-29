"""IR evaluation metrics for ColdStart_Killer.

Deterministic computation of NDCG, Precision, Recall, MRR, HitRate,
and cold-start quality metrics.

Import safety: no side effects at import time.
"""

from __future__ import annotations

import math
import random
from statistics import median
from typing import Any

from .contracts import EvaluationResult


DEFAULT_VARIANT_COMPARISONS: tuple[tuple[str, str], ...] = (
    ("hybrid_union", "title_only"),
    ("hybrid_union", "vector_only"),
    ("hybrid_union", "bm25_only"),
    ("hybrid_union", "hybrid_no_cold_boost"),
)

DEFAULT_COMPARISON_METRICS: tuple[str, ...] = (
    "ndcg_at_10",
    "recall_at_10",
    "mrr_at_10",
    "cold_relevant_rate_at_10",
)


def binary_relevant(relevance: int, threshold: int = 2) -> bool:
    """Return True if relevance meets or exceeds threshold."""
    return relevance >= threshold


def dcg(relevances: list[int]) -> float:
    """Compute Discounted Cumulative Gain."""
    total = 0.0
    for i, rel in enumerate(relevances):
        total += rel / math.log2(i + 2)  # i+2 because rank is 1-indexed
    return total


def ndcg(relevances: list[int], ideal: list[int]) -> float | None:
    """Compute Normalized DCG. Returns None if ideal DCG is zero."""
    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0.0:
        return None
    return dcg(relevances) / ideal_dcg


def compute_query_metrics(
    ranked_results: list[EvaluationResult],
    judgments: dict[str, int],
    k_values: list[int],
    relevance_threshold: int = 2,
) -> dict[str, float | int | bool | None]:
    """Compute all IR metrics for a single query across all K values.

    Args:
        ranked_results: Results sorted by rank (ascending).
        judgments: {item_id: relevance} for this query.
        k_values: List of K values to compute metrics at.
        relevance_threshold: Binary relevance threshold.

    Returns:
        Dict with metrics for each K, plus aggregated stats.
    """
    metrics: dict[str, Any] = {}

    # Judgment coverage stats
    judged_count = sum(1 for r in ranked_results if r.item_id in judgments)
    unjudged_count = len(ranked_results) - judged_count
    metrics["result_count"] = len(ranked_results)
    metrics["judged_result_count"] = judged_count
    metrics["unjudged_result_count"] = unjudged_count
    metrics["has_judgments"] = bool(judgments)

    # Cold-start stats
    cold_items = [r for r in ranked_results if r.is_cold_item is True]
    unknown_cold = [r for r in ranked_results if r.is_cold_item is None]
    metrics["cold_item_count"] = len(cold_items)
    metrics["unknown_cold_status_count"] = len(unknown_cold)

    # Per-query judgment coverage
    metrics["query_judgment_coverage_rate"] = round(
        judged_count / len(ranked_results), 4
    ) if ranked_results else None
    metrics["is_fully_judged"] = (unjudged_count == 0) if ranked_results else False
    metrics["has_positive_judgment"] = any(
        judgments.get(r.item_id, 0) >= relevance_threshold for r in ranked_results
    )

    # All known relevance values for ideal ranking
    all_relevances = sorted(judgments.values(), reverse=True)

    for k in sorted(k_values):
        top_k = ranked_results[:k]

        # Get relevance for each result (unjudged = 0)
        relevances = [judgments.get(r.item_id, 0) for r in top_k]
        binary_rels = [binary_relevant(rel, relevance_threshold) for rel in relevances]

        # Precision@K
        precision = sum(binary_rels) / k if k > 0 else 0.0
        metrics[f"precision_at_{k}"] = round(precision, 4)

        # Recall@K
        total_relevant = sum(1 for r in all_relevances if r >= relevance_threshold)
        retrieved_relevant = sum(binary_rels)
        recall = retrieved_relevant / total_relevant if total_relevant > 0 else None
        metrics[f"recall_at_{k}"] = round(recall, 4) if recall is not None else None

        # NDCG@K
        ideal_rels = sorted(all_relevances[:k], reverse=True)
        # Pad ideal to length k if needed
        while len(ideal_rels) < k:
            ideal_rels.append(0)
        ndcg_val = ndcg(relevances, ideal_rels)
        metrics[f"ndcg_at_{k}"] = round(ndcg_val, 4) if ndcg_val is not None else None

        # MRR@K (Reciprocal Rank of first relevant result)
        mrr = 0.0
        for i, is_rel in enumerate(binary_rels):
            if is_rel:
                mrr = 1.0 / (i + 1)
                break
        metrics[f"mrr_at_{k}"] = round(mrr, 4)

        # HitRate@K (1 if any relevant in top-K, else 0)
        metrics[f"hit_rate_at_{k}"] = 1 if any(binary_rels) else 0

        # Cold-start quality metrics at K
        cold_in_top_k = [r for r in top_k if r.is_cold_item is True]
        cold_relevant = [
            r for r in cold_in_top_k
            if binary_relevant(judgments.get(r.item_id, 0), relevance_threshold)
        ]

        # ColdRelevantRate@K: fraction of cold items that are relevant
        if cold_in_top_k:
            metrics[f"cold_relevant_rate_at_{k}"] = round(
                len(cold_relevant) / len(cold_in_top_k), 4
            )
        else:
            metrics[f"cold_relevant_rate_at_{k}"] = None

        # ColdShareOfRelevant@K: fraction of relevant items that are cold
        if retrieved_relevant > 0:
            metrics[f"cold_share_of_relevant_at_{k}"] = round(
                len(cold_relevant) / retrieved_relevant, 4
            )
        else:
            metrics[f"cold_share_of_relevant_at_{k}"] = None

        # RawColdCoverage@K: fraction of top-K that are cold (diagnostic only)
        metrics[f"raw_cold_coverage_at_{k}"] = round(
            len(cold_in_top_k) / k if k > 0 else 0.0, 4
        )

    return metrics


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _stable_seed(*parts: str, base_seed: int) -> int:
    return base_seed + sum((index + 1) * ord(ch) for index, part in enumerate(parts) for ch in part)


def _bootstrap_mean_ci(
    values: list[float],
    *,
    iterations: int,
    confidence_level: float,
    seed: int,
) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1 or iterations <= 0:
        value = round(values[0], 6)
        return value, value

    rng = random.Random(seed)
    means: list[float] = []
    n = len(values)
    for _ in range(iterations):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    alpha = max(0.0, min(1.0, 1.0 - confidence_level))
    lower_idx = max(0, min(len(means) - 1, int((alpha / 2) * len(means))))
    upper_idx = max(0, min(len(means) - 1, int((1 - alpha / 2) * len(means)) - 1))
    return round(means[lower_idx], 6), round(means[upper_idx], 6)


def compute_variant_comparisons(
    rows: list[dict[str, object]],
    *,
    comparisons: list[tuple[str, str]] | tuple[tuple[str, str], ...] | None = None,
    metric_keys: list[str] | tuple[str, ...] | None = None,
    min_paired_queries: int = 30,
    min_positive_judged_pairs: int = 20,
    bootstrap_iterations: int = 500,
    confidence_level: float = 0.95,
    random_seed: int = 13,
    scope: str = "overall",
) -> list[dict[str, object]]:
    """Compute conservative paired variant-comparison diagnostics.

    A positive raw delta is not enough for a supported claim. The comparison
    must have enough paired, positive-judged queries and a bootstrap CI whose
    lower bound is above zero. Sparse or null evidence remains directional.
    """
    comparison_specs = comparisons or DEFAULT_VARIANT_COMPARISONS
    metrics = metric_keys or DEFAULT_COMPARISON_METRICS

    rows_by_query: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        query_id = str(row.get("query_id", ""))
        variant = str(row.get("variant", ""))
        if query_id and variant:
            rows_by_query.setdefault(query_id, {})[variant] = row

    diagnostics: list[dict[str, object]] = []
    for left_variant, right_variant in comparison_specs:
        paired_rows = [
            (by_variant[left_variant], by_variant[right_variant])
            for by_variant in rows_by_query.values()
            if left_variant in by_variant and right_variant in by_variant
        ]
        paired_query_count = len(paired_rows)
        judged_pair_count = sum(
            1
            for left_row, right_row in paired_rows
            if left_row.get("has_judgments") is True or right_row.get("has_judgments") is True
        )
        positive_judged_pair_count = sum(
            1
            for left_row, right_row in paired_rows
            if left_row.get("has_positive_judgment") is True or right_row.get("has_positive_judgment") is True
        )

        for metric_key in metrics:
            deltas: list[float] = []
            null_pair_count = 0
            for left_row, right_row in paired_rows:
                left_value = left_row.get(metric_key)
                right_value = right_row.get(metric_key)
                if _is_number(left_value) and _is_number(right_value):
                    deltas.append(float(left_value) - float(right_value))
                else:
                    null_pair_count += 1

            blockers: list[str] = []
            if paired_query_count < min_paired_queries:
                blockers.append(f"paired_query_count {paired_query_count} < {min_paired_queries}")
            if positive_judged_pair_count < min_positive_judged_pairs:
                blockers.append(
                    f"positive_judged_pair_count {positive_judged_pair_count} < {min_positive_judged_pairs}"
                )
            if null_pair_count:
                blockers.append(f"null_metric_pair_count {null_pair_count}")
            if not deltas:
                blockers.append("no non-null paired metric values")

            mean_delta = round(sum(deltas) / len(deltas), 6) if deltas else None
            median_delta = round(float(median(deltas)), 6) if deltas else None
            wins = sum(1 for delta in deltas if delta > 0)
            ties = sum(1 for delta in deltas if delta == 0)
            losses = sum(1 for delta in deltas if delta < 0)
            ci_lower, ci_upper = _bootstrap_mean_ci(
                deltas,
                iterations=bootstrap_iterations,
                confidence_level=confidence_level,
                seed=_stable_seed(left_variant, right_variant, metric_key, scope, base_seed=random_seed),
            )

            if blockers:
                significance = "directional_only"
            elif ci_lower is not None and ci_upper is not None and ci_lower > 0:
                significance = "positive"
            elif ci_lower is not None and ci_upper is not None and ci_upper < 0:
                significance = "negative"
            else:
                significance = "directional_only"

            diagnostics.append({
                "scope": scope,
                "comparison": f"{left_variant}_vs_{right_variant}",
                "left_variant": left_variant,
                "right_variant": right_variant,
                "metric": metric_key,
                "paired_query_count": paired_query_count,
                "judged_pair_count": judged_pair_count,
                "positive_judged_pair_count": positive_judged_pair_count,
                "non_null_pair_count": len(deltas),
                "null_metric_pair_count": null_pair_count,
                "mean_delta": mean_delta,
                "median_delta": median_delta,
                "wins": wins,
                "ties": ties,
                "losses": losses,
                "confidence_level": confidence_level,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "significance": significance,
                "blockers": blockers,
            })

    return diagnostics


def compute_slice_confidence(slice_summaries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Build per-slice confidence diagnostics from aggregate slice summaries."""
    diagnostics: list[dict[str, object]] = []
    for summary in slice_summaries:
        variant = str(summary.get("variant", ""))
        slice_name = str(summary.get("slice", ""))
        judged = int(summary.get("judged_query_count", 0) or 0)
        positive = int(summary.get("positive_judged_query_count", 0) or 0)
        result_coverage = float(summary.get("result_judgment_coverage_rate", 0.0) or 0.0)

        blockers: list[str] = []
        if judged < 5:
            blockers.append(f"judged_query_count {judged} < 5")
        if positive < 3:
            blockers.append(f"positive_judged_query_count {positive} < 3")
        if result_coverage < 0.25:
            blockers.append(f"result_judgment_coverage_rate {result_coverage:.4f} < 0.25")

        if judged >= 15 and positive >= 10 and result_coverage >= 0.5:
            confidence = "high"
        elif judged >= 5 and positive >= 3 and result_coverage >= 0.25:
            confidence = "medium"
        else:
            confidence = "low"

        diagnostics.append({
            "variant": variant,
            "slice": slice_name,
            "query_count": summary.get("query_count", 0),
            "judged_query_count": judged,
            "positive_judged_query_count": positive,
            "result_judgment_coverage_rate": round(result_coverage, 4),
            "confidence": confidence,
            "blockers": blockers,
        })
    return diagnostics


def aggregate_metrics(
    rows: list[dict[str, object]],
    group_by: list[str],
) -> list[dict[str, object]]:
    """Aggregate per-query metrics into group-level summaries.

    Groups rows by group_by keys (e.g., ["variant"] or ["variant", "slice"]).
    Computes macro averages for numeric metrics, ignoring None values.
    Reports valid_count and null_count for each metric.

    Args:
        rows: List of per-query metric dicts.
        group_by: List of keys to group by.

    Returns:
        List of group-level summary dicts.
    """
    # Group rows
    groups: dict[tuple, list[dict[str, object]]] = {}
    for row in rows:
        key = tuple(row.get(g, "") for g in group_by)
        groups.setdefault(key, []).append(row)

    summaries: list[dict[str, object]] = []
    for key, group_rows in groups.items():
        summary: dict[str, object] = dict(zip(group_by, key))
        summary["query_count"] = len(group_rows)
        judged_query_count = sum(1 for r in group_rows if r.get("has_judgments") is True)
        positive_judged_query_count = sum(1 for r in group_rows if r.get("has_positive_judgment") is True)
        result_count = sum(
            int(r.get("result_count", 0))
            for r in group_rows
            if isinstance(r.get("result_count", 0), int)
        )
        judged_result_count = sum(
            int(r.get("judged_result_count", 0))
            for r in group_rows
            if isinstance(r.get("judged_result_count", 0), int)
        )

        summary["judged_query_count"] = judged_query_count
        summary["positive_judged_query_count"] = positive_judged_query_count
        summary["query_judgment_coverage_rate"] = round(
            judged_query_count / len(group_rows), 4
        ) if group_rows else 0
        summary["result_judgment_coverage_rate"] = round(
            judged_result_count / result_count, 4
        ) if result_count else 0
        if judged_query_count >= 30:
            summary["metric_confidence"] = "high"
        elif judged_query_count >= 15:
            summary["metric_confidence"] = "medium"
        else:
            summary["metric_confidence"] = "low"
        confidence_blockers: list[str] = []
        if judged_query_count < 15:
            confidence_blockers.append(f"judged_query_count {judged_query_count} < 15")
        if positive_judged_query_count < 5:
            confidence_blockers.append(f"positive_judged_query_count {positive_judged_query_count} < 5")
        if summary["result_judgment_coverage_rate"] < 0.25:
            confidence_blockers.append(
                f"result_judgment_coverage_rate {summary['result_judgment_coverage_rate']:.4f} < 0.25"
            )
        summary["metric_confidence_blockers"] = confidence_blockers

        # Find all numeric keys
        all_keys: set[str] = set()
        for r in group_rows:
            all_keys.update(r.keys())
        numeric_keys = set()
        for k in all_keys:
            if k in group_by or k in (
                "query_id",
                "variant",
                "has_judgments",
                "has_positive_judgment",
                "query_judgment_coverage_rate",
                "result_judgment_coverage_rate",
            ):
                continue
            for r in group_rows:
                v = r.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    numeric_keys.add(k)
                    break

        # Compute averages
        for metric_key in sorted(numeric_keys):
            values = [r[metric_key] for r in group_rows if r.get(metric_key) is not None]
            numeric_vals = [v for v in values if isinstance(v, (int, float))]
            null_count = len(group_rows) - len(numeric_vals)

            if numeric_vals:
                avg = sum(numeric_vals) / len(numeric_vals)
                summary[metric_key] = round(avg, 4) if isinstance(avg, float) else avg
            else:
                summary[metric_key] = None
            summary[f"{metric_key}_valid_count"] = len(numeric_vals)
            summary[f"{metric_key}_null_count"] = null_count

        summaries.append(summary)

    return summaries
