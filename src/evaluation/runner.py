"""Evaluation runner for ColdStart_Killer.

Orchestrates fixture generation, variant execution, metric computation,
and failure recording. Writes all artifacts to the output directory.

Import safety: no side effects at import time.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .contracts import (
    EvaluationQuery,
    EvaluationResult,
    FailureRecord,
    RelevanceJudgment,
    RunConfig,
)
from .dataset import judgments_by_query
from .metrics import aggregate_metrics, compute_query_metrics
from .variants import EVALUATION_VARIANTS, run_variant


FIXTURE_SCHEMA_VERSION = "1.0"


def _get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def build_query_fixture(query: EvaluationQuery) -> dict[str, Any]:
    """Build a search fixture from an EvaluationQuery using process_query()."""
    from src.query_processor import process_query
    return process_query(query.raw_query)


def build_fake_fixture(query: EvaluationQuery) -> dict[str, Any]:
    """Build a fake fixture for smoke testing without Ollama/BGE-M3."""
    return {
        "original_query": query.raw_query,
        "language_detected": query.language,
        "english_query": query.raw_query,
        "hype_search_query_en": f"user looking for {query.raw_query} for everyday use",
        "bm25_search_query_en": query.raw_query.lower(),
        "hard_filters": query.expected_filters,
        "query_embedding": [0.0] * 1024,
    }


def _build_fake_results(
    query_id: str, variant: str, top_k: int
) -> list[EvaluationResult]:
    """Generate fake results for smoke testing."""
    results: list[EvaluationResult] = []
    for i in range(min(top_k, 3)):
        results.append(EvaluationResult(
            query_id=query_id,
            variant=variant,
            rank=i + 1,
            item_id=f"FAKE_{variant}_{i}",
            score=round(1.0 / (i + 1), 4),
            title=f"Fake {variant} result {i + 1}",
            brand="FakeBrand",
            result_status="ok",
            is_cold_item=(i == 0),
        ))
    return results


def load_or_build_fixtures(
    queries: list[EvaluationQuery],
    fixture_path: str | Path,
    use_cache: bool,
    use_fake: bool = False,
    allow_stale: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[FailureRecord]]:
    """Load cached fixtures or build fresh ones.

    Returns:
        (fixtures_by_query_id, failures)
    """
    fixture_file = Path(fixture_path)
    fixtures: dict[str, dict[str, Any]] = {}
    failures: list[FailureRecord] = []

    # Try loading cached fixtures
    if use_cache and fixture_file.exists():
        try:
            with fixture_file.open("r", encoding="utf-8") as f:
                cached = json.load(f)
            schema_version = cached.get("fixture_schema_version", "")
            if schema_version != FIXTURE_SCHEMA_VERSION and not allow_stale:
                failures.append(FailureRecord(
                    stage="fixture_generation",
                    error_type="stale_fixture_schema",
                    error=f"Cached fixture schema {schema_version!r} != current {FIXTURE_SCHEMA_VERSION!r}",
                    recoverable=True,
                    details={"cached_version": schema_version, "current_version": FIXTURE_SCHEMA_VERSION},
                ))
            else:
                for qid, fix in cached.get("fixtures", {}).items():
                    fixtures[qid] = fix
                return fixtures, failures
        except (json.JSONDecodeError, Exception) as exc:
            failures.append(FailureRecord(
                stage="fixture_generation",
                error_type="invalid_input_file",
                error=f"Failed to load cached fixtures: {exc}",
                recoverable=True,
            ))

    # Build fixtures
    for query in queries:
        try:
            if use_fake:
                fix = build_fake_fixture(query)
            else:
                fix = build_query_fixture(query)
            fixtures[query.query_id] = fix
        except Exception as exc:
            failures.append(FailureRecord(
                stage="fixture_generation",
                error_type="fixture_generation_failed",
                error=f"{type(exc).__name__}: {exc}",
                recoverable=True,
                query_id=query.query_id,
                next_file_to_inspect="src/query_processor.py",
                next_function_to_inspect="process_query",
            ))

    return fixtures, failures


def _save_fixtures(fixtures: dict[str, dict[str, Any]], path: Path, source_query_file: str) -> None:
    """Save fixtures to cache file with schema version."""
    cache = {
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_query_file": source_query_file,
        "query_processor_version": "1.0",
        "fixtures": fixtures,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False, default=str)


def run_evaluation(
    config: RunConfig,
    queries: list[EvaluationQuery],
    judgments: list[RelevanceJudgment],
    use_fake_results: bool = False,
    collection: Any | None = None,
    items_collection: Any | None = None,
) -> dict[str, Any]:
    """Run the full evaluation pipeline.

    Returns a dict with all computed artifacts ready for writing.
    """
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_failures: list[FailureRecord] = []
    all_results: list[EvaluationResult] = []
    per_query_metrics: list[dict[str, Any]] = []
    latency_rows: list[dict[str, Any]] = []

    # 1. Build fixtures (track per-query fixture latency)
    fixture_path = output_dir / "query_fixtures.json"
    fixture_cache_exists = fixture_path.exists()
    fixture_latency: dict[str, float] = {}
    t_fix_start = time.perf_counter()
    fixtures, fix_failures = load_or_build_fixtures(
        queries, fixture_path,
        use_cache=config.use_cached_fixtures,
        use_fake=use_fake_results,
    )
    t_fix_end = time.perf_counter()
    total_fixture_ms = round((t_fix_end - t_fix_start) * 1000, 2)
    # Distribute fixture latency evenly per query (exact per-query timing not available)
    per_query_fixture_ms = round(total_fixture_ms / max(len(queries), 1), 2)
    for q in queries:
        fixture_latency[q.query_id] = per_query_fixture_ms
    all_failures.extend(fix_failures)
    _save_fixtures(fixtures, fixture_path, config.queries_path)
    cache_was_used = (
        config.use_cached_fixtures
        and fixture_cache_exists
        and not any(f.stage == "fixture_generation" for f in fix_failures)
    )
    if cache_was_used:
        fixture_source = "cached"
    elif use_fake_results:
        fixture_source = "fake"
    else:
        fixture_source = "fresh"

    # 2. Index judgments
    j_by_q = judgments_by_query(judgments)

    # 3. Run variants for each query
    variants = config.variants or list(EVALUATION_VARIANTS)
    for query in queries:
        fixture = fixtures.get(query.query_id)
        if fixture is None:
            continue

        for variant in variants:
            t_start = time.perf_counter()

            if use_fake_results:
                results = _build_fake_results(query.query_id, variant, config.top_k)
                failure = None
            else:
                results, failure = run_variant(
                    fixture, variant, query.query_id, config.top_k,
                    collection=collection,
                    items_collection=items_collection,
                )

            t_end = time.perf_counter()
            search_latency_ms = round((t_end - t_start) * 1000, 2)

            if failure:
                all_failures.append(failure)
                continue

            all_results.extend(results)

            # Mark empty results
            result_status = "ok" if results else "ok_empty"

            qp_latency = fixture_latency.get(query.query_id, 0.0)
            latency_rows.append({
                "query_id": query.query_id,
                "variant": variant,
                "query_processing_latency_ms": qp_latency,
                "search_latency_ms": search_latency_ms,
                "total_latency_ms": round(qp_latency + search_latency_ms, 2),
                "result_count": len(results),
                "result_status": result_status,
            })

            # Compute metrics for this (query, variant)
            query_judgments = j_by_q.get(query.query_id, {})
            metrics = compute_query_metrics(
                results, query_judgments,
                k_values=config.k_values,
                relevance_threshold=config.relevance_threshold,
            )
            metrics["query_id"] = query.query_id
            metrics["variant"] = variant
            metrics["slices"] = ",".join(query.slices)
            metrics["result_status"] = result_status
            per_query_metrics.append(metrics)

    # 4. Aggregate metrics
    variant_summaries = aggregate_metrics(per_query_metrics, ["variant"])

    # Per-slice summaries for each variant
    # Expand slices for per-slice metrics
    slice_rows: list[dict[str, object]] = []
    for row in per_query_metrics:
        slices = str(row.get("slices", "")).split(",")
        for s in slices:
            s = s.strip()
            if s:
                slice_row = dict(row)
                slice_row["slice"] = s
                slice_rows.append(slice_row)
    slice_summaries = aggregate_metrics(slice_rows, ["variant", "slice"])
    vietnamese_hybrid = next(
        (s for s in slice_summaries if s.get("variant") == "hybrid_union" and s.get("slice") == "vietnamese"),
        {},
    )
    vietnamese_title = next(
        (s for s in slice_summaries if s.get("variant") == "title_only" and s.get("slice") == "vietnamese"),
        {},
    )

    # 5. Compute judgment coverage statistics
    total_queries = len(queries)
    judged_queries: set[str] = set()
    positive_judged_queries: set[str] = set()
    total_results = 0
    total_judged_results = 0

    for m in per_query_metrics:
        if m.get("variant") == (variants[0] if variants else "hybrid_union"):
            if m.get("has_judgments"):
                judged_queries.add(str(m["query_id"]))
            if m.get("has_positive_judgment"):
                positive_judged_queries.add(str(m["query_id"]))
            total_results += m.get("result_count", 0)
            total_judged_results += m.get("judged_result_count", 0)

    # Vietnamese slice judged count
    vi_judged_queries: set[str] = set()
    for m in per_query_metrics:
        slices_str = str(m.get("slices", ""))
        if "vietnamese" in slices_str and m.get("has_judgments"):
            vi_judged_queries.add(str(m["query_id"]))

    # Determine report status
    judged_count = len(judged_queries)
    positive_count = len(positive_judged_queries)
    if judged_count < 30:
        report_status = "insufficient_judgments"
    elif positive_count < 20:
        report_status = "insufficient_positive_judgments"
    else:
        report_status = "sufficient"

    coverage_stats = {
        "total_query_count": total_queries,
        "judged_query_count": judged_count,
        "positive_judged_query_count": positive_count,
        "query_judgment_coverage_rate": round(judged_count / total_queries, 4) if total_queries else 0,
        "result_judgment_coverage_rate": round(total_judged_results / total_results, 4) if total_results else 0,
        "report_status": report_status,
        "vietnamese_judged_query_count": len(vi_judged_queries),
    }

    # 6. Compute cold/warm distribution
    cold_item_ids: set[str] = set()
    warm_item_ids: set[str] = set()
    unknown_item_ids: set[str] = set()
    for r in all_results:
        if r.variant == (variants[0] if variants else "hybrid_union"):
            if r.is_cold_item is True:
                cold_item_ids.add(r.item_id)
            elif r.is_cold_item is False:
                warm_item_ids.add(r.item_id)
            else:
                unknown_item_ids.add(r.item_id)

    total_known = len(cold_item_ids) + len(warm_item_ids)
    cold_pct = round(len(cold_item_ids) / max(total_known, 1) * 100, 1)
    cold_warm_ratio = {
        "cold_items": len(cold_item_ids),
        "warm_items": len(warm_item_ids),
        "unknown_items": len(unknown_item_ids),
        "cold_percentage": cold_pct,
        "dataset_is_cold_dominant": len(cold_item_ids) > len(warm_item_ids) * 3 if warm_item_ids else True,
    }

    # 7. Enrich config with coverage stats for claim gating
    enriched_config = dict(asdict(config))
    mongodb_source = (
        "fake_results" if use_fake_results
        else "injected_collection" if collection is not None or items_collection is not None
        else "live"
    )
    mongodb_live = config.mongodb_live
    if mongodb_live is None:
        mongodb_live = mongodb_source == "live"

    enriched_config.update(coverage_stats)
    enriched_config.update({
        "created_at": config.created_at or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_commit": config.git_commit or _get_git_commit(),
        "plan_version": config.plan_version or "v2.0",
        "code_version": config.code_version or "2.0.0",
        "python_version": config.python_version or sys.version,
        "platform": config.platform or platform.platform(),
        "mongodb_live": mongodb_live,
        "mongodb_source": mongodb_source,
        "fixture_source": fixture_source,
        "warm_cache": cache_was_used,
        "judgment_count": len(judgments),
        "query_count": len(queries),
        "result_count": len(all_results),
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "dataset_is_cold_dominant": cold_warm_ratio["dataset_is_cold_dominant"],
        "cold_warm_ratio": cold_warm_ratio,
        "latency_sample_count": len(latency_rows),
        "vietnamese_hybrid_ndcg_at_10": vietnamese_hybrid.get("ndcg_at_10"),
        "vietnamese_title_ndcg_at_10": vietnamese_title.get("ndcg_at_10"),
    })

    return {
        "config": enriched_config,
        "queries": [asdict(q) for q in queries],
        "results": [asdict(r) for r in all_results],
        "per_query_metrics": per_query_metrics,
        "variant_summaries": variant_summaries,
        "slice_summaries": slice_summaries,
        "latency": latency_rows,
        "failures": [asdict(f) for f in all_failures],
        "coverage_stats": coverage_stats,
        "cold_warm_ratio": cold_warm_ratio,
    }
