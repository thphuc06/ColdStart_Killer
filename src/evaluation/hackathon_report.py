"""Generate a hackathon-focused impact report.

This report translates raw metrics into business stories
and highlights what matters most for hackathon judges.

Import safety: no side effects at import time.
"""

from __future__ import annotations

from typing import Any


def generate_hackathon_report(run_data: dict[str, Any]) -> str:
    """Generate hackathon impact report markdown."""
    sections: list[str] = []

    # 1. Executive Summary
    sections.append(_executive_summary(run_data))

    # 2. Head-to-head comparisons
    sections.append(_comparison_hybrid_vs_title(run_data))
    sections.append(_comparison_hybrid_vs_single_channel(run_data))

    # 3. Vietnamese query quality
    sections.append(_vietnamese_quality(run_data))

    # 4. Price-filter query quality
    sections.append(_price_filter_quality(run_data))

    # 5. Cold-start exposure
    sections.append(_cold_start_exposure(run_data))

    # 6. Latency profile
    sections.append(_latency_profile(run_data))

    # 7. Qualitative examples (wow factor)
    sections.append(_qualitative_examples(run_data))

    # 8. Business story summary
    sections.append(_business_story(run_data))

    return "\n\n---\n\n".join(s for s in sections if s)


def _get_variant_summary(run_data: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Find a variant summary by name."""
    for s in run_data.get("variant_summaries", []):
        if s.get("variant") == name:
            return s
    return None


def _format_delta(a_val: object, b_val: object) -> tuple[str, str, str]:
    """Format delta and improvement % between two values.

    Returns: (delta_str, pct_str, emoji)
    """
    if a_val is None or b_val is None:
        return "N/A", "N/A", ""
    if not isinstance(a_val, (int, float)) or not isinstance(b_val, (int, float)):
        return "N/A", "N/A", ""
    delta = round(a_val - b_val, 4)
    sign = "+" if delta > 0 else ""
    pct = round((delta / b_val) * 100, 1) if b_val != 0 else float("inf")
    pct_str = f"{sign}{pct}%" if pct != float("inf") else "∞"
    emoji = "✅" if delta > 0 else ("❌" if delta < 0 else "➡️")
    return f"{sign}{delta:.4f}", pct_str, emoji


def _executive_summary(run_data: dict[str, Any]) -> str:
    """Generate the executive summary section."""
    config = run_data.get("config", {})
    coverage = run_data.get("coverage_stats", config)
    hybrid = _get_variant_summary(run_data, "hybrid_union")

    lines = [
        "# 🏆 ColdStart_Killer — Hackathon Impact Report",
        "",
        "## Executive Summary",
        "",
        f"**Run ID:** {config.get('run_id', 'unknown')}",
        f"**Date:** {config.get('created_at', 'unknown')}",
        f"**Queries evaluated:** {coverage.get('total_query_count', 0)}",
        f"**Judgment coverage:** {coverage.get('judged_query_count', 0)} judged "
        f"({coverage.get('query_judgment_coverage_rate', 0):.0%})",
        "",
    ]

    report_status = coverage.get("report_status", "unknown")
    if report_status == "sufficient":
        lines.append("> ✅ **Full evaluation with sufficient judgments.** All metrics and claims are meaningful.")
    else:
        lines.append(f"> ⚠️ **Preliminary evaluation** (status: {report_status}). "
                     "Metrics are directional — add more judgments for official results.")

    if hybrid:
        ndcg = hybrid.get("ndcg_at_10")
        hit_rate = hybrid.get("hit_rate_at_10")
        mrr = hybrid.get("mrr_at_10")
        lines.extend([
            "",
            "### Key Numbers",
            "",
        ])
        if ndcg is not None:
            lines.append(f"- **NDCG@10:** {ndcg:.4f} — ranked results quality")
        if hit_rate is not None:
            lines.append(f"- **HitRate@10:** {hit_rate:.1%} — queries finding relevant results")
        if mrr is not None:
            lines.append(f"- **MRR@10:** {mrr:.4f} — first relevant result ranking")

    return "\n".join(lines)


def _comparison_hybrid_vs_title(run_data: dict[str, Any]) -> str:
    """Generate hybrid vs title_only comparison table."""
    hybrid = _get_variant_summary(run_data, "hybrid_union")
    title = _get_variant_summary(run_data, "title_only")

    if not hybrid or not title:
        return "## Hybrid vs Title-Only\n\n⚠️ Comparison unavailable — missing variant data."

    metrics_to_compare = [
        ("NDCG@10", "ndcg_at_10"),
        ("Recall@10", "recall_at_10"),
        ("MRR@10", "mrr_at_10"),
        ("Precision@5", "precision_at_5"),
        ("HitRate@10", "hit_rate_at_10"),
    ]

    lines = [
        "## Hybrid vs Title-Only Baseline",
        "",
        "> Title-only uses simple keyword regex matching. Hybrid uses semantic vector + BM25 fusion.",
        "",
        "| Metric | Hybrid | Title-Only | Delta | Improvement |",
        "|--------|--------|------------|-------|-------------|",
    ]

    for label, key in metrics_to_compare:
        h_val = hybrid.get(key)
        t_val = title.get(key)
        delta_str, pct_str, emoji = _format_delta(h_val, t_val)
        h_display = f"{h_val:.4f}" if isinstance(h_val, (int, float)) else "N/A"
        t_display = f"{t_val:.4f}" if isinstance(t_val, (int, float)) else "N/A"
        lines.append(f"| {label} | {h_display} | {t_display} | {delta_str} | {pct_str} {emoji} |")

    return "\n".join(lines)


def _comparison_hybrid_vs_single_channel(run_data: dict[str, Any]) -> str:
    """Generate hybrid vs vector_only and bm25_only comparison."""
    hybrid = _get_variant_summary(run_data, "hybrid_union")
    vector = _get_variant_summary(run_data, "vector_only")
    bm25 = _get_variant_summary(run_data, "bm25_only")

    if not hybrid:
        return ""

    lines = [
        "## Hybrid vs Single-Channel Baselines",
        "",
        "> Shows that fusion outperforms individual retrieval channels.",
        "",
    ]

    metrics_keys = [
        ("NDCG@10", "ndcg_at_10"),
        ("MRR@10", "mrr_at_10"),
        ("HitRate@10", "hit_rate_at_10"),
    ]

    if vector:
        lines.extend([
            "### Hybrid vs Vector-Only",
            "",
            "| Metric | Hybrid | Vector-Only | Delta | Improvement |",
            "|--------|--------|------------|-------|-------------|",
        ])
        for label, key in metrics_keys:
            h_val = hybrid.get(key)
            v_val = vector.get(key)
            delta_str, pct_str, emoji = _format_delta(h_val, v_val)
            h_display = f"{h_val:.4f}" if isinstance(h_val, (int, float)) else "N/A"
            v_display = f"{v_val:.4f}" if isinstance(v_val, (int, float)) else "N/A"
            lines.append(f"| {label} | {h_display} | {v_display} | {delta_str} | {pct_str} {emoji} |")
        lines.append("")

    if bm25:
        lines.extend([
            "### Hybrid vs BM25-Only",
            "",
            "| Metric | Hybrid | BM25-Only | Delta | Improvement |",
            "|--------|--------|-----------|-------|-------------|",
        ])
        for label, key in metrics_keys:
            h_val = hybrid.get(key)
            b_val = bm25.get(key)
            delta_str, pct_str, emoji = _format_delta(h_val, b_val)
            h_display = f"{h_val:.4f}" if isinstance(h_val, (int, float)) else "N/A"
            b_display = f"{b_val:.4f}" if isinstance(b_val, (int, float)) else "N/A"
            lines.append(f"| {label} | {h_display} | {b_display} | {delta_str} | {pct_str} {emoji} |")

    return "\n".join(lines)


def _vietnamese_quality(run_data: dict[str, Any]) -> str:
    """Generate Vietnamese query quality section."""
    slice_summaries = run_data.get("slice_summaries", [])
    vi_hybrid = next(
        (s for s in slice_summaries
         if s.get("slice") == "vietnamese" and s.get("variant") == "hybrid_union"),
        None,
    )
    vi_title = next(
        (s for s in slice_summaries
         if s.get("slice") == "vietnamese" and s.get("variant") == "title_only"),
        None,
    )
    en_hybrid = next(
        (s for s in slice_summaries
         if s.get("slice") == "english" and s.get("variant") == "hybrid_union"),
        None,
    )

    if not vi_hybrid:
        return "## Vietnamese Query Quality\n\n⚠️ No Vietnamese slice data available."

    lines = [
        "## 🇻🇳 Vietnamese Query Quality",
        "",
        "> Vietnamese queries go through Ollama translation + BGE-M3 multilingual embedding.",
        "",
    ]

    qc = vi_hybrid.get("query_count", 0)
    vi_ndcg = vi_hybrid.get("ndcg_at_10")
    vi_mrr = vi_hybrid.get("mrr_at_10")
    vi_hit = vi_hybrid.get("hit_rate_at_10")

    lines.append(f"- **Vietnamese queries:** {qc}")
    if vi_ndcg is not None:
        lines.append(f"- **NDCG@10:** {vi_ndcg:.4f}")
    if vi_mrr is not None:
        lines.append(f"- **MRR@10:** {vi_mrr:.4f}")
    if vi_hit is not None:
        lines.append(f"- **HitRate@10:** {vi_hit:.1%}")

    # Comparison with English
    if en_hybrid:
        en_ndcg = en_hybrid.get("ndcg_at_10")
        if vi_ndcg is not None and en_ndcg is not None:
            gap = round(vi_ndcg - en_ndcg, 4)
            sign = "+" if gap > 0 else ""
            lines.extend([
                "",
                f"**Vietnamese vs English gap:** NDCG@10 delta = {sign}{gap}",
            ])
            if abs(gap) < 0.1:
                lines.append("> ✅ Vietnamese retrieval quality is comparable to English.")
            else:
                lines.append("> ⚠️ Significant gap between Vietnamese and English quality.")

    # Comparison with title_only for Vietnamese
    if vi_title:
        t_ndcg = vi_title.get("ndcg_at_10")
        if vi_ndcg is not None and t_ndcg is not None:
            delta_str, pct_str, emoji = _format_delta(vi_ndcg, t_ndcg)
            lines.extend([
                "",
                f"**Hybrid vs Title-Only for Vietnamese:** NDCG@10 {delta_str} ({pct_str}) {emoji}",
            ])

    return "\n".join(lines)


def _price_filter_quality(run_data: dict[str, Any]) -> str:
    """Generate price-filter quality section."""
    slice_summaries = run_data.get("slice_summaries", [])
    pf_hybrid = next(
        (s for s in slice_summaries
         if s.get("slice") == "price_filter" and s.get("variant") == "hybrid_union"),
        None,
    )

    if not pf_hybrid:
        return "## Price-Filter Quality\n\n⚠️ No price_filter slice data available."

    lines = [
        "## 💰 Price-Filter Quality",
        "",
        "> Queries with explicit price constraints (e.g., 'sunscreen under 200k').",
        "",
    ]

    qc = pf_hybrid.get("query_count", 0)
    ndcg = pf_hybrid.get("ndcg_at_10")
    hit = pf_hybrid.get("hit_rate_at_10")
    prec = pf_hybrid.get("precision_at_5")

    lines.append(f"- **Price-filter queries:** {qc}")
    if ndcg is not None:
        lines.append(f"- **NDCG@10:** {ndcg:.4f}")
    if hit is not None:
        lines.append(f"- **HitRate@10:** {hit:.1%}")
    if prec is not None:
        lines.append(f"- **Precision@5:** {prec:.4f}")

    return "\n".join(lines)


def _cold_start_exposure(run_data: dict[str, Any]) -> str:
    """Generate cold-start exposure section with correct framing."""
    cold_warm_ratio = run_data.get("cold_warm_ratio", {})
    hybrid = _get_variant_summary(run_data, "hybrid_union")
    no_cold = _get_variant_summary(run_data, "hybrid_no_cold_boost")

    is_cold_dominant = cold_warm_ratio.get("dataset_is_cold_dominant", False)

    lines = [
        "## ❄️ Cold-Start Exposure Quality" if is_cold_dominant else "## ❄️ Cold-Start Lift",
        "",
    ]

    if is_cold_dominant:
        lines.append("> ⚠️ Dataset is cold-dominant — this measures whether surfaced cold items are relevant, "
                     "NOT cold vs warm lift.")
        lines.append("")

    if cold_warm_ratio:
        lines.append(f"- **Cold items:** {cold_warm_ratio.get('cold_items', 0)}")
        lines.append(f"- **Warm items:** {cold_warm_ratio.get('warm_items', 0)}")
        lines.append(f"- **Cold percentage:** {cold_warm_ratio.get('cold_percentage', 0)}%")

    if hybrid:
        cold_rate = hybrid.get("cold_relevant_rate_at_10")
        cold_share = hybrid.get("cold_share_of_relevant_at_10")
        raw_cov = hybrid.get("raw_cold_coverage_at_10")
        lines.append("")
        if cold_rate is not None:
            lines.append(f"- **ColdRelevantRate@10:** {cold_rate:.4f} — "
                         f"{'Good! Cold items are relevant' if cold_rate > 0.3 else 'Low — cold items may need better content'}")
        if cold_share is not None:
            lines.append(f"- **ColdShareOfRelevant@10:** {cold_share:.4f}")
        if raw_cov is not None:
            lines.append(f"- **RawColdCoverage@10:** {raw_cov:.4f}")

    # Ablation comparison: hybrid vs no_cold_boost
    if hybrid and no_cold:
        h_ndcg = hybrid.get("ndcg_at_10")
        nc_ndcg = no_cold.get("ndcg_at_10")
        if h_ndcg is not None and nc_ndcg is not None:
            delta_str, pct_str, emoji = _format_delta(h_ndcg, nc_ndcg)
            lines.extend([
                "",
                "### Cold Boost Ablation",
                "",
                f"- **Hybrid (with boost) NDCG@10:** {h_ndcg:.4f}",
                f"- **Hybrid (no boost) NDCG@10:** {nc_ndcg:.4f}",
                f"- **Delta:** {delta_str} ({pct_str}) {emoji}",
            ])

    return "\n".join(lines)


def _latency_profile(run_data: dict[str, Any]) -> str:
    """Generate latency profile section."""
    latency = run_data.get("latency", [])
    if not latency:
        return "## Latency\n\n⚠️ No latency data available."

    search_latencies = sorted([r["search_latency_ms"] for r in latency if "search_latency_ms" in r])
    total_latencies = sorted([r["total_latency_ms"] for r in latency if "total_latency_ms" in r])
    qp_latencies = sorted([r["query_processing_latency_ms"] for r in latency if "query_processing_latency_ms" in r])

    if not search_latencies:
        return "## Latency\n\n⚠️ No search latency measurements."

    s_p50 = search_latencies[len(search_latencies) // 2]
    s_p95_idx = min(int(len(search_latencies) * 0.95), len(search_latencies) - 1)
    s_p95 = search_latencies[s_p95_idx]

    lines = [
        "## ⚡ Latency Profile",
        "",
        f"**Sample size:** {len(search_latencies)} measurements",
        "",
        "| Stage | P50 | P95 | Min | Max |",
        "|-------|-----|-----|-----|-----|",
    ]

    lines.append(f"| Search | {s_p50:.0f}ms | {s_p95:.0f}ms | "
                 f"{min(search_latencies):.0f}ms | {max(search_latencies):.0f}ms |")

    if qp_latencies:
        qp_p50 = qp_latencies[len(qp_latencies) // 2]
        qp_p95 = qp_latencies[min(int(len(qp_latencies) * 0.95), len(qp_latencies) - 1)]
        lines.append(f"| Query Processing | {qp_p50:.0f}ms | {qp_p95:.0f}ms | "
                     f"{min(qp_latencies):.0f}ms | {max(qp_latencies):.0f}ms |")

    if total_latencies:
        t_p50 = total_latencies[len(total_latencies) // 2]
        t_p95 = total_latencies[min(int(len(total_latencies) * 0.95), len(total_latencies) - 1)]
        lines.append(f"| Total E2E | {t_p50:.0f}ms | {t_p95:.0f}ms | "
                     f"{min(total_latencies):.0f}ms | {max(total_latencies):.0f}ms |")

    # Per-variant latency breakdown
    variants_in_latency = sorted(set(r.get("variant", "") for r in latency))
    if len(variants_in_latency) > 1:
        lines.extend(["", "### Per-Variant Latency", ""])
        lines.append("| Variant | P50 Search | P95 Search | Samples |")
        lines.append("|---------|-----------|-----------|---------|")
        for v in variants_in_latency:
            v_lats = sorted([r["search_latency_ms"] for r in latency
                             if r.get("variant") == v and "search_latency_ms" in r])
            if v_lats:
                vp50 = v_lats[len(v_lats) // 2]
                vp95 = v_lats[min(int(len(v_lats) * 0.95), len(v_lats) - 1)]
                lines.append(f"| {v} | {vp50:.0f}ms | {vp95:.0f}ms | {len(v_lats)} |")

    return "\n".join(lines)


def _select_qualitative_examples(run_data: dict[str, Any], n: int = 5) -> list[dict[str, Any]]:
    """Select the most compelling side-by-side examples.

    Priority:
    1. Queries where hybrid is clearly better than title_only
    2. Vietnamese queries that work well
    3. Price-filter queries showing semantic understanding
    """
    per_query = run_data.get("per_query_metrics", [])
    results = run_data.get("results", [])
    queries_by_id = {
        q.get("query_id", ""): q.get("raw_query", q.get("query_id", ""))
        for q in run_data.get("queries", [])
    }

    # Group results by (query_id, variant)
    results_by_qv: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in results:
        key = (r.get("query_id", ""), r.get("variant", ""))
        results_by_qv.setdefault(key, []).append(r)

    examples = []
    query_ids = sorted(set(m["query_id"] for m in per_query if "query_id" in m))

    for qid in query_ids:
        hybrid_metrics = next(
            (m for m in per_query if m.get("query_id") == qid and m.get("variant") == "hybrid_union"),
            None,
        )
        title_metrics = next(
            (m for m in per_query if m.get("query_id") == qid and m.get("variant") == "title_only"),
            None,
        )
        if hybrid_metrics and title_metrics:
            h_ndcg = hybrid_metrics.get("ndcg_at_10", 0) or 0
            t_ndcg = title_metrics.get("ndcg_at_10", 0) or 0
            delta = h_ndcg - t_ndcg if isinstance(h_ndcg, (int, float)) and isinstance(t_ndcg, (int, float)) else 0
            if delta > 0:
                hybrid_results = results_by_qv.get((qid, "hybrid_union"), [])[:3]
                title_results = results_by_qv.get((qid, "title_only"), [])[:3]

                examples.append({
                    "query_id": qid,
                    "raw_query": queries_by_id.get(qid, qid),
                    "delta_ndcg": delta,
                    "hybrid_results": hybrid_results,
                    "title_results": title_results,
                })

    # Sort by delta_ndcg descending, take top N
    examples.sort(key=lambda x: x["delta_ndcg"], reverse=True)
    return examples[:n]


def _qualitative_examples(run_data: dict[str, Any]) -> str:
    """Generate qualitative side-by-side comparison examples."""
    examples = _select_qualitative_examples(run_data, n=5)
    if not examples:
        return "## 🌟 Qualitative Examples\n\n⚠️ No compelling side-by-side examples found."

    lines = ["## 🌟 Qualitative Examples: Why Hybrid Search is Better", ""]

    for i, ex in enumerate(examples, 1):
        lines.append(f"### Example {i}: \"{ex.get('raw_query', ex['query_id'])}\"")
        lines.append("")

        # Title-only results
        if ex["title_results"]:
            lines.append("**Title-Only Results** (simple keyword matching):")
            for r in ex["title_results"]:
                title = r.get("title", "Unknown")
                score = r.get("score", 0)
                rank = r.get("rank", "?")
                lines.append(f"  {rank}. {title} (score: {score:.3f})" if isinstance(score, (int, float))
                             else f"  {rank}. {title}")
        else:
            lines.append("**Title-Only Results**: No results returned")

        lines.append("")

        # Hybrid results
        if ex["hybrid_results"]:
            lines.append("**Hybrid Results** (semantic + factual understanding):")
            for r in ex["hybrid_results"]:
                title = r.get("title", "Unknown")
                score = r.get("score", 0)
                rank = r.get("rank", "?")
                intent = r.get("matched_intent", "")
                fact = r.get("matched_fact", "")
                lines.append(f"  {rank}. {title} (score: {score:.3f})" if isinstance(score, (int, float))
                             else f"  {rank}. {title}")
                if intent:
                    lines.append(f"     ↳ Intent match: \"{str(intent)[:80]}\"")
                if fact:
                    lines.append(f"     ↳ Fact match: \"{str(fact)[:80]}\"")
        else:
            lines.append("**Hybrid Results**: No results returned")

        lines.append("")
        lines.append(
            f"**Why hybrid is better**: Hybrid matches buyer intent and product facts beyond title keywords. "
            f"NDCG improvement: +{ex['delta_ndcg']:.3f}"
            if isinstance(ex['delta_ndcg'], (int, float))
            else "**Why hybrid is better**: Hybrid matches buyer intent and product facts beyond title keywords."
        )
        lines.append("")

    return "\n".join(lines)


def _business_story(run_data: dict[str, Any]) -> str:
    """Map technical metrics to business impact stories."""
    hybrid = _get_variant_summary(run_data, "hybrid_union")
    coverage = run_data.get("coverage_stats", run_data.get("config", {}))
    cold_warm = run_data.get("cold_warm_ratio", {})

    stories = [
        "## 📊 Business Impact Summary",
        "",
        "### For Buyers (Search Quality)",
        "",
    ]

    if hybrid:
        ndcg = hybrid.get("ndcg_at_10")
        hit_rate = hybrid.get("hit_rate_at_10")
        mrr = hybrid.get("mrr_at_10")
        if ndcg is not None:
            stories.append(
                f"- **Tìm đúng sản phẩm hơn**: NDCG@10 = {ndcg:.3f} — "
                "hybrid search hiểu buyer intent qua semantic matching, "
                "không chỉ keyword matching như title-only"
            )
        if hit_rate is not None:
            stories.append(
                f"- **Ít search thất bại**: HitRate@10 = {hit_rate:.1%} — "
                f"{hit_rate:.0%} queries tìm được ít nhất 1 sản phẩm phù hợp"
            )
        if mrr is not None:
            stories.append(
                f"- **Kết quả tốt nhất lên đầu**: MRR@10 = {mrr:.3f} — "
                "sản phẩm phù hợp nhất xuất hiện sớm trong kết quả tìm kiếm"
            )

    stories.extend([
        "",
        "### For New Sellers (Cold-Start Exposure)",
        "",
    ])

    if hybrid:
        cold_rate = hybrid.get("cold_relevant_rate_at_10")
        if cold_rate is not None and cold_rate > 0:
            stories.append(
                f"- **Seller mới vẫn được surface**: {cold_rate:.1%} cold-start items "
                "xuất hiện trong top 10 kết quả VÀ thực sự relevant — "
                "không sacrifice quality để boost new sellers"
            )
        else:
            stories.append("- Cold-start exposure data unavailable or zero")

    stories.extend([
        "",
        "### For Platform Performance",
        "",
    ])

    latency = run_data.get("latency", [])
    if latency:
        search_lats = sorted([l["search_latency_ms"] for l in latency if "search_latency_ms" in l])
        if search_lats:
            p50 = search_lats[len(search_lats) // 2]
            stories.append(
                f"- **Search vẫn nhanh**: P50 search latency = {p50:.0f}ms — "
                "đủ nhanh cho real-time e-commerce search"
            )

    stories.extend([
        "",
        "### For Vietnamese Users",
        "",
    ])

    slice_summaries = run_data.get("slice_summaries", [])
    vi_slices = [s for s in slice_summaries
                 if s.get("slice") == "vietnamese" and s.get("variant") == "hybrid_union"]
    if vi_slices:
        vi = vi_slices[0]
        vi_ndcg = vi.get("ndcg_at_10")
        if vi_ndcg is not None:
            stories.append(
                f"- **Vietnamese/e-commerce intent handling**: Vietnamese queries achieve "
                f"NDCG@10 = {vi_ndcg:.3f} — Ollama translation + BGE-M3 multilingual "
                "embedding handles Vietnamese search well"
            )
        else:
            stories.append("- Vietnamese NDCG data not available yet — needs more judgments")
    else:
        stories.append("- Vietnamese slice data unavailable — ensure Vietnamese queries have labels")

    stories.extend([
        "",
        "---",
        "",
        "*Generated by ColdStart_Killer evaluation framework.*",
    ])

    return "\n".join(stories)
