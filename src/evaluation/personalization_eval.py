"""Phase 12 personalization and CF evaluation.

Offline evaluation for homepage-style recommendation quality using temporal
splits over clickstream data. The evaluator intentionally rebuilds train-time
signals from the first 70% of each user's history to avoid leaking held-out
future behavior into profile or CF scoring.
"""

from __future__ import annotations

import csv
import json
import math
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.behavior.profile_builder import POSITIVE_SIGNAL_THRESHOLD, _signal_weight
from src.behavior.signal_builder import build_signal_artifacts
from src.mongodb import (
    get_clickstream_events_collection,
    get_evaluation_runs_collection,
    get_item_item_cf_edges_collection,
    get_item_stats_collection,
    get_items_collection,
    get_recommendation_logs_collection,
    get_user_item_signals_collection,
    get_user_profiles_collection,
)
from src.recommendation.item_item_cf import (
    CF_INPUT_POLICY_CURRENT,
    CF_INPUT_POLICY_QUALIFIED,
    DEFAULT_CF_MIN_SUPPORT,
    compute_item_item_cf_edges,
)


BASELINE_NAMES = (
    "content_only",
    "exploration_only",
    "popularity",
    "profile_only",
    "profile_plus_cf",
    "profile_plus_qualified_cf",
)
POSITIVE_EVENT_TYPES = frozenset({"click", "add_to_cart", "purchase", "view_detail", "wishlist"})


@dataclass(frozen=True)
class PersonalizationEvalConfig:
    run_id: str
    output_dir: str = ""
    train_ratio: float = 0.7
    top_k: int = 20
    hit_rate_k: int = 10
    recall_k: int = 20
    map_k: int = 20
    synthetic_data: bool = True
    algorithm_version: str = ""
    ranking_version: str = ""
    created_at: str = ""
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TemporalSplit:
    train_events: list[dict[str, Any]]
    held_out_events: list[dict[str, Any]]
    train_positive_item_ids: list[str]
    held_out_positive_item_ids: list[str]
    held_out_deliberate_item_ids: list[str]
    train_negative_item_ids: list[str]


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise ValueError(f"Unsupported timestamp value: {value!r}")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _is_positive_event(event_type: str) -> bool:
    return event_type in POSITIVE_EVENT_TYPES


def _canonical_item(item: dict[str, Any], item_stats_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    cold_start = item.get("cold_start") if isinstance(item.get("cold_start"), dict) else {}
    stats_cold = item_stats_doc.get("cold_start") if isinstance(item_stats_doc, dict) and isinstance(item_stats_doc.get("cold_start"), dict) else {}
    item_id = str(item.get("item_id") or item.get("_id") or "").strip()
    quality_score = _safe_float(item.get("quality_score"), _safe_float((item_stats_doc or {}).get("quality_score"), 0.5))
    return {
        "item_id": item_id,
        "title": str(item.get("title") or item.get("title_en") or "").strip(),
        "brand": str(item.get("brand") or "").strip(),
        "category_id": str(item.get("category_id") or "unknown").strip() or "unknown",
        "price_bucket": str(item.get("price_bucket") or (item_stats_doc or {}).get("price_bucket") or "unknown").strip() or "unknown",
        "quality_score": quality_score,
        "is_cold_item": bool(cold_start.get("is_cold_item", stats_cold.get("is_cold_item", False))),
    }


def _normalize_counter(counter: Counter[str]) -> dict[str, float]:
    if not counter:
        return {}
    max_value = max(counter.values())
    if max_value <= 0:
        return {}
    return {
        key: round(value / max_value, 6)
        for key, value in counter.items()
        if value > 0
    }


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _build_train_signals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        return []
    updated_at = max(str(event.get("timestamp") or "") for event in events)
    return build_signal_artifacts(events=events, updated_at=updated_at).signal_docs


def temporal_split_events(
    events: list[dict[str, Any]],
    *,
    train_ratio: float = 0.7,
) -> TemporalSplit:
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be between 0 and 1")

    ordered_events = sorted(events, key=lambda event: _parse_timestamp(event.get("timestamp")))
    if not ordered_events:
        return TemporalSplit([], [], [], [], [], [])

    cut_index = max(1, int(len(ordered_events) * train_ratio))
    cut_index = min(cut_index, len(ordered_events))
    train_events = ordered_events[:cut_index]
    held_out_events = ordered_events[cut_index:]

    train_positive_item_ids = _dedupe_preserve_order([
        str(event.get("item_id") or "")
        for event in train_events
        if _is_positive_event(str(event.get("event_type") or ""))
    ])
    train_positive_set = set(train_positive_item_ids)
    held_out_positive_item_ids = _dedupe_preserve_order([
        str(event.get("item_id") or "")
        for event in held_out_events
        if _is_positive_event(str(event.get("event_type") or ""))
        and str(event.get("item_id") or "") not in train_positive_set
    ])
    held_out_deliberate_item_ids = _dedupe_preserve_order([
        str(signal.get("item_id") or "")
        for signal in _build_train_signals(held_out_events)
        if bool(signal.get("seed_eligible"))
        and str(signal.get("item_id") or "") not in train_positive_set
    ])
    train_negative_item_ids = _dedupe_preserve_order([
        str(signal.get("item_id") or "")
        for signal in _build_train_signals(train_events)
        if _safe_float(signal.get("negative_score"), 0.0) > 0
    ])

    return TemporalSplit(
        train_events=train_events,
        held_out_events=held_out_events,
        train_positive_item_ids=train_positive_item_ids,
        held_out_positive_item_ids=held_out_positive_item_ids,
        held_out_deliberate_item_ids=held_out_deliberate_item_ids,
        train_negative_item_ids=train_negative_item_ids,
    )


def _title_tokens(item: dict[str, Any]) -> set[str]:
    return _tokenize(item.get("title", ""))


def _content_similarity(source_item: dict[str, Any], candidate_item: dict[str, Any]) -> float:
    category_match = 1.0 if source_item.get("category_id") == candidate_item.get("category_id") else 0.0
    brand_match = 1.0 if source_item.get("brand") and source_item.get("brand") == candidate_item.get("brand") else 0.0
    price_match = 1.0 if source_item.get("price_bucket") == candidate_item.get("price_bucket") else 0.0
    source_tokens = _title_tokens(source_item)
    candidate_tokens = _title_tokens(candidate_item)
    token_overlap = 0.0
    if source_tokens and candidate_tokens:
        token_overlap = len(source_tokens & candidate_tokens) / len(source_tokens | candidate_tokens)
    return round((0.45 * brand_match) + (0.35 * category_match) + (0.10 * price_match) + (0.10 * token_overlap), 6)


def _build_user_profile(train_signals: list[dict[str, Any]], items_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    category_counter: Counter[str] = Counter()
    brand_counter: Counter[str] = Counter()
    price_counter: Counter[str] = Counter()
    token_counter: Counter[str] = Counter()
    seen_positive_items: list[str] = []

    for signal in train_signals:
        item_id = str(signal.get("item_id") or "")
        item = items_by_id.get(item_id)
        if not item:
            continue
        weight = _signal_weight(signal)
        if weight < POSITIVE_SIGNAL_THRESHOLD:
            continue
        category_counter[item["category_id"]] += weight
        if item["brand"]:
            brand_counter[item["brand"]] += weight
        price_counter[item["price_bucket"]] += weight
        for token in _title_tokens(item):
            token_counter[token] += weight
        seen_positive_items.append(item_id)

    return {
        "category_affinity": _normalize_counter(category_counter),
        "brand_affinity": _normalize_counter(brand_counter),
        "price_affinity": _normalize_counter(price_counter),
        "token_affinity": _normalize_counter(token_counter),
        "train_positive_item_ids": _dedupe_preserve_order(seen_positive_items),
    }


def _profile_score(candidate_item: dict[str, Any], user_profile: dict[str, Any]) -> float:
    category_score = _safe_float(user_profile.get("category_affinity", {}).get(candidate_item.get("category_id")), 0.0)
    brand_score = _safe_float(user_profile.get("brand_affinity", {}).get(candidate_item.get("brand")), 0.0)
    price_score = _safe_float(user_profile.get("price_affinity", {}).get(candidate_item.get("price_bucket")), 0.0)
    token_affinity = user_profile.get("token_affinity", {})
    candidate_tokens = _title_tokens(candidate_item)
    if candidate_tokens:
        token_score = sum(_safe_float(token_affinity.get(token), 0.0) for token in candidate_tokens) / len(candidate_tokens)
    else:
        token_score = 0.0
    return round((0.50 * category_score) + (0.35 * brand_score) + (0.10 * token_score) + (0.05 * price_score), 6)


def _build_train_popularity(train_signals_by_user: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    popularity: defaultdict[str, float] = defaultdict(float)
    for signals in train_signals_by_user.values():
        for signal in signals:
            item_id = str(signal.get("item_id") or "")
            weight = _signal_weight(signal)
            if item_id and weight >= POSITIVE_SIGNAL_THRESHOLD:
                popularity[item_id] += weight
    return dict(popularity)


def _cf_source_item_ids(signals: list[dict[str, Any]], *, qualified: bool) -> list[str]:
    return _dedupe_preserve_order([
        str(signal.get("item_id") or "")
        for signal in signals
        if (
            bool(signal.get("seed_eligible"))
            and _safe_float(signal.get("negative_score"), 0.0) <= 0
            if qualified
            else (_safe_float(signal.get("implicit_score"), 0.0) > 1.0 or bool(signal.get("preference")))
        )
    ])


def _compute_eval_cf_edges(
    train_signals_by_user: dict[str, list[dict[str, Any]]],
    *,
    qualified: bool,
    min_support: int = DEFAULT_CF_MIN_SUPPORT,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    signal_docs = [
        signal
        for signals in train_signals_by_user.values()
        for signal in signals
    ]
    existing_item_ids = {
        str(signal.get("item_id") or "").strip()
        for signal in signal_docs
        if str(signal.get("item_id") or "").strip()
    }
    updated_at = max(
        (
            str(signal.get("last_interaction_at") or signal.get("updated_at") or "")
            for signal in signal_docs
            if str(signal.get("last_interaction_at") or signal.get("updated_at") or "")
        ),
        default=_now_iso(),
    )
    computed = compute_item_item_cf_edges(
        signal_docs=signal_docs,
        existing_item_ids=existing_item_ids,
        input_policy=CF_INPUT_POLICY_QUALIFIED if qualified else CF_INPUT_POLICY_CURRENT,
        min_support=min_support,
        updated_at=updated_at,
    )
    edges: defaultdict[str, dict[str, float]] = defaultdict(dict)
    for edge in computed["edge_docs"]:
        edges[str(edge["item_id"])][str(edge["neighbor_item_id"])] = _safe_float(edge.get("cf_score"), 0.0)
    return {item_id: dict(neighbors) for item_id, neighbors in edges.items()}, computed["stats"].as_dict()


def _build_cf_edges(
    train_signals_by_user: dict[str, list[dict[str, Any]]],
    *,
    qualified: bool,
    min_support: int = DEFAULT_CF_MIN_SUPPORT,
) -> dict[str, dict[str, float]]:
    edges, _stats = _compute_eval_cf_edges(
        train_signals_by_user,
        qualified=qualified,
        min_support=min_support,
    )
    return edges


def _rank_content_only(
    *,
    user_profile: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    excluded_item_ids: set[str],
    top_k: int,
) -> tuple[list[str], set[str]]:
    source_items = [items_by_id[item_id] for item_id in user_profile.get("train_positive_item_ids", []) if item_id in items_by_id]
    scored: list[tuple[float, str]] = []
    for item_id, candidate in items_by_id.items():
        if item_id in excluded_item_ids:
            continue
        similarity = max((_content_similarity(source_item, candidate) for source_item in source_items), default=0.0)
        scored.append((similarity, item_id))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item_id for _score, item_id in scored[:top_k]], set()


def _rank_exploration_only(
    *,
    items_by_id: dict[str, dict[str, Any]],
    excluded_item_ids: set[str],
    top_k: int,
) -> tuple[list[str], set[str]]:
    scored: list[tuple[float, str]] = []
    for item_id, candidate in items_by_id.items():
        if item_id in excluded_item_ids:
            continue
        score = (1.0 if candidate.get("is_cold_item") else 0.0) + (0.25 * _safe_float(candidate.get("quality_score"), 0.0))
        scored.append((round(score, 6), item_id))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item_id for _score, item_id in scored[:top_k]], set()


def _rank_popularity(
    *,
    items_by_id: dict[str, dict[str, Any]],
    popularity_by_item: dict[str, float],
    excluded_item_ids: set[str],
    top_k: int,
) -> tuple[list[str], set[str]]:
    scored: list[tuple[float, str]] = []
    for item_id, candidate in items_by_id.items():
        if item_id in excluded_item_ids:
            continue
        score = _safe_float(popularity_by_item.get(item_id), 0.0) + (0.05 * _safe_float(candidate.get("quality_score"), 0.0))
        scored.append((round(score, 6), item_id))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item_id for _score, item_id in scored[:top_k]], set()


def _rank_profile_only(
    *,
    user_profile: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    excluded_item_ids: set[str],
    top_k: int,
) -> tuple[list[str], set[str]]:
    scored: list[tuple[float, str]] = []
    for item_id, candidate in items_by_id.items():
        if item_id in excluded_item_ids:
            continue
        score = _profile_score(candidate, user_profile)
        scored.append((score, item_id))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [item_id for _score, item_id in scored[:top_k]], set()


def _rank_profile_plus_cf(
    *,
    user_profile: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    cf_edges: dict[str, dict[str, float]],
    popularity_by_item: dict[str, float],
    source_item_ids: list[str],
    excluded_item_ids: set[str],
    top_k: int,
) -> tuple[list[str], set[str]]:
    scored: list[tuple[float, str]] = []
    cf_supported_item_ids: set[str] = set()
    for item_id, candidate in items_by_id.items():
        if item_id in excluded_item_ids:
            continue
        profile_score = _profile_score(candidate, user_profile)
        cf_score = max((_safe_float(cf_edges.get(source_item_id, {}).get(item_id), 0.0) for source_item_id in source_item_ids), default=0.0)
        if cf_score > 0:
            cf_supported_item_ids.add(item_id)
        popularity_bonus = 0.05 * _safe_float(popularity_by_item.get(item_id), 0.0)
        score = profile_score + (0.75 * cf_score) + popularity_bonus
        scored.append((round(score, 6), item_id))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    ranked_item_ids = [item_id for _score, item_id in scored[:top_k]]
    return ranked_item_ids, {item_id for item_id in ranked_item_ids if item_id in cf_supported_item_ids}


def compute_ranking_metrics(
    recommended_item_ids: list[str],
    held_out_positive_item_ids: list[str],
    *,
    items_by_id: dict[str, dict[str, Any]],
    popularity_by_item: dict[str, float] | None = None,
    cf_supported_item_ids: set[str] | None = None,
    negative_item_ids: set[str] | None = None,
    hit_rate_k: int = 10,
    recall_k: int = 20,
    map_k: int = 20,
    ndcg_k: int = 20,
    mrr_k: int = 10,
) -> dict[str, Any]:
    popularity_by_item = popularity_by_item or {}
    cf_supported_item_ids = cf_supported_item_ids or set()
    negative_item_ids = negative_item_ids or set()
    held_out_set = set(held_out_positive_item_ids)
    hit_slice = recommended_item_ids[:hit_rate_k]
    recall_slice = recommended_item_ids[:recall_k]
    map_slice = recommended_item_ids[:map_k]

    hit_rate = 1.0 if any(item_id in held_out_set for item_id in hit_slice) else 0.0
    recall = 0.0
    if held_out_set:
        recall = sum(1 for item_id in recall_slice if item_id in held_out_set) / len(held_out_set)

    precision_sum = 0.0
    hit_count = 0
    for index, item_id in enumerate(map_slice, start=1):
        if item_id in held_out_set:
            hit_count += 1
            precision_sum += hit_count / index
    average_precision = precision_sum / len(held_out_set) if held_out_set else 0.0
    ndcg_slice = recommended_item_ids[:ndcg_k]
    discounted_gain = sum(
        1.0 / math.log2(index + 1)
        for index, item_id in enumerate(ndcg_slice, start=1)
        if item_id in held_out_set
    )
    ideal_gain = sum(
        1.0 / math.log2(index + 1)
        for index in range(1, min(len(held_out_set), ndcg_k) + 1)
    )
    ndcg = discounted_gain / ideal_gain if ideal_gain else 0.0
    reciprocal_rank = next(
        (
            1.0 / index
            for index, item_id in enumerate(recommended_item_ids[:mrr_k], start=1)
            if item_id in held_out_set
        ),
        0.0,
    )

    inspected = recall_slice
    inspected_items = []
    for item_id in inspected:
        raw_item = items_by_id.get(item_id)
        if not raw_item:
            continue
        if "is_cold_item" in raw_item and "title" in raw_item:
            inspected_items.append(raw_item)
        else:
            inspected_items.append(_canonical_item(raw_item))
    distinct_categories = {item.get("category_id", "unknown") for item in inspected_items}
    diversity = len(distinct_categories) / len(inspected_items) if inspected_items else 0.0

    max_popularity = max(popularity_by_item.values(), default=0.0)
    novelty_scores: list[float] = []
    for item_id in inspected:
        popularity = _safe_float(popularity_by_item.get(item_id), 0.0)
        if max_popularity <= 0:
            novelty_scores.append(1.0)
            continue
        novelty_scores.append(1.0 - (math.log1p(popularity) / math.log1p(max_popularity)))
    novelty = sum(novelty_scores) / len(novelty_scores) if novelty_scores else 0.0

    cold_items = [item for item in inspected_items if item.get("is_cold_item")]
    cold_exposure = len(cold_items) / len(inspected_items) if inspected_items else 0.0
    cf_supported_count = sum(1 for item_id in recall_slice if item_id in cf_supported_item_ids)
    negative_reexposure_count = sum(1 for item_id in recall_slice if item_id in negative_item_ids)

    return {
        "hit_rate_at_10": round(hit_rate, 6),
        "recall_at_20": round(recall, 6),
        "map_at_20": round(average_precision, 6),
        "ndcg_at_20": round(ndcg, 6),
        "mrr_at_10": round(reciprocal_rank, 6),
        "diversity_at_20": round(diversity, 6),
        "novelty_at_20": round(novelty, 6),
        "cold_start_exposure_at_20": round(cold_exposure, 6),
        "cf_supported_recommendation_count": cf_supported_count,
        "negative_reexposure_count": negative_reexposure_count,
        "negative_reexposure_rate": round(negative_reexposure_count / len(recall_slice), 6) if recall_slice else 0.0,
    }


def _infer_version(recommendation_logs: list[dict[str, Any]] | None, field_name: str, fallback: str) -> str:
    if not recommendation_logs:
        return fallback
    values = [str(doc.get(field_name) or "").strip() for doc in recommendation_logs]
    values = [value for value in values if value]
    if not values:
        return fallback
    return Counter(values).most_common(1)[0][0]


def _summary_row(
    baseline: str,
    rows: list[dict[str, Any]],
    *,
    catalog_size: int,
    top_k: int,
) -> dict[str, Any]:
    if not rows:
        return {
            "baseline": baseline,
            "evaluated_user_count": 0,
            "hit_rate_at_10": 0.0,
            "recall_at_20": 0.0,
            "map_at_20": 0.0,
            "ndcg_at_20": 0.0,
            "mrr_at_10": 0.0,
            "coverage": 0.0,
            "diversity_at_20": 0.0,
            "novelty_at_20": 0.0,
            "cold_start_exposure_at_20": 0.0,
            "cf_supported_recommendation_count": 0,
            "cf_supported_recommendation_rate": 0.0,
            "negative_reexposure_count": 0,
            "negative_reexposure_rate": 0.0,
            "deliberate_evaluated_user_count": 0,
            "deliberate_hit_rate_at_10": 0.0,
            "deliberate_recall_at_20": 0.0,
            "deliberate_map_at_20": 0.0,
            "deliberate_ndcg_at_20": 0.0,
            "deliberate_mrr_at_10": 0.0,
        }

    unique_recommended_items = {
        item_id
        for row in rows
        for item_id in row.get("recommended_item_ids", [])[:top_k]
    }
    total_cf_supported = sum(int(row.get("cf_supported_recommendation_count", 0)) for row in rows)
    total_negative_reexposure = sum(int(row.get("negative_reexposure_count", 0)) for row in rows)
    denominator = max(sum(min(len(row.get("recommended_item_ids", [])), top_k) for row in rows), 1)
    deliberate_rows = [row for row in rows if row.get("has_deliberate_target")]
    deliberate_denominator = len(deliberate_rows) or 1
    return {
        "baseline": baseline,
        "evaluated_user_count": len(rows),
        "hit_rate_at_10": round(sum(_safe_float(row.get("hit_rate_at_10"), 0.0) for row in rows) / len(rows), 6),
        "recall_at_20": round(sum(_safe_float(row.get("recall_at_20"), 0.0) for row in rows) / len(rows), 6),
        "map_at_20": round(sum(_safe_float(row.get("map_at_20"), 0.0) for row in rows) / len(rows), 6),
        "ndcg_at_20": round(sum(_safe_float(row.get("ndcg_at_20"), 0.0) for row in rows) / len(rows), 6),
        "mrr_at_10": round(sum(_safe_float(row.get("mrr_at_10"), 0.0) for row in rows) / len(rows), 6),
        "coverage": round(len(unique_recommended_items) / catalog_size, 6) if catalog_size else 0.0,
        "diversity_at_20": round(sum(_safe_float(row.get("diversity_at_20"), 0.0) for row in rows) / len(rows), 6),
        "novelty_at_20": round(sum(_safe_float(row.get("novelty_at_20"), 0.0) for row in rows) / len(rows), 6),
        "cold_start_exposure_at_20": round(sum(_safe_float(row.get("cold_start_exposure_at_20"), 0.0) for row in rows) / len(rows), 6),
        "cf_supported_recommendation_count": total_cf_supported,
        "cf_supported_recommendation_rate": round(total_cf_supported / denominator, 6),
        "negative_reexposure_count": total_negative_reexposure,
        "negative_reexposure_rate": round(total_negative_reexposure / denominator, 6),
        "deliberate_evaluated_user_count": len(deliberate_rows),
        "deliberate_hit_rate_at_10": round(sum(_safe_float(row.get("deliberate_hit_rate_at_10"), 0.0) for row in deliberate_rows) / deliberate_denominator, 6),
        "deliberate_recall_at_20": round(sum(_safe_float(row.get("deliberate_recall_at_20"), 0.0) for row in deliberate_rows) / deliberate_denominator, 6),
        "deliberate_map_at_20": round(sum(_safe_float(row.get("deliberate_map_at_20"), 0.0) for row in deliberate_rows) / deliberate_denominator, 6),
        "deliberate_ndcg_at_20": round(sum(_safe_float(row.get("deliberate_ndcg_at_20"), 0.0) for row in deliberate_rows) / deliberate_denominator, 6),
        "deliberate_mrr_at_10": round(sum(_safe_float(row.get("deliberate_mrr_at_10"), 0.0) for row in deliberate_rows) / deliberate_denominator, 6),
    }


def _comparison_row(summary_by_baseline: dict[str, dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    left_row = summary_by_baseline.get(left, {})
    right_row = summary_by_baseline.get(right, {})
    return {
        "comparison": f"{left}_vs_{right}",
        "hit_rate_at_10_delta": round(_safe_float(left_row.get("hit_rate_at_10"), 0.0) - _safe_float(right_row.get("hit_rate_at_10"), 0.0), 6),
        "recall_at_20_delta": round(_safe_float(left_row.get("recall_at_20"), 0.0) - _safe_float(right_row.get("recall_at_20"), 0.0), 6),
        "map_at_20_delta": round(_safe_float(left_row.get("map_at_20"), 0.0) - _safe_float(right_row.get("map_at_20"), 0.0), 6),
        "ndcg_at_20_delta": round(_safe_float(left_row.get("ndcg_at_20"), 0.0) - _safe_float(right_row.get("ndcg_at_20"), 0.0), 6),
        "mrr_at_10_delta": round(_safe_float(left_row.get("mrr_at_10"), 0.0) - _safe_float(right_row.get("mrr_at_10"), 0.0), 6),
        "deliberate_hit_rate_at_10_delta": round(_safe_float(left_row.get("deliberate_hit_rate_at_10"), 0.0) - _safe_float(right_row.get("deliberate_hit_rate_at_10"), 0.0), 6),
        "deliberate_recall_at_20_delta": round(_safe_float(left_row.get("deliberate_recall_at_20"), 0.0) - _safe_float(right_row.get("deliberate_recall_at_20"), 0.0), 6),
        "deliberate_map_at_20_delta": round(_safe_float(left_row.get("deliberate_map_at_20"), 0.0) - _safe_float(right_row.get("deliberate_map_at_20"), 0.0), 6),
        "deliberate_ndcg_at_20_delta": round(_safe_float(left_row.get("deliberate_ndcg_at_20"), 0.0) - _safe_float(right_row.get("deliberate_ndcg_at_20"), 0.0), 6),
        "deliberate_mrr_at_10_delta": round(_safe_float(left_row.get("deliberate_mrr_at_10"), 0.0) - _safe_float(right_row.get("deliberate_mrr_at_10"), 0.0), 6),
        "cf_supported_count_delta": int(left_row.get("cf_supported_recommendation_count", 0)) - int(right_row.get("cf_supported_recommendation_count", 0)),
        "negative_reexposure_rate_delta": round(_safe_float(left_row.get("negative_reexposure_rate"), 0.0) - _safe_float(right_row.get("negative_reexposure_rate"), 0.0), 6),
    }


def _qualified_cf_gate(
    summary_by_baseline: dict[str, dict[str, Any]],
    *,
    qualified_directional_edge_count: int,
) -> dict[str, str]:
    current = summary_by_baseline["profile_plus_cf"]
    qualified = summary_by_baseline["profile_plus_qualified_cf"]
    if int(qualified.get("deliberate_evaluated_user_count", 0)) == 0:
        return {"decision": "needs_more_evidence", "reason": "No deliberate held-out targets were available for the qualified CF comparison."}
    if qualified_directional_edge_count <= 0:
        return {"decision": "needs_more_evidence", "reason": "Qualified CF produced no supported edges under min_support=2."}
    if int(qualified.get("cf_supported_recommendation_count", 0)) == 0:
        return {"decision": "needs_more_evidence", "reason": "Qualified CF produced no supported recommendations under min_support=2."}
    if _safe_float(qualified.get("negative_reexposure_rate"), 0.0) > 0:
        return {"decision": "reject", "reason": "Qualified CF re-exposed items with negative evidence."}
    guarded_metrics = (
        "recall_at_20",
        "map_at_20",
        "ndcg_at_20",
        "deliberate_recall_at_20",
        "deliberate_ndcg_at_20",
        "deliberate_mrr_at_10",
    )
    degraded = [metric for metric in guarded_metrics if _safe_float(qualified.get(metric)) < _safe_float(current.get(metric))]
    if degraded:
        return {"decision": "reject", "reason": f"Qualified CF reduced protected metrics: {', '.join(degraded)}."}
    return {"decision": "adopt", "reason": "Qualified CF retained protected all-positive and deliberate metrics with usable supported coverage."}


def evaluate_personalization(
    *,
    items: list[dict[str, Any]],
    clickstream_events: list[dict[str, Any]],
    recommendation_logs: list[dict[str, Any]] | None = None,
    item_stats: list[dict[str, Any]] | None = None,
    config: PersonalizationEvalConfig | None = None,
) -> dict[str, Any]:
    if config is None:
        config = PersonalizationEvalConfig(run_id=f"personalization_eval_{int(time.time())}")

    if config.top_k <= 0:
        raise ValueError("top_k must be positive")

    item_stats_by_id = {
        str(doc.get("item_id") or doc.get("_id") or "").strip(): dict(doc)
        for doc in (item_stats or [])
        if str(doc.get("item_id") or doc.get("_id") or "").strip()
    }
    items_by_id = {
        canonical["item_id"]: canonical
        for canonical in (
            _canonical_item(item, item_stats_by_id.get(str(item.get("item_id") or item.get("_id") or "").strip()))
            for item in items
        )
        if canonical["item_id"]
    }

    events_by_user: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in clickstream_events:
        user_id_hash = str(event.get("user_id_hash") or "").strip()
        item_id = str(event.get("item_id") or "").strip()
        if not user_id_hash or not item_id or item_id not in items_by_id:
            continue
        copied = dict(event)
        copied["item_id"] = item_id
        copied["user_id_hash"] = user_id_hash
        events_by_user[user_id_hash].append(copied)

    user_splits = {
        user_id_hash: temporal_split_events(events, train_ratio=config.train_ratio)
        for user_id_hash, events in events_by_user.items()
    }
    train_signals_by_user = {
        user_id_hash: _build_train_signals(split.train_events)
        for user_id_hash, split in user_splits.items()
        if split.train_events
    }
    popularity_by_item = _build_train_popularity(train_signals_by_user)
    cf_edges, cf_stats = _compute_eval_cf_edges(train_signals_by_user, qualified=False)
    qualified_cf_edges, qualified_cf_stats = _compute_eval_cf_edges(train_signals_by_user, qualified=True)

    per_user_metrics: list[dict[str, Any]] = []
    evaluated_users = 0
    for user_id_hash, split in sorted(user_splits.items()):
        if not split.train_positive_item_ids or not split.held_out_positive_item_ids:
            continue
        evaluated_users += 1
        user_signals = train_signals_by_user.get(user_id_hash, [])
        user_profile = _build_user_profile(user_signals, items_by_id)
        current_cf_source_item_ids = _cf_source_item_ids(user_signals, qualified=False)
        qualified_cf_source_item_ids = _cf_source_item_ids(user_signals, qualified=True)
        negative_item_ids = set(split.train_negative_item_ids)
        excluded_item_ids = set(split.train_positive_item_ids) | negative_item_ids

        baseline_rankers = {
            "content_only": lambda: _rank_content_only(
                user_profile=user_profile,
                items_by_id=items_by_id,
                excluded_item_ids=excluded_item_ids,
                top_k=config.top_k,
            ),
            "exploration_only": lambda: _rank_exploration_only(
                items_by_id=items_by_id,
                excluded_item_ids=excluded_item_ids,
                top_k=config.top_k,
            ),
            "popularity": lambda: _rank_popularity(
                items_by_id=items_by_id,
                popularity_by_item=popularity_by_item,
                excluded_item_ids=excluded_item_ids,
                top_k=config.top_k,
            ),
            "profile_only": lambda: _rank_profile_only(
                user_profile=user_profile,
                items_by_id=items_by_id,
                excluded_item_ids=excluded_item_ids,
                top_k=config.top_k,
            ),
            "profile_plus_cf": lambda: _rank_profile_plus_cf(
                user_profile=user_profile,
                items_by_id=items_by_id,
                cf_edges=cf_edges,
                popularity_by_item=popularity_by_item,
                source_item_ids=current_cf_source_item_ids,
                excluded_item_ids=excluded_item_ids,
                top_k=config.top_k,
            ),
            "profile_plus_qualified_cf": lambda: _rank_profile_plus_cf(
                user_profile=user_profile,
                items_by_id=items_by_id,
                cf_edges=qualified_cf_edges,
                popularity_by_item=popularity_by_item,
                source_item_ids=qualified_cf_source_item_ids,
                excluded_item_ids=excluded_item_ids,
                top_k=config.top_k,
            ),
        }

        for baseline in BASELINE_NAMES:
            recommended_item_ids, cf_supported_item_ids = baseline_rankers[baseline]()
            metric_row = compute_ranking_metrics(
                recommended_item_ids,
                split.held_out_positive_item_ids,
                items_by_id=items_by_id,
                popularity_by_item=popularity_by_item,
                cf_supported_item_ids=cf_supported_item_ids,
                negative_item_ids=negative_item_ids,
                hit_rate_k=config.hit_rate_k,
                recall_k=config.recall_k,
                map_k=config.map_k,
            )
            deliberate_metrics = compute_ranking_metrics(
                recommended_item_ids,
                split.held_out_deliberate_item_ids,
                items_by_id=items_by_id,
                popularity_by_item=popularity_by_item,
                cf_supported_item_ids=cf_supported_item_ids,
                negative_item_ids=negative_item_ids,
                hit_rate_k=config.hit_rate_k,
                recall_k=config.recall_k,
                map_k=config.map_k,
            )
            per_user_metrics.append({
                "user_id_hash": user_id_hash,
                "baseline": baseline,
                "train_positive_item_ids": list(split.train_positive_item_ids),
                "held_out_positive_item_ids": list(split.held_out_positive_item_ids),
                "held_out_deliberate_item_ids": list(split.held_out_deliberate_item_ids),
                "train_negative_item_ids": list(split.train_negative_item_ids),
                "has_deliberate_target": bool(split.held_out_deliberate_item_ids),
                "recommended_item_ids": list(recommended_item_ids),
                **metric_row,
                "deliberate_hit_rate_at_10": deliberate_metrics["hit_rate_at_10"],
                "deliberate_recall_at_20": deliberate_metrics["recall_at_20"],
                "deliberate_map_at_20": deliberate_metrics["map_at_20"],
                "deliberate_ndcg_at_20": deliberate_metrics["ndcg_at_20"],
                "deliberate_mrr_at_10": deliberate_metrics["mrr_at_10"],
            })

    summary_by_baseline = {
        baseline: _summary_row(
            baseline,
            [row for row in per_user_metrics if row["baseline"] == baseline],
            catalog_size=len(items_by_id),
            top_k=config.top_k,
        )
        for baseline in BASELINE_NAMES
    }
    baseline_summaries = [summary_by_baseline[baseline] for baseline in BASELINE_NAMES]
    comparisons = [
        _comparison_row(summary_by_baseline, "profile_plus_cf", "profile_only"),
        _comparison_row(summary_by_baseline, "profile_plus_cf", "popularity"),
        _comparison_row(summary_by_baseline, "profile_plus_qualified_cf", "profile_plus_cf"),
    ]

    synthetic_label = "synthetic/demo" if config.synthetic_data else "live/non-synthetic"
    algorithm_version = config.algorithm_version or _infer_version(recommendation_logs, "algorithm_version", "unknown")
    ranking_version = config.ranking_version or _infer_version(recommendation_logs, "ranking_version", "unknown")
    config_dict = {
        "run_id": config.run_id,
        "created_at": config.created_at or _now_iso(),
        "train_ratio": config.train_ratio,
        "top_k": config.top_k,
        "hit_rate_k": config.hit_rate_k,
        "recall_k": config.recall_k,
        "map_k": config.map_k,
        "algorithm_version": algorithm_version,
        "ranking_version": ranking_version,
        "data_label": f"{synthetic_label} evaluation; metrics must be interpreted with explicit synthetic/demo caveats.",
        "event_count": len(clickstream_events),
        "user_count": len(events_by_user),
        "evaluated_user_count": evaluated_users,
        "baselines": list(BASELINE_NAMES),
        "cf_min_support": DEFAULT_CF_MIN_SUPPORT,
        "extra_metadata": dict(config.extra_metadata),
    }

    return {
        "config": config_dict,
        "per_user_metrics": per_user_metrics,
        "baseline_summaries": baseline_summaries,
        "comparisons": comparisons,
        "cf_diagnostics": {
            "min_support": DEFAULT_CF_MIN_SUPPORT,
            "current_directional_edge_count": sum(len(neighbors) for neighbors in cf_edges.values()),
            "qualified_directional_edge_count": sum(len(neighbors) for neighbors in qualified_cf_edges.values()),
            "current_build_stats": cf_stats,
            "qualified_build_stats": qualified_cf_stats,
        },
        "cf_qualified_gate": _qualified_cf_gate(
            summary_by_baseline,
            qualified_directional_edge_count=sum(len(neighbors) for neighbors in qualified_cf_edges.values()),
        ),
    }


def _markdown_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> list[str]:
    header = "| " + " | ".join(label for _key, label in columns) + " |"
    divider = "|" + "---|" * len(columns)
    lines = [header, divider]
    for row in rows:
        values = []
        for key, _label in columns:
            value = row.get(key, "")
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def generate_personalization_summary_md(run_data: dict[str, Any]) -> str:
    config = run_data.get("config", {})
    baseline_summaries = run_data.get("baseline_summaries", [])
    comparisons = run_data.get("comparisons", [])
    gate = run_data.get("cf_qualified_gate", {})
    cf_diagnostics = run_data.get("cf_diagnostics", {})

    lines = [
        "# Personalization Evaluation Report",
        "",
        f"**Run ID:** {config.get('run_id', 'unknown')}",
        f"**Created at:** {config.get('created_at', 'unknown')}",
        f"**Algorithm version:** {config.get('algorithm_version', 'unknown')}",
        f"**Ranking version:** {config.get('ranking_version', 'unknown')}",
        "",
        f"> {config.get('data_label', 'synthetic/demo evaluation caveat missing')}",
        "",
        "## Baseline Metrics",
        "",
    ]
    lines.extend(_markdown_table(
        baseline_summaries,
        [
            ("baseline", "Baseline"),
            ("evaluated_user_count", "Users"),
            ("hit_rate_at_10", "HitRate@10"),
            ("recall_at_20", "Recall@20"),
            ("map_at_20", "MAP@20"),
            ("ndcg_at_20", "NDCG@20"),
            ("mrr_at_10", "MRR@10"),
            ("deliberate_hit_rate_at_10", "Deliberate Hit@10"),
            ("deliberate_recall_at_20", "Deliberate Recall@20"),
            ("deliberate_map_at_20", "Deliberate MAP@20"),
            ("deliberate_ndcg_at_20", "Deliberate NDCG@20"),
            ("deliberate_mrr_at_10", "Deliberate MRR@10"),
            ("coverage", "Coverage"),
            ("diversity_at_20", "Diversity"),
            ("novelty_at_20", "Novelty"),
            ("cold_start_exposure_at_20", "Cold-start Exposure"),
            ("cf_supported_recommendation_count", "CF-supported Count"),
            ("negative_reexposure_rate", "Negative Re-exposure"),
        ],
    ))
    lines.extend([
        "",
        "## Key Comparisons",
        "",
    ])
    lines.extend(_markdown_table(
        comparisons,
        [
            ("comparison", "Comparison"),
            ("hit_rate_at_10_delta", "HitRate@10 Delta"),
            ("recall_at_20_delta", "Recall@20 Delta"),
            ("map_at_20_delta", "MAP@20 Delta"),
            ("ndcg_at_20_delta", "NDCG@20 Delta"),
            ("deliberate_map_at_20_delta", "Deliberate MAP@20 Delta"),
            ("cf_supported_count_delta", "CF-supported Delta"),
        ],
    ))
    lines.extend([
        "",
        "## Qualified CF Gate",
        "",
        f"- Decision: `{gate.get('decision', 'needs_more_evidence')}`",
        f"- Reason: {gate.get('reason', 'No gate result produced.')}",
        f"- CF min support: `{cf_diagnostics.get('min_support', config.get('cf_min_support', 'unknown'))}`",
        f"- Current / qualified directional edge count: `{cf_diagnostics.get('current_directional_edge_count', 0)}` / `{cf_diagnostics.get('qualified_directional_edge_count', 0)}`",
        "",
        "## Notes",
        "",
        "- Temporal split uses the first 70% of each user's event history for training and the final 30% for held-out positives.",
        "- The evaluator builds production-policy signals, popularity, and CF in memory from train-only data to avoid future leakage and MongoDB writes.",
        "- Both current-policy and qualified-policy CF variants enforce min_support=2.",
        "- Both CF variants use the runtime pair computation, caps, recency decay, and symmetric edge selection.",
        "- Hidden or disliked train-time items are removed before recommendation metrics and counted by negative re-exposure checks.",
        "- CF evidence in this report is behavior-derived from train-time co-interactions, not semantic similarity.",
    ])
    return "\n".join(lines) + "\n"


def write_personalization_outputs(run_data: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    config_path = output_path / "config.json"
    per_user_json_path = output_path / "per_user_metrics.json"
    per_user_csv_path = output_path / "per_user_metrics.csv"
    baseline_path = output_path / "baseline_summaries.json"
    comparison_path = output_path / "comparisons.json"
    gate_path = output_path / "cf_qualified_gate.json"
    summary_path = output_path / "metrics_summary.md"
    manifest_path = output_path / "manifest.json"

    config_path.write_text(json.dumps(run_data.get("config", {}), indent=2, ensure_ascii=False), encoding="utf-8")
    per_user_json_path.write_text(json.dumps(run_data.get("per_user_metrics", []), indent=2, ensure_ascii=False), encoding="utf-8")
    baseline_path.write_text(json.dumps(run_data.get("baseline_summaries", []), indent=2, ensure_ascii=False), encoding="utf-8")
    comparison_path.write_text(json.dumps(run_data.get("comparisons", []), indent=2, ensure_ascii=False), encoding="utf-8")
    gate_path.write_text(json.dumps(run_data.get("cf_qualified_gate", {}), indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(generate_personalization_summary_md(run_data), encoding="utf-8")

    per_user_rows = run_data.get("per_user_metrics", [])
    csv_columns = [
        "user_id_hash",
        "baseline",
        "hit_rate_at_10",
        "recall_at_20",
        "map_at_20",
        "ndcg_at_20",
        "mrr_at_10",
        "diversity_at_20",
        "novelty_at_20",
        "cold_start_exposure_at_20",
        "cf_supported_recommendation_count",
        "negative_reexposure_count",
        "negative_reexposure_rate",
        "deliberate_hit_rate_at_10",
        "deliberate_recall_at_20",
        "deliberate_map_at_20",
        "deliberate_ndcg_at_20",
        "deliberate_mrr_at_10",
        "train_positive_item_ids",
        "held_out_positive_item_ids",
        "held_out_deliberate_item_ids",
        "train_negative_item_ids",
        "recommended_item_ids",
    ]
    with per_user_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns)
        writer.writeheader()
        for row in per_user_rows:
            csv_row = dict(row)
            for key in ("train_positive_item_ids", "held_out_positive_item_ids", "held_out_deliberate_item_ids", "train_negative_item_ids", "recommended_item_ids"):
                csv_row[key] = "|".join(csv_row.get(key, []))
            writer.writerow({key: csv_row.get(key, "") for key in csv_columns})

    manifest = {
        "run_id": run_data.get("config", {}).get("run_id", "unknown"),
        "generated_at": run_data.get("config", {}).get("created_at", _now_iso()),
        "files": {
            "config": str(config_path),
            "per_user_metrics_json": str(per_user_json_path),
            "per_user_metrics_csv": str(per_user_csv_path),
            "baseline_summaries": str(baseline_path),
            "comparisons": str(comparison_path),
            "cf_qualified_gate": str(gate_path),
            "metrics_summary": str(summary_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "config": str(config_path),
        "per_user_metrics_json": str(per_user_json_path),
        "per_user_metrics_csv": str(per_user_csv_path),
        "baseline_summaries": str(baseline_path),
        "comparisons": str(comparison_path),
        "cf_qualified_gate": str(gate_path),
        "metrics_summary": str(summary_path),
        "manifest": str(manifest_path),
    }


def load_live_personalization_inputs() -> dict[str, Any]:
    items_collection = get_items_collection()
    clickstream_collection = get_clickstream_events_collection()
    recommendation_logs_collection = get_recommendation_logs_collection()
    item_stats_collection = get_item_stats_collection()
    user_item_signals_collection = get_user_item_signals_collection()
    user_profiles_collection = get_user_profiles_collection()
    cf_edges_collection = get_item_item_cf_edges_collection()

    items = list(items_collection.find({}, {
        "_id": 1,
        "title_en": 1,
        "brand": 1,
        "category_id": 1,
        "price_bucket": 1,
        "quality_score": 1,
        "cold_start": 1,
    }))
    clickstream_events = list(clickstream_collection.find({}, {
        "event_id": 1,
        "user_id_hash": 1,
        "item_id": 1,
        "event_type": 1,
        "dwell_time_ms": 1,
        "timestamp": 1,
    }))
    recommendation_logs = list(recommendation_logs_collection.find({}, {
        "algorithm_version": 1,
        "ranking_version": 1,
    }))
    item_stats = list(item_stats_collection.find({}, {
        "item_id": 1,
        "quality_score": 1,
        "cold_start": 1,
    }))

    live_state_counts = {
        "recommendation_logs": recommendation_logs_collection.count_documents({}),
        "clickstream_events": clickstream_collection.count_documents({}),
        "user_item_signals": user_item_signals_collection.count_documents({}),
        "user_profiles": user_profiles_collection.count_documents({}),
        "item_item_cf_edges": cf_edges_collection.count_documents({}),
        "item_stats": item_stats_collection.count_documents({}),
        "items": items_collection.count_documents({}),
    }

    return {
        "items": items,
        "clickstream_events": clickstream_events,
        "recommendation_logs": recommendation_logs,
        "item_stats": item_stats,
        "live_state_counts": live_state_counts,
    }


def persist_evaluation_run(
    run_data: dict[str, Any],
    *,
    evaluation_runs_collection: Any | None = None,
) -> dict[str, Any]:
    if evaluation_runs_collection is None:
        evaluation_runs_collection = get_evaluation_runs_collection()

    payload = {
        "run_id": run_data.get("config", {}).get("run_id", "unknown"),
        "created_at": run_data.get("config", {}).get("created_at", _now_iso()),
        "algorithm_version": run_data.get("config", {}).get("algorithm_version", "unknown"),
        "ranking_version": run_data.get("config", {}).get("ranking_version", "unknown"),
        "data_label": run_data.get("config", {}).get("data_label", "synthetic/demo"),
        "baseline_summaries": run_data.get("baseline_summaries", []),
        "comparisons": run_data.get("comparisons", []),
        "evaluated_user_count": run_data.get("config", {}).get("evaluated_user_count", 0),
    }
    result = evaluation_runs_collection.insert_one(payload)
    return {"ok": True, "inserted_id": str(result.inserted_id)}
