# Evaluation Framework

This directory contains the evaluation data for ColdStart_Killer retrieval quality assessment.

The current evaluation seed is no longer empty. It includes 50 retrieval queries, 20 diagnostic probes, and AI-assisted conservative judgments.

> ⚠️ Labels are AI-assisted (LLM-scored with conservative thresholds), not fully human-audited ground truth. Treat NDCG/Recall as indicative metrics.

## Current Status

Latest verified live run:

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/plan_review_live
```

Result summary:

| Item | Value |
|---|---:|
| Retrieval queries | 50 |
| Diagnostic probes | 20 |
| AI-assisted conservative judgments | 2,119 |
| Judged queries | 50 |
| Queries with relevance >= 2 | 43 |
| Live retrieval results | 2,425 |
| Evaluation failures | 0 |
| Report status | sufficient |
| Search P95 latency | 116.5ms |
| Total P95 latency | 1173.0ms |

Live MongoDB data snapshot:

| Metric | Value |
|---|---:|
| items | 3,000 |
| retrieval_units | 29,753 |
| HyPE units | 13,580 |
| proposition units | 16,173 |
| cold items | 3,000 (100% cold — interaction_count=0) |
| categories | All_Beauty, Cell_Phones_and_Accessories |
| VECTOR_NUM_CANDIDATES | 400 |
| VECTOR_CHANNEL_LIMIT | 20 |

`category_id` is NOT a hard filter — category intent is handled by BGE-M3 embedding semantics in `$vectorSearch`. `hard_filters` only supports: `in_stock`, `price_max`, `price_min`.

Main live metrics:

| Variant | NDCG@10 | Recall@10 | MRR@10 | HitRate@10 | ColdRelevantRate@10 |
|---|---:|---:|---:|---:|---:|
| `title_only` | 0.5537 | 0.3154 | 0.4992 | 0.74 | 0.3020 |
| `vector_only` | 0.7195 | 0.4005 | 0.5537 | 0.74 | 0.3727 |
| `bm25_only` | 0.6042 | 0.3303 | 0.5546 | 0.76 | 0.3363 |
| `hybrid_union` | 0.7735 | 0.4478 | 0.6817 | 0.78 | 0.3920 |
| `hybrid_no_cold_boost` | 0.7735 | 0.4478 | 0.6817 | 0.78 | 0.3920 |

Important caveats:

- The current labels are AI-assisted conservative judgments. They pass local coverage gates, but a human audit is recommended before publication-grade claims.
- The latest live run is cold-dominant: 300 cold items, 0 warm items, 0 unknown items in the sampled top results. Cold-start metrics therefore measure **exposure quality**, not cold-vs-warm lift.
- Cold-start window measurement is not available until source data includes lifecycle timestamps such as `indexed_at` and `first_seen_in_top_k_at`.
- Search P95 latency is under 400ms, but total P95 latency is 1173.0ms in the latest run. The report therefore supports measured live latency, not a claim that the full query path is already below 400ms.

## Structure

```text
evaluation/
  queries/
    diagnostic_probes.json      # 20 Layer-1 diagnostic probes
    retrieval_queries_seed.json # 50 Layer-2 retrieval queries
  judgments/
    retrieval_judgments_seed.json # 2,119 AI-assisted conservative judgments
```

Runtime artifacts are written under `.runtime/evaluation/<run_id>/`.

Important generated artifacts:

- `metrics_summary.md` — technical report with coverage, variants, claims, slice analysis, failures, latency, explanation coverage.
- `hackathon_impact_report.md` — judge-facing report with business impact, deltas, qualitative examples, and caveats.
- `config.json` — reproducibility metadata.
- `layer2_metrics_summary.json` — aggregate variant metrics.
- `layer2_metrics_by_query.csv` — per-query metrics.
- `layer2_raw_results.json` — raw retrieval results.

## Evaluation Layers

### Layer 1: Diagnostic Probes

Layer 1 checks query processing behavior:

- Language detection.
- Vietnamese to English translation path.
- Price filter extraction.
- Price/filter extraction; category intent is handled by embedding semantics, not hard filters.
- Known unsupported cases and edge cases.

Run:

```bash
python scripts/run_eval_diagnostics.py \
  --probes evaluation/queries/diagnostic_probes.json \
  --out .runtime/evaluation/diagnostics_seed
```

### Layer 2: IR Metrics

Layer 2 measures retrieval quality across 5 variants:

- `title_only`
- `vector_only`
- `bm25_only`
- `hybrid_union`
- `hybrid_no_cold_boost`

Metrics:

| Metric | Definition |
|---|---|
| NDCG@K | Normalized Discounted Cumulative Gain at rank K |
| Precision@K | Fraction of top-K results that are relevant |
| Recall@K | Fraction of all known relevant items found in top-K |
| MRR@K | Reciprocal rank of the first relevant result |
| HitRate@K | 1 if any relevant result appears in top-K, else 0 |
| ColdRelevantRate@K | Fraction of top-K results that are both cold and relevant |
| ColdShareOfRelevant@K | Fraction of relevant top-K results that are cold |
| RawColdCoverage@K | Fraction of top-K results that are cold; diagnostic only |

### Layer 3: Claim Verification

Layer 3 converts metrics into report claims with evidence gates.

Claim statuses:

- `supported` — enough evidence and metrics support the claim.
- `unsupported` — enough evidence and metrics do not support the claim.
- `needs_more_evidence` — missing data, missing variant, insufficient judgment coverage, null metrics, or unavailable timestamp fields.

Current live claim summary:

| Claim | Status | Notes |
|---|---|---|
| Hybrid beats title baseline | supported | Hybrid NDCG/Recall/MRR beat title-only |
| Hybrid beats single-channel baselines | supported | Hybrid NDCG beats vector-only and BM25-only |
| Cold-start exposure quality | supported | ColdRelevantRate@10 is positive, but dataset is cold-dominant |
| Cold-start window was measured | needs_more_evidence | Missing lifecycle timestamps |
| Vietnamese robustness | supported | Hybrid Vietnamese NDCG@10 = 0.856 > title = 0.4913 |
| Live end-to-end latency | supported | Measured on live MongoDB with fresh fixtures and 250 samples; search P95 = 116.5ms, total P95 = 1173.0ms |

## Relevance Labeling Rules

### Relevance Scale

| Score | Label | Meaning |
|---|---|---|
| 3 | Highly relevant | Exact or near-exact match. Correct product type and key constraints. |
| 2 | Relevant | Useful result. Correct product family, but some constraints are partial or implicit. |
| 1 | Marginally relevant | Same broad domain, but weak product or intent match. |
| 0 | Not relevant | Wrong category, wrong compatibility, hard filter miss, or clearly irrelevant. |

### Decision Rules

1. If the item has no valid product identity or title, use score `0`.
2. If the item is in the wrong domain/category for the query, use score `0`.
3. If the item violates a hard price filter, use score `0`.
4. If the item has incompatible device/model support, use score `0` or cap at `1` depending on severity.
5. If the title matches the core product type but misses a key constraint, use score `2`.
6. If the title matches both core product type and key constraints, use score `3`.
7. If only domain matches but the core product type does not, use score `1`.

### Labels Field

The current seed labels include tags such as:

- `auto_ai_assisted`
- `title_guarded`
- `domain_beauty`
- `domain_electronics`
- `price_ok`
- `price_violation`
- `compatibility_weak`
- `core_match`
- `constraint_match`
- `partial_match`
- `strong_match`
- `weak_match`
- `unrelated`

These labels are diagnostic. Evaluation metrics use the integer `relevance` score.

## Judgment Workflow

The seed judgments are already populated. Use this workflow only when rebuilding or auditing labels.

### Step 1: Build the Judgment Pool

Requires live MongoDB, Ollama/Qwen3:8b, and BGE-M3.

```bash
python scripts/build_eval_pool.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --out .runtime/evaluation/pool_seed \
  --top-k 20 \
  --variants title_only vector_only bm25_only hybrid_union hybrid_no_cold_boost
```

This writes:

- `.runtime/evaluation/pool_seed/judgment_pool.csv`
- `.runtime/evaluation/pool_seed/failures.json`
- `.runtime/evaluation/pool_seed/manifest.json`

### Step 2: Label or Audit the CSV

Edit these columns:

- `relevance` — integer `0`, `1`, `2`, or `3`
- `reason` — short reason for the label
- `labels` — comma-separated diagnostic tags

### Step 3: Import Judgments

```bash
python scripts/import_eval_judgments.py \
  --csv .runtime/evaluation/pool_seed/judgment_pool.csv \
  --out evaluation/judgments/retrieval_judgments_seed.json \
  --strict
```

`--strict` fails on empty or invalid relevance values.

### Step 4: Verify Judgment Gates

Minimum gates:

- >= 200 judgments
- >= 30 judged query IDs
- >= 20 query IDs with at least one relevance `>= 2`
- >= 3 judged queries for each core slice: `english`, `vietnamese`, `price_filter`, `compatibility`

Current seed passes these gates.

## Running Evaluation

### Smoke Test

No MongoDB/Ollama/BGE-M3 required:

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/smoke \
  --use-fake-results
```

Smoke mode validates the report pipeline, but fake item IDs do not represent live retrieval quality.

### Full Live Evaluation

Requires MongoDB, Ollama/Qwen3:8b, and BGE-M3:

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/eval_seed
```

`scripts/run_evaluation.py` writes both:

- `metrics_summary.md`
- `hackathon_impact_report.md`

### Phase 12 Personalization Evaluation

Phase 12 measures homepage-style personalization and CF lift with a temporal split over clickstream data.

Dry-run against live MongoDB data:

```bash
python scripts/run_personalization_evaluation.py --dry-run
```

Optional local output directory override:

```bash
python scripts/run_personalization_evaluation.py \
  --out .runtime/evaluation/personalization_live
```

Optional MongoDB summary write after local artifacts are created:

```bash
python scripts/run_personalization_evaluation.py --write-evaluation-run
```

Phase 12 baselines:

- `content_only`
- `exploration_only`
- `popularity`
- `profile_only`
- `profile_plus_cf`

Phase 12 artifacts:

- `config.json`
- `baseline_summaries.json`
- `comparisons.json`
- `per_user_metrics.json`
- `per_user_metrics.csv`
- `metrics_summary.md`
- `manifest.json`

Important caveat:

- Current demo data is synthetic/demo behavior. The Phase 12 report labels this explicitly and should not be described as human-ground-truth validation.
- The evaluator rebuilds popularity and item-item CF from the train portion of each user's history to avoid future-event leakage.

## Tests

Run the evaluation-related test subset:

```bash
python -m pytest \
  tests/test_evaluation_dataset.py \
  tests/test_evaluation_metrics.py \
  tests/test_evaluation_diagnostics.py \
  tests/test_evaluation_guardrails.py \
  tests/test_evaluation_runner.py \
  tests/test_evaluation_variants.py \
  tests/test_evaluation_polish.py \
  tests/test_hackathon_report.py \
  tests/test_import_eval_judgments.py \
  -v
```

Run the full suite:

```bash
python -m pytest tests/ -v
```

Latest full-suite result:

```text
101 passed, 1 warning
```
