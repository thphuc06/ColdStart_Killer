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
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
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
from .metrics import aggregate_metrics, compute_query_metrics, compute_slice_confidence, compute_variant_comparisons
from .variants import EVALUATION_VARIANTS, run_variant


FIXTURE_SCHEMA_VERSION = "1.0"
EVALUATION_SCHEMA_VERSION = "2.2"
ARTIFACT_CONTRACT_VERSION = "1.0"


def _get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def _file_fingerprint(path_value: str) -> dict[str, object]:
    """Return stable file lineage metadata without requiring the file to exist."""
    path = Path(path_value) if path_value else None
    if path is None:
        return {"path": path_value, "exists": False}
    if not path.exists() or not path.is_file():
        return {"path": path_value, "exists": False}
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path_value,
        "exists": True,
        "sha256": digest.hexdigest(),
        "byte_count": path.stat().st_size,
    }


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    index = min(int(len(sorted_values) * percentile), len(sorted_values) - 1)
    return sorted_values[index]


def _summarize_latency(latency_rows: list[dict[str, Any]]) -> dict[str, dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for key in ("query_processing_latency_ms", "search_latency_ms", "total_latency_ms"):
        values = sorted(
            float(row[key])
            for row in latency_rows
            if isinstance(row.get(key), (int, float))
        )
        confidence = "high" if len(values) >= 50 else ("medium" if len(values) >= 20 else "low")
        summaries[key] = {
            "sample_count": len(values),
            "p50": round(_percentile(values, 0.50), 2) if values else None,
            "p95": round(_percentile(values, 0.95), 2) if values else None,
            "confidence": confidence,
            "blockers": [] if len(values) >= 20 else [f"sample_count {len(values)} < 20"],
        }
    return summaries


def _source_status(sources: list[str]) -> str:
    source_set = {source for source in sources if source}
    if not source_set:
        return "unjudged"
    if source_set == {"human_audited"}:
        return "human_audited"
    if source_set == {"ai_assisted"}:
        return "ai_assisted"
    return "mixed"


def _summarize_judgment_audit(
    queries: list[EvaluationQuery],
    judgments: list[RelevanceJudgment],
) -> dict[str, Any]:
    """Summarize judgment provenance without changing legacy judgment meaning."""
    source_counts = Counter(j.judgment_source for j in judgments)
    source_counts_dict = {source: count for source, count in sorted(source_counts.items()) if count > 0}
    judgments_by_q: dict[str, list[RelevanceJudgment]] = {}
    for judgment in judgments:
        judgments_by_q.setdefault(judgment.query_id, []).append(judgment)

    slices_by_name: dict[str, list[EvaluationQuery]] = {}
    for query in queries:
        for slice_name in query.slices:
            if slice_name:
                slices_by_name.setdefault(slice_name, []).append(query)

    slice_audit: list[dict[str, Any]] = []
    for slice_name in sorted(slices_by_name):
        slice_queries = slices_by_name[slice_name]
        judged_query_count = 0
        human_audited_query_count = 0
        query_sources: list[str] = []
        for query in slice_queries:
            q_judgments = judgments_by_q.get(query.query_id, [])
            if not q_judgments:
                continue
            judged_query_count += 1
            sources = [judgment.judgment_source for judgment in q_judgments]
            query_sources.extend(sources)
            if sources and all(source == "human_audited" for source in sources):
                human_audited_query_count += 1

        audit_status = _source_status(query_sources)
        blockers: list[str] = []
        if judged_query_count < len(slice_queries):
            blockers.append(f"judged_query_count {judged_query_count} < query_count {len(slice_queries)}")
        if audit_status != "human_audited":
            blockers.append(f"judgment_source_status is {audit_status}")
        slice_audit.append({
            "slice": slice_name,
            "query_count": len(slice_queries),
            "judged_query_count": judged_query_count,
            "human_audited_query_count": human_audited_query_count,
            "audit_status": audit_status,
            "demo_readiness": "claim_grade" if not blockers else "directional_only",
            "blockers": blockers,
        })

    total = len(judgments)
    human_count = source_counts.get("human_audited", 0)
    return {
        "overall_status": _source_status([judgment.judgment_source for judgment in judgments]),
        "source_counts": source_counts_dict,
        "total_judgment_count": total,
        "human_audited_judgment_count": human_count,
        "human_audited_rate": round(human_count / total, 4) if total else 0.0,
        "slice_audit": slice_audit,
    }


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
    allow_stale_fixtures: bool = False,
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
        allow_stale=allow_stale_fixtures,
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
    variant_comparisons = compute_variant_comparisons(per_query_metrics)
    slice_variant_comparisons: list[dict[str, object]] = []
    for slice_name in sorted({str(row.get("slice", "")) for row in slice_rows if row.get("slice")}):
        scoped_rows = [row for row in slice_rows if row.get("slice") == slice_name]
        slice_variant_comparisons.extend(compute_variant_comparisons(
            scoped_rows,
            min_paired_queries=5,
            min_positive_judged_pairs=3,
            scope=f"slice:{slice_name}",
        ))
    slice_confidence = compute_slice_confidence(slice_summaries)
    slice_metrics: dict[str, dict[str, dict[str, object]]] = {}
    for summary in slice_summaries:
        slice_name = str(summary.get("slice", ""))
        variant_name = str(summary.get("variant", ""))
        if slice_name and variant_name:
            slice_metrics.setdefault(slice_name, {})[variant_name] = dict(summary)
    latency_summary = _summarize_latency(latency_rows)
    judgment_audit = _summarize_judgment_audit(queries, judgments)
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
        query_id = str(m.get("query_id", ""))
        if not query_id:
            continue
        if m.get("has_judgments"):
            judged_queries.add(query_id)
        if m.get("has_positive_judgment"):
            positive_judged_queries.add(query_id)
        total_results += int(m.get("result_count", 0) or 0)
        total_judged_results += int(m.get("judged_result_count", 0) or 0)

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
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "input_fingerprints": {
            "queries": _file_fingerprint(config.queries_path),
            "judgments": _file_fingerprint(config.judgments_path),
        },
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "dataset_is_cold_dominant": cold_warm_ratio["dataset_is_cold_dominant"],
        "cold_warm_ratio": cold_warm_ratio,
        "latency_sample_count": len(latency_rows),
        "latency_summary": latency_summary,
        "variant_comparisons": variant_comparisons,
        "slice_variant_comparisons": slice_variant_comparisons,
        "slice_confidence": slice_confidence,
        "slice_metrics": slice_metrics,
        "judgment_audit": judgment_audit,
        "vietnamese_hybrid_ndcg_at_10": vietnamese_hybrid.get("ndcg_at_10"),
        "vietnamese_title_ndcg_at_10": vietnamese_title.get("ndcg_at_10"),
    })

    return {
        "config": enriched_config,
        "queries": [asdict(q) for q in queries],
        "results": [asdict(r) for r in all_results],
        "per_query_metrics": per_query_metrics,
        "variant_summaries": variant_summaries,
        "variant_comparisons": variant_comparisons,
        "slice_variant_comparisons": slice_variant_comparisons,
        "slice_summaries": slice_summaries,
        "slice_confidence": slice_confidence,
        "slice_metrics": slice_metrics,
        "judgment_audit": judgment_audit,
        "latency": latency_rows,
        "latency_summary": latency_summary,
        "failures": [asdict(f) for f in all_failures],
        "coverage_stats": coverage_stats,
        "cold_warm_ratio": cold_warm_ratio,
    }
