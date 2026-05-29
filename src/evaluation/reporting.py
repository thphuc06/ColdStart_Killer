"""Evaluation reporting for ColdStart_Killer.

Generates Markdown reports, JSON summaries, CSV outputs,
manifest files, and claim status tables.

Import safety: no side effects at import time.
"""

from __future__ import annotations

import csv
import json
import time
from shutil import copyfile
from io import StringIO
from pathlib import Path
from typing import Any

from .contracts import ClaimStatus
from .explanation_check import check_explanation_quality


def decide_claim_status(
    variant_summaries: list[dict[str, object]],
    config: dict[str, Any],
    failures: list[dict[str, Any]],
) -> list[ClaimStatus]:
    """Generate deterministic claim statuses from metrics and gates.

    Rules:
    - needs_more_evidence: when data is insufficient (missing judgments, null metrics, missing variants)
    - unsupported: ONLY when judgment gates pass AND metrics are non-None AND comparison genuinely fails
    - supported: ONLY when judgment gates pass AND metrics are non-None AND comparison genuinely passes
    """
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
    comparison_diagnostics = []
    for diag_source in (config.get("variant_comparisons", []), config.get("slice_variant_comparisons", [])):
        if isinstance(diag_source, list):
            comparison_diagnostics.extend(diag_source)
    slice_confidence = config.get("slice_confidence", [])
    slice_metrics = config.get("slice_metrics", {})

    def _comparison_diag(comparison: str, metric: str, scope: str = "overall") -> dict[str, Any] | None:
        if not isinstance(comparison_diagnostics, list):
            return None
        for diag in comparison_diagnostics:
            if not isinstance(diag, dict):
                continue
            if (
                diag.get("comparison") == comparison
                and diag.get("metric") == metric
                and diag.get("scope", "overall") == scope
            ):
                return diag
        return None

    def _paired_blockers(comparison: str, metrics: list[str], scope: str = "overall") -> list[str]:
        blockers: list[str] = []
        for metric in metrics:
            diag = _comparison_diag(comparison, metric, scope=scope)
            if diag is None:
                blockers.append(f"paired comparison diagnostic missing for {comparison}/{metric}/{scope}")
                continue
            if diag.get("significance") != "positive":
                diag_blockers = diag.get("blockers") or []
                reason = "; ".join(str(b) for b in diag_blockers) if diag_blockers else "CI does not clear zero"
                blockers.append(f"{metric} significance={diag.get('significance')} ({reason})")
        return blockers

    def _slice_diag(slice_name: str, variant: str) -> dict[str, Any] | None:
        if not isinstance(slice_confidence, list):
            return None
        for diag in slice_confidence:
            if not isinstance(diag, dict):
                continue
            if diag.get("slice") == slice_name and diag.get("variant") == variant:
                return diag
        return None

    def _slice_metric(slice_name: str, variant: str, metric: str) -> Any:
        if isinstance(slice_metrics, dict):
            by_variant = slice_metrics.get(slice_name, {})
            if isinstance(by_variant, dict):
                row = by_variant.get(variant, {})
                if isinstance(row, dict):
                    return row.get(metric)
        key = f"{slice_name}_{variant.replace('hybrid_union', 'hybrid').replace('title_only', 'title')}_{metric}"
        return config.get(key)

    def _slice_quality_claim(slice_name: str, claim_name: str) -> ClaimStatus:
        if not judgment_gates_pass:
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker=f"Insufficient judgments: judged={judged_query_count}, positive={positive_judged_query_count}",
            )
        diag = _slice_diag(slice_name, "hybrid_union")
        if diag is None:
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker=f"{slice_name} slice confidence diagnostic missing",
            )
        if diag.get("confidence") == "low" or diag.get("blockers"):
            blockers = diag.get("blockers") or ["low slice confidence"]
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker=f"{slice_name} slice evidence is sparse: " + "; ".join(str(b) for b in blockers),
            )
        hybrid_ndcg = _slice_metric(slice_name, "hybrid_union", "ndcg_at_10")
        title_ndcg = _slice_metric(slice_name, "title_only", "ndcg_at_10")
        if not isinstance(hybrid_ndcg, (int, float)) or not isinstance(title_ndcg, (int, float)):
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker=f"{slice_name} slice NDCG@10 metrics are null",
            )
        if hybrid_ndcg > title_ndcg:
            blockers = _paired_blockers(
                "hybrid_union_vs_title_only",
                ["ndcg_at_10"],
                scope=f"slice:{slice_name}",
            )
            if blockers:
                return ClaimStatus(
                    claim=claim_name,
                    status="needs_more_evidence",
                    blocker="slice paired comparison evidence not supportive: " + "; ".join(blockers),
                )
            return ClaimStatus(
                claim=claim_name,
                status="supported",
                evidence=f"hybrid {slice_name} NDCG@10={hybrid_ndcg} > title={title_ndcg}; slice paired CI evidence positive",
            )
        return ClaimStatus(
            claim=claim_name,
            status="unsupported",
            evidence=f"hybrid {slice_name} NDCG@10={hybrid_ndcg}, title={title_ndcg}",
        )

    # Judgment coverage gates
    judged_query_count = config.get("judged_query_count", 0)
    positive_judged_query_count = config.get("positive_judged_query_count", 0)
    judgment_gates_pass = (
        judged_query_count >= 30 and
        positive_judged_query_count >= 20
    )

    # Claim 1: Hybrid beats title baseline
    if "title_only" in failed_variants or title is None:
        claims.append(ClaimStatus(
            claim="Hybrid beats title baseline",
            status="needs_more_evidence",
            blocker="title_only variant is unavailable",
        ))
    elif not judgment_gates_pass:
        claims.append(ClaimStatus(
            claim="Hybrid beats title baseline",
            status="needs_more_evidence",
            blocker=f"Insufficient judgments: judged={judged_query_count}, positive={positive_judged_query_count}",
        ))
    elif hybrid and title:
        hybrid_ndcg = hybrid.get("ndcg_at_10")
        hybrid_recall = hybrid.get("recall_at_10")
        hybrid_mrr = hybrid.get("mrr_at_10")
        title_ndcg = title.get("ndcg_at_10")
        title_recall = title.get("recall_at_10")
        title_mrr = title.get("mrr_at_10")
        all_metrics = [hybrid_ndcg, hybrid_recall, hybrid_mrr, title_ndcg, title_recall, title_mrr]
        if any(m is None for m in all_metrics):
            claims.append(ClaimStatus(
                claim="Hybrid beats title baseline",
                status="needs_more_evidence",
                blocker="Some comparison metrics are null",
            ))
        elif hybrid_ndcg > title_ndcg and hybrid_recall > title_recall and hybrid_mrr > title_mrr:
            blockers = _paired_blockers("hybrid_union_vs_title_only", ["ndcg_at_10", "recall_at_10", "mrr_at_10"])
            if blockers:
                claims.append(ClaimStatus(
                    claim="Hybrid beats title baseline",
                    status="needs_more_evidence",
                    blocker="paired comparison evidence not supportive: " + "; ".join(blockers),
                ))
            else:
                claims.append(ClaimStatus(
                    claim="Hybrid beats title baseline",
                    status="supported",
                    evidence=f"hybrid NDCG@10={hybrid_ndcg} > title={title_ndcg}, "
                             f"Recall@10={hybrid_recall} > {title_recall}, "
                             f"MRR@10={hybrid_mrr} > {title_mrr}; paired CI evidence positive",
                ))
        else:
            claims.append(ClaimStatus(
                claim="Hybrid beats title baseline",
                status="unsupported",
                evidence=f"hybrid NDCG@10={hybrid_ndcg}, title={title_ndcg}; "
                         f"Recall@10: {hybrid_recall} vs {title_recall}; "
                         f"MRR@10: {hybrid_mrr} vs {title_mrr}",
            ))

    # Claim 2: Hybrid beats single-channel baselines
    if not judgment_gates_pass:
        claims.append(ClaimStatus(
            claim="Hybrid beats single-channel baselines",
            status="needs_more_evidence",
            blocker=f"Insufficient judgments: judged={judged_query_count}, positive={positive_judged_query_count}",
        ))
    elif hybrid and vector and bm25:
        h_n = hybrid.get("ndcg_at_10")
        v_n = vector.get("ndcg_at_10")
        b_n = bm25.get("ndcg_at_10")
        if all(x is not None for x in [h_n, v_n, b_n]):
            if h_n > v_n and h_n > b_n:
                blockers = (
                    _paired_blockers("hybrid_union_vs_vector_only", ["ndcg_at_10"]) +
                    _paired_blockers("hybrid_union_vs_bm25_only", ["ndcg_at_10"])
                )
                if blockers:
                    claims.append(ClaimStatus(
                        claim="Hybrid beats single-channel baselines",
                        status="needs_more_evidence",
                        blocker="paired comparison evidence not supportive: " + "; ".join(blockers),
                    ))
                else:
                    claims.append(ClaimStatus(
                        claim="Hybrid beats single-channel baselines",
                        status="supported",
                        evidence=f"hybrid={h_n} > vector={v_n}, bm25={b_n}; paired NDCG@10 CI evidence positive",
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
    dataset_cold_dominant = config.get("dataset_is_cold_dominant", False)
    if not judgment_gates_pass:
        claims.append(ClaimStatus(
            claim="Cold-start exposure quality" if dataset_cold_dominant else "Cold-start retrieval is useful",
            status="needs_more_evidence",
            blocker=f"Insufficient judgments: judged={judged_query_count}, positive={positive_judged_query_count}",
        ))
    elif hybrid:
        cold_rate = hybrid.get("cold_relevant_rate_at_10")
        claim_name = "Cold-start exposure quality" if dataset_cold_dominant else "Cold-start retrieval is useful"
        if cold_rate is not None and cold_rate > 0:
            evidence_suffix = (
                ", but dataset is cold-dominant — cannot prove cold vs warm lift"
                if dataset_cold_dominant else ""
            )
            claims.append(ClaimStatus(
                claim=claim_name,
                status="supported",
                evidence=f"ColdRelevantRate@10={cold_rate}{evidence_suffix}",
            ))
        elif cold_rate == 0:
            claims.append(ClaimStatus(
                claim=claim_name,
                status="unsupported",
                evidence="ColdRelevantRate@10=0",
            ))
        else:
            claims.append(ClaimStatus(
                claim=claim_name,
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
    vi_judged = config.get("vietnamese_judged_query_count", 0)
    vi_hybrid_ndcg = config.get("vietnamese_hybrid_ndcg_at_10")
    vi_title_ndcg = config.get("vietnamese_title_ndcg_at_10")
    if not judgment_gates_pass or vi_judged < 5:
        claims.append(ClaimStatus(
            claim="Vietnamese robustness",
            status="needs_more_evidence",
            blocker=f"Vietnamese slice has only {vi_judged} judged queries (need >= 5) "
                    f"or overall judgment gates not met",
        ))
    elif (vi_diag := _slice_diag("vietnamese", "hybrid_union")) is None:
        claims.append(ClaimStatus(
            claim="Vietnamese robustness",
            status="needs_more_evidence",
            blocker="Vietnamese slice confidence diagnostic missing",
        ))
    elif vi_diag.get("confidence") == "low" or vi_diag.get("blockers"):
        blockers = vi_diag.get("blockers") or ["low slice confidence"]
        claims.append(ClaimStatus(
            claim="Vietnamese robustness",
            status="needs_more_evidence",
            blocker="Vietnamese slice evidence is sparse: " + "; ".join(str(b) for b in blockers),
        ))
    elif not isinstance(vi_hybrid_ndcg, (int, float)) or not isinstance(vi_title_ndcg, (int, float)):
        claims.append(ClaimStatus(
            claim="Vietnamese robustness",
            status="needs_more_evidence",
            blocker="Vietnamese slice NDCG@10 metrics are null",
        ))
    elif vi_hybrid_ndcg > vi_title_ndcg:
        blockers = _paired_blockers(
            "hybrid_union_vs_title_only",
            ["ndcg_at_10"],
            scope="slice:vietnamese",
        )
        if blockers:
            claims.append(ClaimStatus(
                claim="Vietnamese robustness",
                status="needs_more_evidence",
                blocker="slice paired comparison evidence not supportive: " + "; ".join(blockers),
            ))
        else:
            claims.append(ClaimStatus(
                claim="Vietnamese robustness",
                status="supported",
                evidence=f"hybrid Vietnamese NDCG@10={vi_hybrid_ndcg} > title={vi_title_ndcg}; slice paired CI evidence positive",
            ))
    else:
        claims.append(ClaimStatus(
            claim="Vietnamese robustness",
            status="unsupported",
            evidence=f"hybrid Vietnamese NDCG@10={vi_hybrid_ndcg}, title={vi_title_ndcg}",
        ))

    claims.append(_slice_quality_claim("price_filter", "Price-filter retrieval quality"))
    claims.append(_slice_quality_claim("compatibility", "Compatibility retrieval quality"))

    # Claim 8: live latency evidence, split by measured scope.
    use_cached = config.get("use_cached_fixtures", True)
    mongodb_live = config.get("mongodb_live")
    model_download = config.get("model_download_observed", False)
    latency_sample_count = config.get("latency_sample_count", 0)
    latency_summary = config.get("latency_summary", {})
    search_summary = latency_summary.get("search_latency_ms", {}) if isinstance(latency_summary, dict) else {}
    total_summary = latency_summary.get("total_latency_ms", {}) if isinstance(latency_summary, dict) else {}

    def _latency_claim(claim_name: str, label: str, summary: dict[str, Any]) -> ClaimStatus:
        sample_count = int(summary.get("sample_count", latency_sample_count) or 0)
        if use_cached or not mongodb_live:
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker="Cached fixtures used or MongoDB not live" if use_cached else "MongoDB not confirmed live",
            )
        if model_download:
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker="Model download observed - latency is cold runtime, not normal serving",
            )
        if sample_count < 20:
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker=f"{label} latency sample count {sample_count} < 20",
            )
        if summary.get("p95") is None or summary.get("p50") is None:
            return ClaimStatus(
                claim=claim_name,
                status="needs_more_evidence",
                blocker=f"{label} latency percentile summary missing",
            )
        return ClaimStatus(
            claim=claim_name,
            status="supported",
            evidence=(
                f"Live MongoDB with fresh fixtures; {label} P50={summary.get('p50')}ms, "
                f"{label} P95={summary.get('p95')}ms, samples={sample_count}"
            ),
        )

    claims.append(_latency_claim("Live search latency evidence", "search", search_summary))
    claims.append(_latency_claim("Live total path latency evidence", "total path", total_summary))

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
    coverage_stats = run_data.get("coverage_stats", config)
    cold_warm_ratio = run_data.get("cold_warm_ratio", config.get("cold_warm_ratio", {}))
    variant_comparisons = run_data.get("variant_comparisons", config.get("variant_comparisons", []))
    slice_variant_comparisons = run_data.get("slice_variant_comparisons", config.get("slice_variant_comparisons", []))
    slice_confidence = run_data.get("slice_confidence", config.get("slice_confidence", []))
    slice_metrics = run_data.get("slice_metrics", config.get("slice_metrics", {}))
    judgment_audit = run_data.get("judgment_audit", config.get("judgment_audit", {}))
    latency_summary = run_data.get("latency_summary", config.get("latency_summary", {}))

    lines: list[str] = []
    lines.append("# Evaluation Report")
    lines.append("")
    lines.append(f"**Run ID:** {config.get('run_id', 'unknown')}")
    lines.append(f"**Created at:** {config.get('created_at', 'unknown')}")
    lines.append(f"**K values:** {config.get('k_values', [])}")
    lines.append(f"**Relevance threshold:** {config.get('relevance_threshold', 2)}")
    lines.append(f"**Git commit:** {config.get('git_commit', 'N/A')}")
    lines.append(f"**Python version:** {config.get('python_version', 'N/A')}")
    lines.append(f"**Platform:** {config.get('platform', 'N/A')}")
    lines.append("")

    # Report status banner
    report_status = coverage_stats.get("report_status", config.get("report_status", "unknown"))
    if report_status == "insufficient_judgments":
        lines.append("> ⚠️ **PRELIMINARY RESULTS**: Insufficient relevance judgments "
                     f"(judged={coverage_stats.get('judged_query_count', 0)}, need ≥30). "
                     "All metrics below are directional only.")
        lines.append("")
    elif report_status == "insufficient_positive_judgments":
        lines.append("> ⚠️ **PRELIMINARY RESULTS**: Insufficient positive judgments "
                     f"(positive={coverage_stats.get('positive_judged_query_count', 0)}, need ≥20). "
                     "Retrieval quality claims cannot be made.")
        lines.append("")

    # Judgment Coverage
    lines.append("## Judgment Coverage")
    lines.append("")
    jqc = coverage_stats.get("judged_query_count", 0)
    pjqc = coverage_stats.get("positive_judged_query_count", 0)
    tqc = coverage_stats.get("total_query_count", 0)
    qjcr = coverage_stats.get("query_judgment_coverage_rate", 0)
    rjcr = coverage_stats.get("result_judgment_coverage_rate", 0)
    lines.append("| Metric | Value | Gate | Status |")
    lines.append("|--------|-------|------|--------|")
    lines.append(f"| Total queries | {tqc} | — | — |")
    lines.append(f"| Judged queries | {jqc} | ≥ 30 | {'✅' if jqc >= 30 else '❌'} |")
    lines.append(f"| Positive judged queries | {pjqc} | ≥ 20 | {'✅' if pjqc >= 20 else '❌'} |")
    lines.append(f"| Query coverage rate | {qjcr:.1%} | ≥ 50% | {'✅' if qjcr >= 0.5 else '❌'} |")
    lines.append(f"| Result coverage rate | {rjcr:.1%} | — | — |")
    lines.append(f"| Report status | **{report_status}** | — | — |")
    lines.append("")

    if isinstance(judgment_audit, dict) and judgment_audit:
        lines.append("## Judgment Provenance")
        lines.append("")
        lines.append(f"- **Overall audit status:** `{judgment_audit.get('overall_status', 'unknown')}`")
        lines.append(f"- **Human-audited rate:** `{judgment_audit.get('human_audited_rate', 0)}`")
        source_counts = judgment_audit.get("source_counts", {})
        if isinstance(source_counts, dict) and source_counts:
            lines.append("")
            lines.append("| Source | Count |")
            lines.append("|---|---|")
            for source, count in sorted(source_counts.items()):
                lines.append(f"| {source} | {count} |")
        slice_audit = judgment_audit.get("slice_audit", [])
        if isinstance(slice_audit, list) and slice_audit:
            lines.append("")
            lines.append("| Slice | Queries | Judged | Human-audited queries | Audit status | Demo readiness | Blockers |")
            lines.append("|---|---|---|---|---|---|---|")
            for row in slice_audit:
                blockers = row.get("blockers") or []
                blocker_text = "; ".join(str(blocker) for blocker in blockers) if blockers else "-"
                lines.append(
                    f"| {row.get('slice', '')} | {row.get('query_count', 0)} | "
                    f"{row.get('judged_query_count', 0)} | {row.get('human_audited_query_count', 0)} | "
                    f"{row.get('audit_status', '')} | {row.get('demo_readiness', '')} | {blocker_text} |"
                )
        lines.append("")

    # Cold/Warm Distribution
    if cold_warm_ratio:
        lines.append("## Cold/Warm Distribution")
        lines.append("")
        cold_items = cold_warm_ratio.get("cold_items", 0)
        warm_items = cold_warm_ratio.get("warm_items", 0)
        unknown_items = cold_warm_ratio.get("unknown_items", 0)
        cold_pct = cold_warm_ratio.get("cold_percentage", 0)
        is_cold_dominant = cold_warm_ratio.get("dataset_is_cold_dominant", False)
        lines.append(f"- **Cold items:** {cold_items}")
        lines.append(f"- **Warm items:** {warm_items}")
        lines.append(f"- **Unknown status:** {unknown_items}")
        lines.append(f"- **Cold percentage:** {cold_pct}%")
        if is_cold_dominant:
            lines.append("")
            lines.append("> ⚠️ **Dataset is cold-dominant** — Cold-start metrics measure exposure quality, "
                         "not cold vs warm lift. Insufficient warm items for comparison.")
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
    headers = "| variant | query_count | metric_confidence | NDCG@10 | Recall@10 | MRR@10 | Precision@5 | HitRate@10 | ColdRelevantRate@10 | empty_results | failures |"
    lines.append(headers)
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for vs in variant_summaries:
        v = vs.get("variant", "")
        qc = vs.get("query_count", 0)
        metric_confidence = vs.get("metric_confidence")
        if not metric_confidence:
            judged_for_variant = vs.get("judged_query_count", jqc)
            if isinstance(judged_for_variant, int) and judged_for_variant >= 30:
                metric_confidence = "high"
            elif isinstance(judged_for_variant, int) and judged_for_variant >= 15:
                metric_confidence = "medium"
            else:
                metric_confidence = "low"
        ndcg = vs.get("ndcg_at_10", "N/A")
        recall = vs.get("recall_at_10", "N/A")
        mrr = vs.get("mrr_at_10", "N/A")
        prec = vs.get("precision_at_5", "N/A")
        hr = vs.get("hit_rate_at_10", "N/A")
        cold = vs.get("cold_relevant_rate_at_10", "N/A")
        # Count empty results and failures per variant
        empty_count = sum(1 for l in latency if l.get("variant") == v and l.get("result_status") == "ok_empty")
        fail_count = sum(1 for f in failures if f.get("variant") == v)
        lines.append(f"| {v} | {qc} | {metric_confidence} | {ndcg} | {recall} | {mrr} | {prec} | {hr} | {cold} | {empty_count} | {fail_count} |")
    lines.append("")

    # Ablation Impact Table
    _add_ablation_impact(lines, variant_summaries, variant_comparisons)

    # Slice Analysis
    slice_summaries = run_data.get("slice_summaries", [])
    if slice_summaries:
        _add_slice_analysis(lines, slice_summaries, jqc, slice_confidence)

    # Claim Status
    claim_config = dict(config)
    claim_config.setdefault("variant_comparisons", variant_comparisons)
    claim_config.setdefault("slice_variant_comparisons", slice_variant_comparisons)
    claim_config.setdefault("slice_confidence", slice_confidence)
    claim_config.setdefault("slice_metrics", slice_metrics)
    claim_config.setdefault("latency_summary", latency_summary)
    claims = decide_claim_status(variant_summaries, claim_config, failures)
    lines.append("## Claim Status")
    lines.append("")
    lines.append("| claim | status | evidence | blocker |")
    lines.append("|---|---|---|---|")
    for c in claims:
        status_emoji = {"supported": "✅", "unsupported": "❌", "needs_more_evidence": "⚠️"}.get(c.status, "")
        lines.append(f"| {c.claim} | {status_emoji} {c.status} | {c.evidence} | {c.blocker} |")
    lines.append("")

    supported_claims = [claim for claim in claims if claim.status == "supported"]
    blocked_claims = [claim for claim in claims if claim.status != "supported"]

    lines.append("## What We Can Claim")
    lines.append("")
    if supported_claims:
        for claim in supported_claims:
            lines.append(f"- **{claim.claim}:** {claim.evidence}")
    else:
        lines.append("- No supported claims yet. Treat all metrics as directional.")
    lines.append("")

    lines.append("## What We Cannot Claim Yet")
    lines.append("")
    if blocked_claims:
        for claim in blocked_claims:
            reason = claim.blocker or claim.evidence or "No supporting evidence."
            lines.append(f"- **{claim.claim}:** {claim.status}; {reason}")
    else:
        lines.append("- No blocked claims in this run.")
    lines.append("")

    lines.append("## Claim Blockers")
    lines.append("")
    blockers = [claim for claim in claims if claim.blocker]
    if blockers:
        lines.append("| claim | blocker |")
        lines.append("|---|---|")
        for claim in blockers:
            lines.append(f"| {claim.claim} | {claim.blocker} |")
    else:
        lines.append("- No explicit claim blockers.")
    lines.append("")

    # Failure Dashboard
    _add_failure_dashboard(lines, failures)

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
            lines.append("- Search latency is not total path latency.")
            if total_latencies:
                t_p50 = total_latencies[len(total_latencies) // 2]
                t_p95 = total_latencies[min(int(len(total_latencies) * 0.95), len(total_latencies) - 1)]
                lines.append(f"- **P50 total latency:** {t_p50:.1f}ms")
                lines.append(f"- **P95 total latency:** {t_p95:.1f}ms")
                lines.append("- Total path latency includes query processing plus search.")
            confidence = "high" if len(search_latencies) >= 50 else ("medium" if len(search_latencies) >= 20 else "low")
            lines.append(f"- **Latency confidence:** {confidence}")
            if confidence == "low":
                lines.append("  - ⚠️ P95 latency is directional only (sample < 20)")
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

    # Explanation Coverage
    _add_explanation_coverage(lines, run_data.get("results", []))

    # Commands Run / Not Run
    lines.append("## Commands")
    lines.append("")
    run_id = config.get("run_id", "unknown")
    out_dir = config.get("output_dir", f".runtime/evaluation/{run_id}")
    queries_path = config.get("queries_path", "evaluation/queries/retrieval_queries_seed.json")
    judgments_path = config.get("judgments_path", "evaluation/judgments/retrieval_judgments_seed.json")

    lines.append("### Commands Run")
    lines.append("")
    lines.append("```bash")
    lines.append(f"python scripts/run_evaluation.py \\")
    lines.append(f"  --queries {queries_path} \\")
    lines.append(f"  --judgments {judgments_path} \\")
    lines.append(f"  --out {out_dir}")
    lines.append("```")
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


def _add_ablation_impact(
    lines: list[str],
    variant_summaries: list[dict[str, object]],
    variant_comparisons: list[dict[str, object]] | None = None,
) -> None:
    """Add ablation impact comparison table."""

    def _get(name: str) -> dict[str, object] | None:
        return next((s for s in variant_summaries if s.get("variant") == name), None)

    hybrid = _get("hybrid_union")
    title = _get("title_only")
    vector = _get("vector_only")
    bm25 = _get("bm25_only")
    no_cold = _get("hybrid_no_cold_boost")

    comparisons = []
    if hybrid and title:
        comparisons.append(("hybrid vs title_only", hybrid, title))
    if hybrid and vector:
        comparisons.append(("hybrid vs vector_only", hybrid, vector))
    if hybrid and bm25:
        comparisons.append(("hybrid vs bm25_only", hybrid, bm25))
    if hybrid and no_cold:
        comparisons.append(("hybrid vs no_cold_boost", hybrid, no_cold))

    if not comparisons:
        return

    lines.append("## Ablation Impact")
    lines.append("")
    lines.append("| comparison | delta_NDCG@10 | delta_MRR@10 | delta_ColdRelevantRate@10 | paired evidence | interpretation |")
    lines.append("|---|---|---|---|---|---|")
    comparison_keys = {
        "hybrid vs title_only": "hybrid_union_vs_title_only",
        "hybrid vs vector_only": "hybrid_union_vs_vector_only",
        "hybrid vs bm25_only": "hybrid_union_vs_bm25_only",
        "hybrid vs no_cold_boost": "hybrid_union_vs_hybrid_no_cold_boost",
    }
    for label, a, b in comparisons:
        comparison_key = comparison_keys.get(label, label.replace("hybrid vs ", "hybrid_union_vs_"))

        def _evidence(metric: str) -> str:
            for diag in variant_comparisons or []:
                if diag.get("comparison") == comparison_key and diag.get("metric") == metric:
                    status = str(diag.get("significance", "unknown"))
                    blockers = diag.get("blockers") or []
                    if blockers:
                        return f"{status}: {'; '.join(str(b) for b in blockers)}"
                    return status
            return "missing paired comparison"

        def _delta(key: str) -> str:
            av = a.get(key)
            bv = b.get(key)
            if av is not None and bv is not None and isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                d = round(av - bv, 4)
                sign = "+" if d > 0 else ""
                return f"{sign}{d}"
            return "N/A"

        d_ndcg = _delta("ndcg_at_10")
        d_mrr = _delta("mrr_at_10")
        d_cold = _delta("cold_relevant_rate_at_10")
        evidence = _evidence("ndcg_at_10")
        interp = "—"
        if d_ndcg != "N/A":
            val = float(d_ndcg)
            if not evidence.startswith("positive"):
                interp = "Directional only; do not treat as supported"
            elif val > 0.05:
                interp = "Clear improvement ✅"
            elif val > 0:
                interp = "Slight improvement"
            elif val > -0.05:
                interp = "Negligible difference"
            else:
                interp = "Regression ❌"
        lines.append(f"| {label} | {d_ndcg} | {d_mrr} | {d_cold} | {evidence} | {interp} |")
    lines.append("")


def _add_slice_analysis(
    lines: list[str],
    slice_summaries: list[dict[str, object]],
    judged_count: int,
    slice_confidence: list[dict[str, object]] | None = None,
) -> None:
    """Add slice analysis with language and intent sub-tables."""
    lines.append("## Slice Analysis")
    lines.append("")

    # Group by slice
    slices_by_name: dict[str, list[dict[str, object]]] = {}
    for s in slice_summaries:
        slice_name = str(s.get("slice", ""))
        if slice_name:
            slices_by_name.setdefault(slice_name, []).append(s)

    language_slices = ["english", "vietnamese", "vietnamese_no_diacritic"]
    intent_slices = ["price_filter", "compatibility", "gift", "persona", "occasion", "problem", "constraint"]

    # Language slices
    lang_entries = {k: v for k, v in slices_by_name.items() if k in language_slices}
    if lang_entries:
        lines.append("### Language Slices")
        lines.append("")
        lines.append("| Slice | Queries | Judged | Confidence | Hybrid NDCG@10 | Title NDCG@10 | Delta |")
        lines.append("|-------|---------|--------|------------|----------------|---------------|-------|")
        for sl in language_slices:
            if sl not in lang_entries:
                continue
            entries = lang_entries[sl]
            hybrid_entry = next((e for e in entries if e.get("variant") == "hybrid_union"), None)
            title_entry = next((e for e in entries if e.get("variant") == "title_only"), None)
            if hybrid_entry:
                qc = hybrid_entry.get("query_count", 0)
                judged = hybrid_entry.get("judged_query_count", 0)
                conf = "high" if judged >= 15 else ("medium" if judged >= 5 else "low")
                h_ndcg = hybrid_entry.get("ndcg_at_10", "N/A")
                t_ndcg = title_entry.get("ndcg_at_10", "N/A") if title_entry else "N/A"
                delta = "N/A"
                if isinstance(h_ndcg, (int, float)) and isinstance(t_ndcg, (int, float)):
                    d = round(h_ndcg - t_ndcg, 4)
                    delta = f"+{d}" if d > 0 else str(d)
                conf_mark = "⚠️" if conf == "low" else ""
                lines.append(f"| {sl} | {qc} | {judged} | {conf} {conf_mark} | {h_ndcg} | {t_ndcg} | {delta} |")
        lines.append("")

    # Intent slices
    intent_entries = {k: v for k, v in slices_by_name.items() if k in intent_slices}
    if intent_entries:
        lines.append("### Intent Slices")
        lines.append("")
        lines.append("| Slice | Queries | Judged | Confidence | Hybrid NDCG@10 | Best Variant |")
        lines.append("|-------|---------|--------|------------|----------------|--------------|")
        for sl in intent_slices:
            if sl not in intent_entries:
                continue
            entries = intent_entries[sl]
            hybrid_entry = next((e for e in entries if e.get("variant") == "hybrid_union"), None)
            if hybrid_entry:
                qc = hybrid_entry.get("query_count", 0)
                judged = hybrid_entry.get("judged_query_count", 0)
                conf = "high" if judged >= 15 else ("medium" if judged >= 5 else "low")
                h_ndcg = hybrid_entry.get("ndcg_at_10", "N/A")
                # Find best variant for this slice
                best_var = "N/A"
                best_ndcg = -1.0
                for e in entries:
                    v_ndcg = e.get("ndcg_at_10")
                    if v_ndcg is not None and isinstance(v_ndcg, (int, float)) and v_ndcg > best_ndcg:
                        best_ndcg = v_ndcg
                        best_var = str(e.get("variant", ""))
                conf_mark = "⚠️" if conf == "low" else ""
                lines.append(f"| {sl} | {qc} | {judged} | {conf} {conf_mark} | {h_ndcg} | {best_var} |")
        lines.append("")

    if slice_confidence:
        lines.append("### Slice Confidence Diagnostics")
        lines.append("")
        lines.append("| Slice | Variant | Confidence | Judged | Positive Judged | Result Coverage | Blockers |")
        lines.append("|-------|---------|------------|--------|-----------------|-----------------|----------|")
        for diag in slice_confidence:
            blockers = diag.get("blockers") or []
            blocker_text = "; ".join(str(b) for b in blockers) if blockers else "-"
            lines.append(
                f"| {diag.get('slice', '')} | {diag.get('variant', '')} | {diag.get('confidence', '')} | "
                f"{diag.get('judged_query_count', 0)} | {diag.get('positive_judged_query_count', 0)} | "
                f"{diag.get('result_judgment_coverage_rate', 0)} | {blocker_text} |"
            )
        lines.append("")


def _add_failure_dashboard(lines: list[str], failures: list[dict[str, Any]]) -> None:
    """Generate detailed failure dashboard."""
    if not failures:
        lines.append("## Failure Dashboard")
        lines.append("")
        lines.append("✅ No failures recorded.")
        lines.append("")
        return

    lines.append("## Failure Dashboard")
    lines.append("")

    # Failure matrix: group by (variant, error_type)
    failure_matrix: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for f in failures:
        variant = f.get("variant", "unknown")
        error_type = f.get("error_type", "unknown")
        key = (variant, error_type)
        failure_matrix.setdefault(key, []).append(f)

    lines.append("| Variant | Error Type | Count | Affected Queries | Next File | Next Function |")
    lines.append("|---------|-----------|-------|------------------|-----------|---------------|")

    for (variant, error_type), fails in sorted(failure_matrix.items()):
        affected = ", ".join(sorted(set(f.get("query_id", "?") for f in fails if f.get("query_id"))))[:60]
        next_file = fails[0].get("next_file_to_inspect", "—")
        next_func = fails[0].get("next_function_to_inspect", "—")
        lines.append(f"| {variant} | {error_type} | {len(fails)} | {affected} | {next_file} | {next_func} |")
    lines.append("")

    # Top failure details
    if len(failures) > 0:
        lines.append("### Top Failure Details")
        lines.append("")
        for f in failures[:10]:
            lines.append(f"- **{f.get('variant', '?')}/{f.get('query_id', '?')}**: "
                         f"`{f.get('error_type', '?')}` — {f.get('error', 'unknown error')}")
            details = f.get("details") or {}
            if isinstance(details, dict):
                for key, value in details.items():
                    lines.append(f"  - {key}: {value}")
        lines.append("")


def _add_explanation_coverage(lines: list[str], results: list[dict[str, Any]]) -> None:
    """Add explanation readiness check section."""
    if not results:
        return

    stats = check_explanation_quality(results)
    total = stats["total_results"]
    has_intent = stats["has_matched_intent"]
    has_fact = stats["has_matched_fact"]
    has_both = stats["has_both_explanations"]
    full_coverage = stats["full_explanation_coverage"]
    both_missing_rate = stats.get("both_missing_rate")
    quality = stats.get("explanation_quality")

    lines.append("## Explanation Coverage")
    lines.append("")
    lines.append(f"- **Total results:** {total}")
    lines.append(f"- **Has matched_intent:** {has_intent} ({round(has_intent / total * 100, 1) if total else 0}%)")
    lines.append(f"- **Has matched_fact:** {has_fact} ({round(has_fact / total * 100, 1) if total else 0}%)")
    lines.append(f"- **Has both explanations:** {has_both} ({round(has_both / total * 100, 1) if total else 0}%)")
    lines.append(f"- **Has neither explanation:** {stats.get('has_no_explanation')} ({round(float(both_missing_rate) * 100, 1) if isinstance(both_missing_rate, (int, float)) else 0}%)")
    lines.append(f"- **Explanation quality:** {quality}")
    if full_coverage is not None and full_coverage < 0.5:
        lines.append("")
        lines.append("> ⚠️ Less than 50% of results have full explanations (both matched_intent and matched_fact). "
                     "This may affect demo readiness.")
    lines.append("")


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


def generate_judge_facing_executive_summary_md(run_data: dict[str, Any]) -> str:
    """Generate a short judge-facing summary with explicit claim boundaries."""
    config = run_data.get("config", {})
    variant_summaries = run_data.get("variant_summaries", [])
    failures = run_data.get("failures", [])
    claim_config = dict(config)
    claim_config.setdefault("variant_comparisons", run_data.get("variant_comparisons", []))
    claim_config.setdefault("slice_variant_comparisons", run_data.get("slice_variant_comparisons", []))
    claim_config.setdefault("slice_confidence", run_data.get("slice_confidence", []))
    claim_config.setdefault("slice_metrics", run_data.get("slice_metrics", {}))
    claim_config.setdefault("latency_summary", run_data.get("latency_summary", {}))
    claims = decide_claim_status(variant_summaries, claim_config, failures)
    supported = [claim for claim in claims if claim.status == "supported"]
    blocked = [claim for claim in claims if claim.status != "supported"]
    judgment_audit = run_data.get("judgment_audit", config.get("judgment_audit", {}))

    lines = [
        "# Judge-Facing Executive Summary",
        "",
        f"**Run ID:** {config.get('run_id', 'unknown')}",
        f"**Evaluation schema:** {config.get('evaluation_schema_version', 'unknown')}",
        f"**Artifact contract:** {config.get('artifact_contract_version', '1.0')}",
        "",
        "## What We Can Claim",
        "",
    ]
    if supported:
        for claim in supported:
            lines.append(f"- **{claim.claim}:** {claim.evidence}")
    else:
        lines.append("- No supported claims yet. Use metrics as directional evidence only.")

    lines.extend(["", "## What We Cannot Claim Yet", ""])
    if blocked:
        for claim in blocked:
            reason = claim.blocker or claim.evidence or "No supporting evidence."
            lines.append(f"- **{claim.claim}:** {claim.status}; {reason}")
    else:
        lines.append("- No blocked claims in this run.")

    lines.extend([
        "",
        "## Evidence Caveats",
        "",
        "- Claim states are deterministic: supported, unsupported, or needs_more_evidence.",
        "- Search latency and total path latency are separate evidence scopes.",
        "- Slice claims require slice coverage plus paired evidence, not raw metric deltas alone.",
    ])
    if isinstance(judgment_audit, dict) and judgment_audit:
        lines.append(
            f"- Judgment provenance status: `{judgment_audit.get('overall_status', 'unknown')}`; "
            f"human-audited rate `{judgment_audit.get('human_audited_rate', 0)}`."
        )

    lines.extend([
        "",
        "## Report Pack Files",
        "",
        "- metrics_summary.md",
        "- hackathon_impact_report.md",
        "- evaluation_upgrade_report_vi.md (optional static attachment copied from repo root if available)",
        "- judge_facing_executive_summary.md",
    ])
    return "\n".join(lines) + "\n"


def write_judge_report_pack(run_data: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    """Write additive judge-facing report pack files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "judge_facing_executive_summary.md"
    manifest_path = out / "judge_report_pack_manifest.json"
    vietnamese_report_path = out / "evaluation_upgrade_report_vi.md"
    summary_path.write_text(generate_judge_facing_executive_summary_md(run_data), encoding="utf-8")
    source_vietnamese_report = Path(__file__).resolve().parents[2] / "evaluation_upgrade_report_vi.md"
    missing_required_files: list[str] = []
    missing_optional_static_files: list[str] = []
    files_written = {
        "executive_summary": str(summary_path),
        "manifest": str(manifest_path),
    }
    if source_vietnamese_report.exists():
        copyfile(source_vietnamese_report, vietnamese_report_path)
        files_written["evaluation_upgrade_report_vi"] = str(vietnamese_report_path)
    else:
        missing_optional_static_files.append("evaluation_upgrade_report_vi.md")
    manifest = {
        "run_id": run_data.get("config", {}).get("run_id", "unknown"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "artifact_contract_version": run_data.get("config", {}).get("artifact_contract_version", "1.0"),
        "expected_pack_files": [
            "metrics_summary.md",
            "hackathon_impact_report.md",
            "judge_facing_executive_summary.md",
        ],
        "optional_static_pack_files": [
            "evaluation_upgrade_report_vi.md",
        ],
        "files_written": files_written,
        "missing_required_files": missing_required_files,
        "missing_optional_static_files": missing_optional_static_files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return files_written


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
