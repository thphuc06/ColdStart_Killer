"""IR evaluation metrics for ColdStart_Killer.

Deterministic computation of NDCG, Precision, Recall, MRR, HitRate,
and cold-start quality metrics.

Import safety: no side effects at import time.
"""

from __future__ import annotations

import math
from typing import Any

from .contracts import EvaluationResult


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

        # Find all numeric keys
        all_keys: set[str] = set()
        for r in group_rows:
            all_keys.update(r.keys())
        numeric_keys = set()
        for k in all_keys:
            if k in group_by or k in ("query_id", "variant", "has_judgments"):
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
