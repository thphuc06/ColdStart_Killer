from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from src.search_pipeline import run_search
from src.mongodb import get_item_hype_profiles_collection
from src.recommendation.schemas import EMBEDDING_DIM
from src.utils import utc_now_iso


FusionMode = Literal["unionWith", "rankFusion", "scoreFusion"]
SUPPORTED_FUSION_MODES: tuple[FusionMode, ...] = ("unionWith", "rankFusion", "scoreFusion")
DEFAULT_FUSION_QUERIES: tuple[str, ...] = (
    "sunscreen for oily skin",
    "wireless earbuds",
    "coffee maker",
)


class FusionComparisonError(RuntimeError):
    """Raised when strict comparison should fail on an unavailable mode."""


@dataclass(frozen=True)
class FusionComparisonConfig:
    queries: tuple[str, ...] = DEFAULT_FUSION_QUERIES
    modes: tuple[FusionMode, ...] = ("unionWith", "rankFusion", "scoreFusion")
    top_k: int = 10
    strict: bool = False


def compute_top_k_overlap(baseline_item_ids: list[str], candidate_item_ids: list[str], *, k: int | None = None) -> float:
    """Return intersection-over-baseline-size for the top-k item ids."""
    if k is None:
        k = max(len(baseline_item_ids), len(candidate_item_ids))
    baseline = [item_id for item_id in baseline_item_ids[:k] if item_id]
    candidate = [item_id for item_id in candidate_item_ids[:k] if item_id]
    if not baseline:
        return 0.0
    return round(len(set(baseline) & set(candidate)) / len(set(baseline)), 6)


def _default_process_query(raw_query: str) -> dict[str, Any]:
    from src.query_processor import process_query

    return process_query(raw_query)


def _result_item_id(result: dict[str, Any]) -> str:
    return str(result.get("item_id") or result.get("_id") or "").strip()


def _result_score(result: dict[str, Any]) -> float | None:
    value = result.get("score")
    if value is None:
        value = result.get("fusion_score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_distribution(results: list[dict[str, Any]]) -> dict[str, float | None]:
    scores = [score for score in (_result_score(result) for result in results) if score is not None]
    if not scores:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": round(min(scores), 6),
        "max": round(max(scores), 6),
        "mean": round(statistics.fmean(scores), 6),
    }


def _explainable_count(results: list[dict[str, Any]]) -> int:
    count = 0
    for result in results:
        if result.get("explanation") or result.get("reason_badges") or result.get("debug"):
            count += 1
    return count


def _sanitize_error(exc: BaseException) -> str:
    message = str(exc).replace("\n", " ").strip()
    if len(message) > 500:
        return message[:497] + "..."
    return message


def _looks_unsupported(exc: BaseException) -> bool:
    text = str(exc).lower()
    unsupported_markers = (
        "rankfusion",
        "$rankfusion",
        "unsupported",
        "not supported",
        "unrecognized pipeline stage",
        "unknown stage",
        "requires atlas",
        "is not allowed",
    )
    return any(marker in text for marker in unsupported_markers)


def build_catalog_backed_query_fixture(
    raw_query: str,
    *,
    item_hype_profiles_collection: Any | None = None,
) -> dict[str, Any]:
    """Build a lightweight comparison fixture from an existing catalog embedding.

    This avoids running the local embedding model during smoke comparisons. It is
    intentionally labeled by callers as a catalog-backed smoke fixture, not a
    query-quality benchmark.
    """
    query = str(raw_query or "").strip()
    if not query:
        raise ValueError("query must be non-empty")
    collection = item_hype_profiles_collection or get_item_hype_profiles_collection()
    doc = collection.find_one(
        {"item_semantic_embedding": {"$type": "array"}},
        {"_id": 0, "item_id": 1, "item_semantic_embedding": 1},
    )
    embedding = doc.get("item_semantic_embedding") if isinstance(doc, dict) else None
    if not isinstance(embedding, list) or len(embedding) != EMBEDDING_DIM:
        raise RuntimeError("No valid item_hype_profiles embedding available for fusion comparison smoke fixture")
    return {
        "original_query": query,
        "language_detected": "en",
        "english_query": query,
        "hype_search_query_en": f"catalog-backed fusion comparison smoke for {query}",
        "bm25_search_query_en": query,
        "hard_filters": {},
        "query_embedding": [float(value) for value in embedding],
        "fixture_source": "catalog_backed_item_hype_profile",
        "source_item_id": str(doc.get("item_id") or "") if isinstance(doc, dict) else "",
    }


def safe_run_search_mode(
    fixture: dict[str, Any],
    *,
    mode: FusionMode,
    top_k: int,
    run_search_fn: Callable[..., list[dict[str, Any]]] = run_search,
    strict: bool = False,
) -> dict[str, Any]:
    """Run one search mode and convert unsupported native fusion into a report row."""
    started = time.perf_counter()
    if mode == "scoreFusion":
        return {
            "mode": mode,
            "status": "not_implemented",
            "latency_ms": 0.0,
            "result_count": 0,
            "top_item_ids": [],
            "top_results": [],
            "score_distribution": {"min": None, "max": None, "mean": None},
            "explainable_count": 0,
            "message": "$scoreFusion is proposed-only in this repo; no branch is implemented.",
        }
    try:
        results = list(run_search_fn(fixture, top_k=top_k, mode=mode))
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        if mode == "rankFusion" and _looks_unsupported(exc):
            if strict:
                raise FusionComparisonError(f"rankFusion unsupported in strict mode: {_sanitize_error(exc)}") from exc
            return {
                "mode": mode,
                "status": "unsupported",
                "latency_ms": latency_ms,
                "result_count": 0,
                "top_item_ids": [],
                "top_results": [],
                "score_distribution": {"min": None, "max": None, "mean": None},
                "explainable_count": 0,
                "message": _sanitize_error(exc),
            }
        if strict:
            raise FusionComparisonError(f"{mode} failed in strict mode: {_sanitize_error(exc)}") from exc
        return {
            "mode": mode,
            "status": "error",
            "latency_ms": latency_ms,
            "result_count": 0,
            "top_item_ids": [],
            "top_results": [],
            "score_distribution": {"min": None, "max": None, "mean": None},
            "explainable_count": 0,
            "message": _sanitize_error(exc),
        }
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    top_results = results[:top_k]
    top_item_ids = [_result_item_id(result) for result in top_results if _result_item_id(result)]
    return {
        "mode": mode,
        "status": "ok",
        "latency_ms": latency_ms,
        "result_count": len(results),
        "top_item_ids": top_item_ids,
        "top_results": top_results,
        "score_distribution": _score_distribution(top_results),
        "explainable_count": _explainable_count(top_results),
        "message": "",
    }


def compare_query_across_modes(
    raw_query: str,
    *,
    modes: Iterable[FusionMode] = ("unionWith", "rankFusion", "scoreFusion"),
    top_k: int = 10,
    process_query_fn: Callable[[str], dict[str, Any]] = _default_process_query,
    run_search_fn: Callable[..., list[dict[str, Any]]] = run_search,
    strict: bool = False,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    query = str(raw_query or "").strip()
    if not query:
        raise ValueError("query must be non-empty")
    selected_modes = tuple(modes)
    unsupported_modes = sorted(set(selected_modes) - set(SUPPORTED_FUSION_MODES))
    if unsupported_modes:
        raise ValueError(f"unsupported comparison modes: {', '.join(unsupported_modes)}")

    fixture = dict(process_query_fn(query))
    mode_results = [
        safe_run_search_mode(
            fixture,
            mode=mode,
            top_k=top_k,
            run_search_fn=run_search_fn,
            strict=strict,
        )
        for mode in selected_modes
    ]
    baseline = next((row for row in mode_results if row["mode"] == "unionWith" and row["status"] == "ok"), None)
    baseline_ids = list(baseline.get("top_item_ids", [])) if baseline else []
    for row in mode_results:
        row["top_k_overlap_vs_unionWith"] = (
            1.0
            if row["mode"] == "unionWith" and row["status"] == "ok"
            else compute_top_k_overlap(baseline_ids, list(row.get("top_item_ids", [])), k=top_k)
        )
    return {
        "query": query,
        "fixture_summary": {
            "source": fixture.get("fixture_source", "process_query"),
            "language_detected": fixture.get("language_detected"),
            "english_query": fixture.get("english_query"),
            "hard_filters": fixture.get("hard_filters") if isinstance(fixture.get("hard_filters"), dict) else {},
        },
        "modes": mode_results,
    }


def summarize_fusion_results(query_results: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode: dict[str, dict[str, Any]] = {}
    for query_result in query_results:
        for row in query_result.get("modes", []):
            mode = str(row.get("mode"))
            bucket = by_mode.setdefault(
                mode,
                {
                    "queries": 0,
                    "ok": 0,
                    "unsupported": 0,
                    "error": 0,
                    "not_implemented": 0,
                    "latencies": [],
                    "overlaps": [],
                },
            )
            bucket["queries"] += 1
            status = str(row.get("status") or "error")
            bucket[status] = int(bucket.get(status, 0)) + 1
            if status == "ok":
                bucket["latencies"].append(float(row.get("latency_ms") or 0.0))
                bucket["overlaps"].append(float(row.get("top_k_overlap_vs_unionWith") or 0.0))

    summary: dict[str, Any] = {}
    for mode, bucket in sorted(by_mode.items()):
        latencies = bucket.pop("latencies")
        overlaps = bucket.pop("overlaps")
        summary[mode] = {
            **bucket,
            "avg_latency_ms": round(statistics.fmean(latencies), 3) if latencies else None,
            "avg_overlap_vs_unionWith": round(statistics.fmean(overlaps), 6) if overlaps else None,
        }
    return summary


def run_fusion_comparison(
    *,
    config: FusionComparisonConfig | None = None,
    process_query_fn: Callable[[str], dict[str, Any]] = _default_process_query,
    run_search_fn: Callable[..., list[dict[str, Any]]] = run_search,
) -> dict[str, Any]:
    active_config = config or FusionComparisonConfig()
    query_results = [
        compare_query_across_modes(
            query,
            modes=active_config.modes,
            top_k=active_config.top_k,
            process_query_fn=process_query_fn,
            run_search_fn=run_search_fn,
            strict=active_config.strict,
        )
        for query in active_config.queries
    ]
    return {
        "ok": True,
        "comparison_type": "fusion_comparison",
        "created_at": utc_now_iso(),
        "dry_run": True,
        "mongo_write_performed": False,
        "default_search_unchanged": True,
        "default_search_mode": "unionWith",
        "score_fusion_status": "not_implemented",
        "caveat": (
            "Comparison only. Default production search remains unionWith/manual RRF. "
            "Native rankFusion support depends on Atlas tier/version."
        ),
        "config": {
            "queries": list(active_config.queries),
            "modes": list(active_config.modes),
            "top_k": active_config.top_k,
            "strict": active_config.strict,
        },
        "summary": summarize_fusion_results(query_results),
        "queries": query_results,
    }


def write_fusion_comparison_artifact(report: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stamp = str(report.get("created_at") or utc_now_iso()).replace(":", "").replace("+", "_")
    path = output_path / f"fusion_comparison_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path
