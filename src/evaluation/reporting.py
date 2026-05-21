"""Evaluation reporting for ColdStart_Killer.

Generates Markdown reports, JSON summaries, CSV outputs,
manifest files, and claim status tables.

Import safety: no side effects at import time.
"""

from __future__ import annotations

import csv
import json
import time
from io import StringIO
from pathlib import Path
from typing import Any

from .contracts import ClaimStatus


def decide_claim_status(
    variant_summaries: list[dict[str, object]],
    config: dict[str, Any],
    failures: list[dict[str, Any]],
) -> list[ClaimStatus]:
    """Generate deterministic claim statuses from metrics and gates."""
    claims: list[ClaimStatus] = []

    # Helper: find variant summary
    def _get_variant(name: str) -> dict[str, object] | None:
        for s in variant_summaries:
            if s.get("variant") == name:
                return s
        return None

    hybrid = _get_variant("hybrid_union")
    title = _get_variant("title_only")
    vector = _get_variant("vector_only")
    bm25 = _get_variant("bm25_only")
    no_cold = _get_variant("hybrid_no_cold_boost")

    # Check if variants are available
    failed_variants = {f.get("variant") for f in failures if f.get("error_type") == "variant_unavailable"}

    # Claim 1: Hybrid beats title baseline
    if "title_only" in failed_variants or title is None:
        claims.append(ClaimStatus(
            claim="Hybrid beats title baseline",
            status="needs_more_evidence",
            blocker="title_only variant is unavailable",
        ))
    elif hybrid and title:
        hybrid_ndcg = hybrid.get("ndcg_at_10")
        title_ndcg = title.get("ndcg_at_10")
        if hybrid_ndcg is not None and title_ndcg is not None and hybrid_ndcg > title_ndcg:
            claims.append(ClaimStatus(
                claim="Hybrid beats title baseline",
                status="supported",
                evidence=f"hybrid NDCG@10={hybrid_ndcg} > title NDCG@10={title_ndcg}",
            ))
        else:
            claims.append(ClaimStatus(
                claim="Hybrid beats title baseline",
                status="unsupported",
                evidence=f"hybrid NDCG@10={hybrid_ndcg}, title NDCG@10={title_ndcg}",
            ))

    # Claim 2: Hybrid beats single-channel baselines
    if hybrid and vector and bm25:
        h_n = hybrid.get("ndcg_at_10")
        v_n = vector.get("ndcg_at_10")
        b_n = bm25.get("ndcg_at_10")
        if all(x is not None for x in [h_n, v_n, b_n]):
            if h_n > v_n and h_n > b_n:
                claims.append(ClaimStatus(
                    claim="Hybrid beats single-channel baselines",
                    status="supported",
                    evidence=f"hybrid={h_n} > vector={v_n}, bm25={b_n}",
                ))
            else:
                claims.append(ClaimStatus(
                    claim="Hybrid beats single-channel baselines",
                    status="unsupported",
                    evidence=f"hybrid={h_n}, vector={v_n}, bm25={b_n}",
                ))
        else:
            claims.append(ClaimStatus(
                claim="Hybrid beats single-channel baselines",
                status="needs_more_evidence",
                blocker="Some NDCG@10 metrics are null",
            ))
    else:
        claims.append(ClaimStatus(
            claim="Hybrid beats single-channel baselines",
            status="needs_more_evidence",
            blocker="Missing variant summaries",
        ))

    # Claim 3: Cold-start retrieval is useful
    if hybrid:
        cold_rate = hybrid.get("cold_relevant_rate_at_10")
        if cold_rate is not None and cold_rate > 0:
            claims.append(ClaimStatus(
                claim="Cold-start retrieval is useful",
                status="supported",
                evidence=f"ColdRelevantRate@10={cold_rate}",
            ))
        elif cold_rate == 0:
            claims.append(ClaimStatus(
                claim="Cold-start retrieval is useful",
                status="unsupported",
                evidence="ColdRelevantRate@10=0",
            ))
        else:
            claims.append(ClaimStatus(
                claim="Cold-start retrieval is useful",
                status="needs_more_evidence",
                blocker="ColdRelevantRate@10 is null (no cold items in judged results)",
            ))

    # Claim 4: Cold-start window was measured
    claims.append(ClaimStatus(
        claim="Cold-start window was measured",
        status="needs_more_evidence",
        blocker="indexed_at and first_seen_in_top_k_at timestamps not available in this run",
    ))

    # Claim 5: Vietnamese robustness
    claims.append(ClaimStatus(
        claim="Vietnamese robustness",
        status="needs_more_evidence",
        blocker="Requires Vietnamese slice analysis with sufficient judged queries",
    ))

    # Claim 6: Live end-to-end latency
    use_cached = config.get("use_cached_fixtures", True)
    mongodb_live = config.get("mongodb_live")
    if use_cached or not mongodb_live:
        claims.append(ClaimStatus(
            claim="Live end-to-end latency",
            status="needs_more_evidence",
            blocker="Cached fixtures used or MongoDB not live" if use_cached else "MongoDB not confirmed live",
        ))
    else:
        claims.append(ClaimStatus(
            claim="Live end-to-end latency",
            status="supported",
            evidence="Live MongoDB with fresh fixtures",
        ))

    return claims


def generate_variant_availability_table(
    variants: list[str],
    failures: list[dict[str, Any]],
) -> str:
    """Generate the Variant Availability markdown table."""
    failed_variants: dict[str, str] = {}
    for f in failures:
        v = f.get("variant", "")
        if v and f.get("error_type") == "variant_unavailable":
            failed_variants[v] = f.get("error", "unknown")

    lines = ["| variant | availability | reason | recoverable | included_in_comparison |"]
    lines.append("|---|---|---|---|---|")
    for v in variants:
        if v in failed_variants:
            lines.append(f"| {v} | unavailable | {failed_variants[v]} | yes | no |")
        else:
            lines.append(f"| {v} | available | — | — | yes |")
    return "\n".join(lines)


def generate_metrics_summary_md(
    run_data: dict[str, Any],
) -> str:
    """Generate the main metrics_summary.md report."""
    config = run_data.get("config", {})
    variant_summaries = run_data.get("variant_summaries", [])
    failures = run_data.get("failures", [])
    latency = run_data.get("latency", [])

    lines: list[str] = []
    lines.append("# Evaluation Report")
    lines.append("")
    lines.append(f"**Run ID:** {config.get('run_id', 'unknown')}")
    lines.append(f"**Created at:** {config.get('created_at', 'unknown')}")
    lines.append(f"**K values:** {config.get('k_values', [])}")
    lines.append(f"**Relevance threshold:** {config.get('relevance_threshold', 2)}")
    lines.append(f"**Git commit:** {config.get('git_commit', 'N/A')}")
    lines.append("")

    # Variant Availability
    lines.append("## Variant Availability")
    lines.append("")
    variants = config.get("variants", list(run_data.get("variant_summaries", [{}])))
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        variant_names = [v.get("variant", "") for v in variants]
    else:
        variant_names = variants if isinstance(variants, list) else []
    lines.append(generate_variant_availability_table(variant_names, failures))
    lines.append("")

    # Main Variant Comparison
    lines.append("## Variant Comparison")
    lines.append("")
    headers = "| variant | query_count | NDCG@10 | Recall@10 | MRR@10 | Precision@5 | HitRate@10 | ColdRelevantRate@10 |"
    lines.append(headers)
    lines.append("|---|---|---|---|---|---|---|---|")
    for vs in variant_summaries:
        v = vs.get("variant", "")
        qc = vs.get("query_count", 0)
        ndcg = vs.get("ndcg_at_10", "N/A")
        recall = vs.get("recall_at_10", "N/A")
        mrr = vs.get("mrr_at_10", "N/A")
        prec = vs.get("precision_at_5", "N/A")
        hr = vs.get("hit_rate_at_10", "N/A")
        cold = vs.get("cold_relevant_rate_at_10", "N/A")
        lines.append(f"| {v} | {qc} | {ndcg} | {recall} | {mrr} | {prec} | {hr} | {cold} |")
    lines.append("")

    # Claim Status
    claims = decide_claim_status(variant_summaries, config, failures)
    lines.append("## Claim Status")
    lines.append("")
    lines.append("| claim | status | evidence | blocker |")
    lines.append("|---|---|---|---|")
    for c in claims:
        lines.append(f"| {c.claim} | {c.status} | {c.evidence} | {c.blocker} |")
    lines.append("")

    # Failure Summary
    if failures:
        lines.append("## Failure Summary")
        lines.append("")
        error_types: dict[str, int] = {}
        for f in failures:
            et = f.get("error_type", "unknown")
            error_types[et] = error_types.get(et, 0) + 1
        lines.append("| error_type | count |")
        lines.append("|---|---|")
        for et, cnt in sorted(error_types.items()):
            lines.append(f"| {et} | {cnt} |")
        lines.append("")

    # Latency Summary
    if latency:
        search_latencies = [r["search_latency_ms"] for r in latency if "search_latency_ms" in r]
        total_latencies = [r["total_latency_ms"] for r in latency if "total_latency_ms" in r]
        if search_latencies:
            search_latencies.sort()
            total_latencies.sort()
            s_p50 = search_latencies[len(search_latencies) // 2]
            s_p95_idx = min(int(len(search_latencies) * 0.95), len(search_latencies) - 1)
            s_p95 = search_latencies[s_p95_idx]
            lines.append("## Latency")
            lines.append("")
            lines.append(f"- **Sample size:** {len(search_latencies)}")
            lines.append(f"- **P50 search latency:** {s_p50:.1f}ms")
            lines.append(f"- **P95 search latency:** {s_p95:.1f}ms")
            if total_latencies:
                t_p50 = total_latencies[len(total_latencies) // 2]
                t_p95 = total_latencies[min(int(len(total_latencies) * 0.95), len(total_latencies) - 1)]
                lines.append(f"- **P50 total latency:** {t_p50:.1f}ms")
                lines.append(f"- **P95 total latency:** {t_p95:.1f}ms")
            confidence = "high" if len(search_latencies) >= 50 else ("medium" if len(search_latencies) >= 20 else "low")
            lines.append(f"- **Latency confidence:** {confidence}")
            lines.append("")

    # Automatic Recommendations
    lines.append("## Recommendations")
    lines.append("")
    recs = _generate_recommendations(variant_summaries)
    for rec in recs:
        lines.append(f"- {rec}")
    if not recs:
        lines.append("- No automatic recommendations at this time.")
    lines.append("")

    # Commands Run / Not Run
    lines.append("## Commands")
    lines.append("")
    run_id = config.get("run_id", "unknown")
    out_dir = config.get("output_dir", f".runtime/evaluation/{run_id}")
    queries_path = config.get("queries_path", "evaluation/queries/retrieval_queries_seed.json")
    judgments_path = config.get("judgments_path", "evaluation/judgments/retrieval_judgments_seed.json")

    lines.append("### Commands Run")
    lines.append("")
    lines.append(f"```bash")
    lines.append(f"python scripts/run_evaluation.py \\")
    lines.append(f"  --queries {queries_path} \\")
    lines.append(f"  --judgments {judgments_path} \\")
    lines.append(f"  --out {out_dir}")
    lines.append(f"```")
    lines.append("")

    lines.append("### Commands Not Run")
    lines.append("")
    lines.append("```bash")
    lines.append("# Run diagnostics separately:")
    lines.append(f"python scripts/run_eval_diagnostics.py --probes evaluation/queries/diagnostic_probes.json --out {out_dir}/diagnostics")
    lines.append("")
    lines.append("# Build judgment pool for labeling:")
    lines.append(f"python scripts/build_eval_pool.py --queries {queries_path} --out {out_dir}/pool --top-k 20")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def _generate_recommendations(variant_summaries: list[dict[str, object]]) -> list[str]:
    """Generate automatic recommendations from variant comparison."""
    recs: list[str] = []

    def _get(name: str) -> dict[str, object] | None:
        return next((s for s in variant_summaries if s.get("variant") == name), None)

    hybrid = _get("hybrid_union")
    title = _get("title_only")
    vector = _get("vector_only")
    bm25 = _get("bm25_only")
    no_cold = _get("hybrid_no_cold_boost")

    if hybrid and title:
        h, t = hybrid.get("ndcg_at_10"), title.get("ndcg_at_10")
        if h is not None and t is not None and isinstance(h, (int, float)) and isinstance(t, (int, float)):
            if h - t < 0.05:
                recs.append(
                    "title_only is close to hybrid_union — inspect HyPE/proposition generation quality "
                    "in `src/llm_hype.py` and `src/llm_propositions.py`."
                )

    if hybrid and vector:
        h, v = hybrid.get("ndcg_at_10"), vector.get("ndcg_at_10")
        if h is not None and v is not None and isinstance(h, (int, float)) and isinstance(v, (int, float)):
            if v > h:
                recs.append(
                    "vector_only beats hybrid_union — inspect BM25 noise in "
                    "`src/search_pipeline.py::atlas_search_compound()`."
                )

    if hybrid and bm25:
        h, b = hybrid.get("ndcg_at_10"), bm25.get("ndcg_at_10")
        if h is not None and b is not None and isinstance(h, (int, float)) and isinstance(b, (int, float)):
            if b > h:
                recs.append(
                    "bm25_only beats hybrid_union — inspect HyPE quality in "
                    "`src/llm_hype.py::build_contextual_header()`."
                )

    if hybrid and no_cold:
        h, nc = hybrid.get("ndcg_at_10"), no_cold.get("ndcg_at_10")
        if h is not None and nc is not None and isinstance(h, (int, float)) and isinstance(nc, (int, float)):
            if nc > h:
                recs.append(
                    "hybrid_no_cold_boost beats hybrid_union — inspect COLD_START_BOOST value "
                    "in `src/search_pipeline.py`."
                )

    return recs


def write_evaluation_outputs(run_data: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    """Write all evaluation output files. Returns paths written."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    # config.json
    p = out / "config.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(run_data["config"], f, indent=2, ensure_ascii=False, default=str)
    paths["config"] = str(p)

    # failures.json
    p = out / "failures.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(run_data.get("failures", []), f, indent=2, ensure_ascii=False, default=str)
    paths["failures"] = str(p)

    # layer2_raw_results.json
    p = out / "layer2_raw_results.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(run_data.get("results", []), f, indent=2, ensure_ascii=False, default=str)
    paths["raw_results"] = str(p)

    # layer2_metrics_by_query.csv
    per_q = run_data.get("per_query_metrics", [])
    if per_q:
        p = out / "layer2_metrics_by_query.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(per_q[0].keys()))
            writer.writeheader()
            writer.writerows(per_q)
        paths["metrics_by_query"] = str(p)

    # layer2_metrics_summary.json
    p = out / "layer2_metrics_summary.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(run_data.get("variant_summaries", []), f, indent=2, ensure_ascii=False, default=str)
    paths["metrics_summary_json"] = str(p)

    # latency_by_query.csv
    lat = run_data.get("latency", [])
    if lat:
        p = out / "latency_by_query.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(lat[0].keys()))
            writer.writeheader()
            writer.writerows(lat)
        paths["latency"] = str(p)

    # metrics_summary.md
    p = out / "metrics_summary.md"
    md = generate_metrics_summary_md(run_data)
    with p.open("w", encoding="utf-8") as f:
        f.write(md)
    paths["metrics_summary_md"] = str(p)

    # manifest.json
    p = out / "manifest.json"
    manifest = {
        "run_id": run_data["config"].get("run_id", ""),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "config_path": "config.json",
        "artifacts": [
            {"path": "layer2_metrics_summary.json", "type": "metrics_summary", "required": True},
            {"path": "metrics_summary.md", "type": "markdown_report", "required": True},
            {"path": "layer2_raw_results.json", "type": "raw_results", "required": False},
            {"path": "layer2_metrics_by_query.csv", "type": "metrics_detail", "required": False},
            {"path": "latency_by_query.csv", "type": "latency_detail", "required": False},
        ],
        "failures_path": "failures.json",
    }
    with p.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    paths["manifest"] = str(p)

    return paths
