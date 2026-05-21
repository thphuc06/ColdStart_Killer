# Evaluation Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a three-layer evaluation system for ColdStart_Killer that can diagnose pipeline failures, prove retrieval quality against baselines, and produce demo/business-readiness evidence for the MongoDB hackathon.

**Architecture:** Evaluation is an offline-first, read-only layer beside the existing indexing and search pipeline. It uses committed query suites and human relevance judgments under `evaluation/`, writes run artifacts under `.runtime/evaluation/`, reuses `src/query_processor.py` and `src/search_pipeline.py`, and adds evaluation-only variants without changing production search behavior.

**Tech Stack:** Python, PyMongo read-only aggregation, existing MongoDB Atlas Vector Search/Search pipelines, pandas, pytest, JSON, CSV, Markdown.

---

## 1. Evaluation Philosophy

This phase should not produce one impressive-looking metric table and stop there. ColdStart_Killer needs three different evaluation views because each answers a different question:

1. **Layer 1 - Component Diagnostics:** If the system fails, where did it fail?
2. **Layer 2 - Retrieval Quality:** Is hybrid cold-start retrieval better than simpler baselines?
3. **Layer 3 - Demo and Business Readiness:** Is the system fast, useful, explainable, and robust enough for an ecommerce demo?

Only Layer 2 is the main scientific retrieval score. Layer 1 is for debugging. Layer 3 is for judging demo risk and business impact.

## 2. Phase Boundary

Evaluation is allowed to:

- Read committed query, probe, and judgment files.
- Generate query fixtures through `process_query()` when needed.
- Run MongoDB aggregation in read-only mode.
- Produce local run artifacts under `.runtime/evaluation/`.
- Produce human-readable reports under `.runtime/evaluation/<run_id>/`.
- Add evaluation-only code paths for baselines and ablations.

Evaluation must not:

- Insert, update, or delete MongoDB documents.
- Modify `items` or `retrieval_units`.
- Create Atlas indexes automatically.
- Depend on Brave/Tavily/live enrichment.
- Treat LLM-as-judge as the primary metric.
- Add Streamlit or any app layer.
- Change production search defaults unless a later task explicitly asks for a retrieval fix.

### Production Pipeline Safety Rule

The first evaluation implementation pass must not change production search behavior.

Do not modify the default behavior of:

- `src/search_pipeline.py::run_search`
- the existing `hybrid_union` ranking path
- default scoring constants such as `COLD_START_BOOST`
- existing MongoDB aggregation behavior used by demos

Evaluation code may import and call production pipeline functions, but it must not change their defaults.

For `hybrid_no_cold_boost`, prefer an evaluation-only ablation builder. If that cannot be implemented safely without touching production scoring, mark the variant as `variant_unavailable` and continue with the other variants.

### Read-only Enforcement

Evaluation must be read-only against MongoDB.

Evaluation code must not call:

```text
insert_one
insert_many
update_one
update_many
replace_one
delete_one
delete_many
bulk_write
create_index
drop_index
```

Add a test that uses a fake collection object whose write methods raise immediately. Evaluation tests must pass with this fake collection.

If any evaluation path needs a write, it is out of scope for this phase.

## 3. Existing Codebase Anchors

Reuse these files:

- `src/query_processor.py`: language detection, translation, price filter extraction, fixture generation.
- `src/search_pipeline.py`: hybrid MongoDB retrieval, vector/BM25 subpipelines, scoring, filtering.
- `src/retrieval_output.py`: explainable result formatting.
- `src/mongodb.py`: MongoDB collection access.
- `scripts/run_search.py`: fixture-based search runner.
- `tests/test_pipeline.py`: mock-collection pattern for pipeline tests.
- `notebooks/03_buyer_search_pipeline_test.ipynb`: live pipeline health notebook.
- `notebooks/04_demo_buyer_search.ipynb`: demo result presentation pattern.
- `TESTING.md` and `RUNBOOK.md`: operator documentation.

Do not assume these exist on every machine:

- `analysis/mvp_3000_items_diverse.csv`
- live MongoDB data
- ready Atlas indexes
- local BGE-M3 model cache
- running Ollama server

The evaluation tools should fail with precise messages when live dependencies are missing.

### 3.1 Production Function Signatures Used By Evaluation

Evaluation code calls these existing functions. Do not change their signatures or defaults.

```python
# src/query_processor.py — Layer 1 diagnostics call these directly
def detect_language(text: str) -> str:  # returns "vi" or "en"
def translate_to_english(text: str) -> str:  # calls Ollama Qwen3
def extract_hard_filters(text: str) -> dict:  # returns {"in_stock": True, "price_max": ..., ...}
def build_hype_query(english_query: str) -> str:  # returns "user looking for ... for everyday use"
def build_bm25_query(english_query: str) -> str:  # removes stop words, deduplicates
def process_query(raw_query: str) -> dict:  # full pipeline → fixture dict

# src/search_pipeline.py — variant runners call these
def run_search(fixture, top_k=10, mode="unionWith", collection=None) -> list[dict]
def build_union_with_pipeline(fixture, top_k=10) -> list[dict]  # $unionWith RRF
def vector_subpipeline(query_embedding, hard_filters, num_candidates=400, channel_limit=20) -> list[dict]
def bm25_subpipeline(bm25_search_query_en, hard_filters, channel_limit=20) -> list[dict]
def post_fusion_stages(hard_filters, top_k) -> list[dict]  # group + lookup + score + sort
def validate_query_fixture(fixture) -> dict
def normalize_hard_filters(hard_filters) -> dict

# src/retrieval_output.py — result normalization
def build_explainable_result(result: dict) -> dict  # normalizes raw aggregation output
```

### 3.2 Production Scoring Constants

These constants are defined in `src/search_pipeline.py`. Evaluation must read them but never mutate them at runtime.

```python
RRF_K = 60                          # RRF smoothing constant
DEFAULT_WEIGHTS = {"vector": 0.60, "bm25": 0.40}  # fusion channel weights
MULTI_CHANNEL_BONUS = 0.05          # bonus when item matched by both channels
COLD_START_BOOST = 0.03             # unconditional boost for cold items
CONTENT_RICHNESS_WEIGHT = 0.02      # multiplied by item.content_richness
BM25_TITLE_BOOST = 1.5              # Atlas Search boost for text_search path
VECTOR_NUM_CANDIDATES = 400         # $vectorSearch numCandidates
VECTOR_CHANNEL_LIMIT = 20           # max vector results per query
BM25_CHANNEL_LIMIT = 20             # max BM25 results per query
EMBEDDING_DIM = 1024                # BGE-M3 embedding dimension
```

### 3.3 Pipeline Output Field Contract

`run_search()` returns results through `build_explainable_result()`. Each result dict contains:

```python
{
    "item_id": str,           # product ID (parent_asin)
    "title": str,             # product title in English
    "score": float,           # final score = fusion + bonuses
    "matched_intent": str,    # best HyPE match text (from vector channel)
    "matched_fact": str,      # best proposition match text (from BM25 channel)
    "cold_start_note": str,   # cold-start explanation or empty
    "rank_vector": int|None,  # rank in vector channel (None if not matched)
    "rank_bm25": int|None,    # rank in BM25 channel (None if not matched)
    "fusion_score": float,    # RRF fusion score before bonuses
    "debug": {
        "raw_vector_score": float,  # cosine similarity from $vectorSearch
        "raw_bm25_score": float,    # BM25 score from $search
        "matched_channels": list,   # ["vector"], ["bm25"], or ["vector", "bm25"]
        "vector_contribution": float,
        "bm25_contribution": float,
        "multi_channel_bonus": float,
        "cold_start_boost": float,
        "content_richness_bonus": float,
        "brand": str,
        "category_id": str,
        "price_vnd": int|None,
        "price_bucket": str,
        "seller_confirmed": bool|None,
    }
}
```

Evaluation must map `EvaluationResult` fields from this contract:

```text
EvaluationResult.item_id        ← result["item_id"]
EvaluationResult.score          ← result["score"]
EvaluationResult.title          ← result["title"]
EvaluationResult.brand          ← result["debug"]["brand"]
EvaluationResult.category_id    ← result["debug"]["category_id"]
EvaluationResult.price_vnd      ← result["debug"]["price_vnd"]
EvaluationResult.channels       ← result["debug"]["matched_channels"]
EvaluationResult.is_cold_item   ← True if result["cold_start_note"] is non-empty, else None
EvaluationResult.matched_intent ← result["matched_intent"]
EvaluationResult.matched_fact   ← result["matched_fact"]
```

Note: `is_cold_item` must be derived from `cold_start_note` or from the raw aggregation `is_cold_item` field. If neither is available, set to `None` and track as `unknown_cold_status_count`.

### 3.4 Query Fixture Contract

`process_query()` returns a fixture dict consumed by `run_search()`:

```python
{
    "original_query": str,          # raw user input
    "language_detected": str,       # "vi" or "en"
    "english_query": str,           # translated (or original if English)
    "hype_search_query_en": str,    # "user looking for ... for everyday use"
    "bm25_search_query_en": str,    # stop-words removed, deduplicated
    "hard_filters": dict,           # {"in_stock": True, "price_max": ...}
    "query_embedding": list[float], # 1024-dim BGE-M3 embedding
}
```

`validate_query_fixture()` requires `bm25_search_query_en` (non-empty string) and `query_embedding` (1024-dim finite float list). `hype_search_query_en` is optional in the validator.

### 3.5 MockCollection Pattern

`tests/test_pipeline.py` establishes the mock collection pattern. Evaluation tests must reuse and extend this:

```python
class MockCollection:
    def __init__(self):
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return [{
            "item_id": "B001",
            "title": "Hydrating Gel Moisturizer",
            "score": 0.92,
            "matched_intent": "birthday skincare gift for oily skin",
            "matched_fact": "The moisturizer is suitable for oily skin.",
            "rank_vector": 3,
            "rank_bm25": 7,
            "fusion_score": 0.85,
            "is_cold_item": True,
            "interaction_count": 0,
            "debug": {"raw_vector_score": 0.78, "raw_bm25_score": 11.2},
        }]
```

For read-only enforcement tests, extend with a `ReadOnlyMockCollection` that raises on all write methods:

```python
class ReadOnlyMockCollection(MockCollection):
    def insert_one(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def insert_many(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def update_one(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def update_many(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def replace_one(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def delete_one(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def delete_many(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def bulk_write(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def create_index(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
    def drop_index(self, *a, **kw): raise RuntimeError("Write attempted in evaluation")
```

### 3.6 MongoDB Collection Schema Reference

Evaluation variants that bypass `run_search()` (such as `title_only`) query these collections directly:

```text
items collection fields used by evaluation:
  _id              → item_id (parent_asin)
  title_en         → product title
  brand            → brand name
  category_id      → category identifier
  price_vnd        → price in VND
  price_bucket     → price tier string
  in_stock         → boolean
  content_richness → float, used in content_richness_bonus
  cold_start.is_cold_item    → boolean
  cold_start.interaction_count → int
  image_url        → product image URL
  description_enriched.seller_confirmed → boolean

retrieval_units collection fields used by evaluation:
  item_id, unit_type, language, embedding, raw_text, text_search,
  embedding_text, item_title_en, item_brand, confidence, aspect,
  proposition_type, category_id, price_bucket, in_stock, is_cold_item
```

## 4. Three-Layer Evaluation Framework

### 4.1 Layer 1 - Component Diagnostics

Purpose: find the broken subsystem before looking at ranking metrics.

This layer should run mostly offline and should not require MongoDB except for optional channel probes.

Diagnostic areas:

| Area | What To Check | Source Files | Output |
|---|---|---|---|
| Query language detection | English vs Vietnamese with diacritics vs Vietnamese without diacritics | `src/query_processor.py::detect_language` | pass/fail per query |
| Query translation boundary | Vietnamese queries produce usable English when Ollama is available | `src/query_processor.py::translate_to_english` | translated text and failure reason |
| Price filter extraction | `under 300k`, `dưới 500k`, `between 100k and 300k` map to correct filters | `src/query_processor.py::extract_hard_filters` | expected vs actual filters |
| Fixture generation | fixture has `bm25_search_query_en`, `hype_search_query_en`, 1024-d `query_embedding` | `src/query_processor.py::process_query` | fixture validity |
| No-diacritic Vietnamese | queries like `kem duong am cho da kho` are detected or flagged as known risk | `src/query_processor.py::detect_language` | expected fail or pass |
| Negation | queries like `not sunscreen` or `không mua kem chống nắng` are flagged as unsupported | future query logic | known unsupported |
| Channel match | top results came from vector, BM25, or both | `src/search_pipeline.py`, result `debug` | channel attribution |

Important: `negation` is not implemented now. Its diagnostics should be marked `expected_unsupported` until a feature task adds negation handling.

#### Diagnostic Status Model

Every diagnostic row must use exactly one status:

| Status | Meaning | Counts As Failure |
|---|---|---|
| `pass` | Behavior matches expectation | No |
| `fail` | Behavior unexpectedly violates expectation | Yes |
| `known_risk` | Known weak area measured for visibility | No |
| `expected_unsupported` | Feature is intentionally unsupported in this phase | No |
| `skipped_dependency_missing` | Optional live dependency is unavailable | No |
| `error` | Diagnostic crashed or returned invalid output | Yes |

Use this pass-rate formula:

```text
diagnostic_pass_rate =
  pass_count / (pass_count + fail_count + error_count)
```

Do not include `known_risk`, `expected_unsupported`, or `skipped_dependency_missing` in the denominator. Report those counts separately so known gaps do not inflate or punish the parser score.

Layer 1 generated files:

```text
.runtime/evaluation/<run_id>/layer1_diagnostics.json
.runtime/evaluation/<run_id>/layer1_diagnostics.csv
.runtime/evaluation/<run_id>/layer1_summary.md
.runtime/evaluation/<run_id>/manifest.json
```

Layer 1 success criteria:

- Query parser tests are deterministic and offline.
- Known unsupported behavior is explicit, not silently counted as success.
- Failures point to a file/function to inspect next.

### 4.2 Layer 2 - Retrieval Quality

Purpose: evaluate ranking quality with human relevance judgments.

This is the main retrieval evaluation layer.

Required variants:

| Variant | Meaning | Why It Matters |
|---|---|---|
| `title_only` | Regex keyword match on `items.title_en` and `items.brand` — bypasses retrieval units entirely | Proves the system beats simple catalog search. Uses `items` collection directly to avoid overlap with BM25 channel which already searches `item_title_en` via Atlas Search |
| `vector_only` | HyPE vector units only | Measures semantic buyer-intent channel |
| `bm25_only` | Proposition BM25 units only | Measures grounded fact channel |
| `hybrid_union` | Current `$unionWith` hybrid path | Main system under evaluation |
| `hybrid_no_cold_boost` | Hybrid without `COLD_START_BOOST` | Tests whether cold-start boost helps or adds noise |

Optional variants after MVP:

| Variant | Meaning | When To Add |
|---|---|---|
| `rank_fusion` | Native `$rankFusion` path | Only when Atlas tier supports it |
| `hybrid_no_content_bonus` | Hybrid without content richness bonus | If rich descriptions dominate ranking unfairly |
| `hybrid_vector_heavy` | Hybrid with higher vector weight | If BM25 adds noise |
| `hybrid_bm25_heavy` | Hybrid with higher BM25 weight | If HyPE vectors are too broad |

Primary metrics:

| Metric | Role |
|---|---|
| `NDCG@10` | Primary ranking metric for graded relevance `0-3` |
| `Recall@10` | Measures whether relevant items enter top 10 |
| `MRR@10` | Measures how early the first useful result appears |
| `Precision@5` | Demo-facing precision because viewers inspect top 5 |
| `HitRate@10` | Whether a query gets at least one useful result |
| `ColdRelevantRate@10` | Share of the visible result page that is both cold-start and useful |
| `ColdShareOfRelevant@10` | Among useful results, how much cold-start discovery happened |

Do not use raw cold-start exposure as a primary metric. A system can return many cold items that are irrelevant. `RawColdCoverage@K` belongs in diagnostics only.

#### Cold-start Retrieval Metrics

Use these names consistently:

```text
ColdRelevantRate@K =
  relevant cold-start results in top K / K
```

```text
ColdShareOfRelevant@K =
  relevant cold-start results in top K / relevant results in top K
```

```text
RawColdCoverage@K =
  cold-start results in top K / K
```

`RawColdCoverage@K` is diagnostic only. It does not prove quality because a system can return many cold-start items that are irrelevant. The main cold-start quality metric is `ColdRelevantRate@10`; `ColdShareOfRelevant@10` is a supporting metric.

If `is_cold_item is None`, do not count the result as cold-start for cold-start quality metrics. Report unknown cold-start status separately as `unknown_cold_status_count`.

#### Judgment Coverage Gates

The report must compute:

```text
judged_query_count
positive_judged_query_count
judged_result_count
unjudged_result_count
query_judgment_coverage_rate
result_judgment_coverage_rate
```

Definitions:

```text
query_judgment_coverage_rate =
  judged_query_count / total_query_count
```

```text
result_judgment_coverage_rate =
  judged_result_count / total_returned_result_count
```

```text
positive_judged_query_count =
  number of judged queries with at least one judgment where relevance >= 2
```

`positive_judged_query_count` is a query-level count, not a label-level count. Avoid generic coverage names in implementation and reports; use either `query_judgment_coverage_rate` or `result_judgment_coverage_rate`.

Rules:

```text
If judged_query_count < 30:
  report_status = "insufficient_judgments"
  do not claim an overall best variant.
```

```text
If positive_judged_query_count < 20:
  report_status = "insufficient_positive_judgments"
  do not claim retrieval-quality improvement.
```

```text
If query_judgment_coverage_rate < 0.50:
  mark aggregate metrics as preliminary.
```

Metrics may still be displayed, but the report must label them as insufficient or preliminary.

Layer 2 generated files:

```text
.runtime/evaluation/<run_id>/layer2_raw_results.json
.runtime/evaluation/<run_id>/layer2_normalized_results.csv
.runtime/evaluation/<run_id>/layer2_metrics_by_query.csv
.runtime/evaluation/<run_id>/layer2_metrics_summary.json
.runtime/evaluation/<run_id>/layer2_metrics_summary.md
.runtime/evaluation/<run_id>/layer2_variant_comparison.md
.runtime/evaluation/<run_id>/manifest.json
```

Layer 2 success criteria:

- `hybrid_union` beats `title_only` on `NDCG@10`, `Recall@10`, and `MRR@10`.
- `hybrid_union` is competitive with or better than both single-channel variants.
- If a single-channel variant wins, the report explains which query slices caused it.
- `hybrid_no_cold_boost` tells whether the current unconditional cold boost is useful or harmful.

### 4.3 Layer 3 - Demo And Business Readiness

Purpose: translate retrieval quality into demo risk and ecommerce usefulness.

Metrics:

| Metric | Meaning |
|---|---|
| `ColdStartHit@K` | Whether a judged cold-start item appears in top K for a matching query |
| `ColdStartWindowSeconds@K` | Elapsed time from retrieval readiness to first top-K appearance |
| `P95TotalLatencyMs` | End-to-end query processing plus search latency |
| `P95QueryProcessingLatencyMs` | Translation, filter extraction, query construction, embedding |
| `P95SearchLatencyMs` | MongoDB aggregation latency only |
| `ZeroResultRate` | Fraction of queries returning zero results |
| `VietnameseFailureRate` | Failure rate for Vietnamese queries |
| `NoDiacriticVietnameseFailureRate` | Failure rate for Vietnamese no-diacritic queries |
| `PriceFilterFailureRate` | Failure rate for explicit price-filter queries |
| `ChannelCoverage` | Result share from vector only, BM25 only, and both channels |
| `ExplanationCoverage` | Share of results with `matched_intent` or `matched_fact` |

#### Cold-start Measurement Guardrail

Use:

```text
ColdStartHit@K = 1 if a judged cold-start item appears in top K, else 0
```

Use:

```text
ColdStartWindowSeconds@K = first_seen_in_top_k_at - indexed_at
```

`ColdStartWindowSeconds@K` may only be reported when both timestamps are measured during the same run:

- `indexed_at`
- `first_seen_in_top_k_at`

If timestamps are unavailable, the report must only show `ColdStartHit@K`, not a cold-start window. Do not claim production time-to-discovery or "appears after X seconds" without measured timestamps.

#### Latency Claim Guardrails

Every latency report must include:

- `warm_cache`
- `used_cached_fixtures`
- `model_download_observed`
- `ollama_used`
- `embedding_used`
- `mongodb_live`

Rules:

```text
If used_cached_fixtures = true:
  do not label total latency as live end-to-end latency.
```

```text
If model_download_observed = true:
  mark latency as cold runtime latency, not normal serving latency.
```

```text
If mongodb_live = false:
  do not claim MongoDB search latency.
```

Always report `query_processing_latency_ms`, `search_latency_ms`, and `total_latency_ms` separately.

Layer 3 generated files:

```text
.runtime/evaluation/<run_id>/layer3_demo_readiness.json
.runtime/evaluation/<run_id>/layer3_demo_readiness.md
.runtime/evaluation/<run_id>/latency_by_query.csv
.runtime/evaluation/<run_id>/failure_slices.csv
```

Layer 3 success criteria:

- Zero-result queries are listed by query id and topic.
- Latency is split into query-processing and MongoDB-search components.
- Vietnamese and price-filter failures are separated.
- Report gives demo-safe claims and avoids unsupported production claims.

## 5. Query And Judgment Design

### 5.1 Query Suites

Create:

```text
evaluation/
  queries/
    diagnostic_probes.json
    retrieval_queries_seed.json
```

Use JSON instead of JSONL because `.gitignore` currently ignores `*.jsonl`.

#### Complete Diagnostic Probes

`diagnostic_probes.json` — 20 probes covering every parser subsystem:

```json
[
  {"probe_id": "p001", "raw_query": "moisturizing cream for dry skin", "probe_type": "language_detection", "expected_language": "en", "expected_filters": {"in_stock": true}, "expected_status": "pass", "notes": "Basic English detection."},
  {"probe_id": "p002", "raw_query": "kem dưỡng ẩm cho da khô", "probe_type": "language_detection", "expected_language": "vi", "expected_filters": {"in_stock": true}, "expected_status": "pass", "notes": "Vietnamese with diacritics, clear detection from ư, ẩ, ô characters."},
  {"probe_id": "p003", "raw_query": "kem duong am cho da kho", "probe_type": "language_detection", "expected_language": "vi", "expected_filters": {"in_stock": true}, "expected_status": "known_risk", "notes": "No-diacritic Vietnamese. detect_language() uses Unicode ranges 0x1EA0-0x1EF9 and Đ/đ — this text has none. Will be classified as English. Known limitation."},
  {"probe_id": "p004", "raw_query": "sạc nhanh usb c cho iphone 15", "probe_type": "language_detection", "expected_language": "vi", "expected_filters": {"in_stock": true}, "expected_status": "pass", "notes": "Vietnamese with diacritics mixed with English brand/model names."},
  {"probe_id": "p005", "raw_query": "op lung samsung galaxy a14", "probe_type": "language_detection", "expected_language": "vi", "expected_filters": {"in_stock": true}, "expected_status": "known_risk", "notes": "No-diacritic Vietnamese (ốp lưng → op lung). Will classify as English."},
  {"probe_id": "p006", "raw_query": "wireless charger under 300k", "probe_type": "price_filter", "expected_language": "en", "expected_filters": {"in_stock": true, "price_max": 300000}, "expected_status": "pass", "notes": "English 'under Xk' pattern. extract_hard_filters regex: under\\s*(\\d+k)."},
  {"probe_id": "p007", "raw_query": "tai nghe không dây dưới 500k", "probe_type": "price_filter", "expected_language": "vi", "expected_filters": {"in_stock": true, "price_max": 500000}, "expected_status": "pass", "notes": "Vietnamese 'dưới Xk' pattern. Regex matches dưới."},
  {"probe_id": "p008", "raw_query": "serum vitamin C between 200k and 500k", "probe_type": "price_filter", "expected_language": "en", "expected_filters": {"in_stock": true, "price_min": 200000, "price_max": 500000}, "expected_status": "pass", "notes": "English price range pattern. Regex: between\\s+X\\s+and\\s+Y."},
  {"probe_id": "p009", "raw_query": "ốp điện thoại từ 100k đến 300k", "probe_type": "price_filter", "expected_language": "vi", "expected_filters": {"in_stock": true, "price_min": 100000, "price_max": 300000}, "expected_status": "known_risk", "notes": "Vietnamese price range with từ...đến pattern. KNOWN RISK: 'từ' is not in the range regex trigger words (only trong khoảng|khoảng|between|from). 'từ' matches min_match regex instead, so only price_min may be extracted. Fix: add 'từ' to range pattern in extract_hard_filters()."},
  {"probe_id": "p010", "raw_query": "phone case over 200k", "probe_type": "price_filter", "expected_language": "en", "expected_filters": {"in_stock": true, "price_min": 200000}, "expected_status": "pass", "notes": "English 'over Xk' minimum price pattern."},
  {"probe_id": "p011", "raw_query": "sunscreen SPF50 tối đa 400k", "probe_type": "price_filter", "expected_language": "vi", "expected_filters": {"in_stock": true, "price_max": 400000}, "expected_status": "pass", "notes": "Mixed language with Vietnamese tối đa (max) price pattern."},
  {"probe_id": "p012", "raw_query": "not sunscreen for oily skin", "probe_type": "negation", "expected_language": "en", "expected_filters": {"in_stock": true}, "expected_status": "expected_unsupported", "notes": "English negation. Not implemented in this phase."},
  {"probe_id": "p013", "raw_query": "không mua kem chống nắng", "probe_type": "negation", "expected_language": "vi", "expected_filters": {"in_stock": true}, "expected_status": "expected_unsupported", "notes": "Vietnamese negation (không mua = don't want to buy). Not implemented."},
  {"probe_id": "p014", "raw_query": "", "probe_type": "empty_query", "expected_language": "", "expected_filters": {}, "expected_status": "error", "notes": "Empty query should raise ValueError in _require_non_empty_text()."},
  {"probe_id": "p015", "raw_query": "   ", "probe_type": "empty_query", "expected_language": "", "expected_filters": {}, "expected_status": "error", "notes": "Whitespace-only query should raise ValueError."},
  {"probe_id": "p016", "raw_query": "best moisturizer 2024", "probe_type": "fixture_generation", "expected_language": "en", "expected_filters": {"in_stock": true}, "expected_status": "pass", "notes": "Fixture must have bm25_search_query_en, query_embedding (1024-dim). Requires Ollama+BGE-M3."},
  {"probe_id": "p017", "raw_query": "kem chống nắng cho da dầu dưới 300k", "probe_type": "fixture_generation", "expected_language": "vi", "expected_filters": {"in_stock": true, "price_max": 300000}, "expected_status": "pass", "notes": "Vietnamese fixture must translate to English, extract price, embed. Requires Ollama+BGE-M3."},
  {"probe_id": "p018", "raw_query": "a", "probe_type": "edge_case", "expected_language": "en", "expected_filters": {"in_stock": true}, "expected_status": "pass", "notes": "Single character query. Should not crash. build_bm25_query removes tokens with len <= 1."},
  {"probe_id": "p019", "raw_query": "USB-C fast charger 65W GaN under 1.5M VND", "probe_type": "price_filter", "expected_language": "en", "expected_filters": {"in_stock": true}, "expected_status": "known_risk", "notes": "Price as '1.5M VND' is not handled by current regex patterns. Known gap."},
  {"probe_id": "p020", "raw_query": "quà tặng bạn gái dịp 8/3 khoảng 200k đến 500k", "probe_type": "price_filter", "expected_language": "vi", "expected_filters": {"in_stock": true, "price_min": 200000, "price_max": 500000}, "expected_status": "pass", "notes": "Vietnamese occasion+gift+price range. Tests khoảng...đến pattern."}
]
```

#### Complete Retrieval Query Suite

`retrieval_queries_seed.json` — 50 queries covering all required slices:

```json
[
  {"query_id": "q001", "raw_query": "moisturizing cream for dry skin", "language": "en", "topic": "skincare", "intent_tags": ["moisturizing", "skin_type"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "constraint"], "notes": "English beauty, skin-type constraint."},
  {"query_id": "q002", "raw_query": "vitamin C serum for dark spots", "language": "en", "topic": "skincare", "intent_tags": ["brightening", "anti_aging"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "problem"], "notes": "English beauty, targets a skin problem."},
  {"query_id": "q003", "raw_query": "gentle cleanser for sensitive skin", "language": "en", "topic": "skincare", "intent_tags": ["gentle", "sensitive_skin"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "constraint"], "notes": "Constraint: sensitive skin, fragrance-free implied."},
  {"query_id": "q004", "raw_query": "sunscreen SPF50 for oily skin non-greasy", "language": "en", "topic": "skincare", "intent_tags": ["sun_protection", "oil_control"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "constraint"], "notes": "Multi-constraint: SPF50 + oily skin + texture."},
  {"query_id": "q005", "raw_query": "anti-aging eye cream with retinol", "language": "en", "topic": "skincare", "intent_tags": ["anti_aging", "ingredient"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty"], "notes": "Ingredient-specific beauty query."},
  {"query_id": "q006", "raw_query": "hydrating face mask for winter", "language": "en", "topic": "skincare", "intent_tags": ["hydrating", "seasonal"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "occasion"], "notes": "Seasonal/occasion beauty query."},
  {"query_id": "q007", "raw_query": "lip balm with SPF", "language": "en", "topic": "beauty", "intent_tags": ["lip_care", "sun_protection"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty"], "notes": "Simple English beauty query."},
  {"query_id": "q008", "raw_query": "hair oil for frizzy hair", "language": "en", "topic": "haircare", "intent_tags": ["hair_treatment", "frizz_control"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "problem"], "notes": "Haircare problem query."},
  {"query_id": "q009", "raw_query": "men grooming kit beard oil", "language": "en", "topic": "beauty", "intent_tags": ["mens_grooming", "beard_care"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "persona"], "notes": "Persona: men's grooming."},
  {"query_id": "q010", "raw_query": "organic natural deodorant aluminum free", "language": "en", "topic": "beauty", "intent_tags": ["natural", "ingredient_free"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "constraint"], "notes": "Constraint: aluminum-free."},
  {"query_id": "q011", "raw_query": "USB-C fast charger for iPhone 15", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["fast_charging", "compatibility"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "compatibility"], "notes": "Compatibility query: specific phone model."},
  {"query_id": "q012", "raw_query": "wireless Bluetooth earbuds noise cancelling", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["wireless", "noise_cancelling"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics"], "notes": "Feature-specific electronics query."},
  {"query_id": "q013", "raw_query": "screen protector Samsung Galaxy S24", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["screen_protection", "compatibility"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "compatibility"], "notes": "Compatibility: specific Samsung model."},
  {"query_id": "q014", "raw_query": "phone case shockproof military grade", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["protection", "durability"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "constraint"], "notes": "Constraint: shockproof + military grade."},
  {"query_id": "q015", "raw_query": "portable power bank 20000mAh", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["portable_power", "capacity"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics"], "notes": "Spec-heavy: specific capacity."},
  {"query_id": "q016", "raw_query": "wireless charger for car mount", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["wireless_charging", "car_mount"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics"], "notes": "Use-case specific electronics query."},
  {"query_id": "q017", "raw_query": "Lightning to USB-C adapter cable", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["adapter", "cable"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics"], "notes": "Specific connector type query."},
  {"query_id": "q018", "raw_query": "phone tripod for TikTok videos", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["content_creation", "tripod"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "persona"], "notes": "Persona: content creator."},
  {"query_id": "q019", "raw_query": "MagSafe wallet case iPhone", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["magsafe", "wallet"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "compatibility"], "notes": "Brand-specific accessory ecosystem."},
  {"query_id": "q020", "raw_query": "camera lens protector iPhone 15 Pro Max", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["camera_protection", "compatibility"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "compatibility"], "notes": "Very specific model compatibility."},
  {"query_id": "q021", "raw_query": "kem chống nắng cho da dầu", "language": "vi", "topic": "skincare", "intent_tags": ["sun_protection", "oily_skin"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "beauty", "constraint"], "notes": "Vietnamese beauty with diacritics."},
  {"query_id": "q022", "raw_query": "tai nghe không dây chống ồn", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["wireless", "noise_cancelling"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "electronics"], "notes": "Vietnamese electronics with diacritics."},
  {"query_id": "q023", "raw_query": "sạc nhanh usb c cho iphone 15", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["fast_charging", "compatibility"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "electronics", "compatibility"], "notes": "Vietnamese + English brand mix."},
  {"query_id": "q024", "raw_query": "dầu gội trị gàu cho nam", "language": "vi", "topic": "haircare", "intent_tags": ["anti_dandruff", "mens"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "beauty", "persona", "problem"], "notes": "Vietnamese beauty, persona (men), problem (dandruff)."},
  {"query_id": "q025", "raw_query": "ốp lưng chống sốc samsung galaxy a14", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["shockproof", "compatibility"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "electronics", "compatibility"], "notes": "Vietnamese electronics, specific model compatibility."},
  {"query_id": "q026", "raw_query": "nước hoa hồng cho da nhạy cảm", "language": "vi", "topic": "skincare", "intent_tags": ["toner", "sensitive_skin"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "beauty", "constraint"], "notes": "Vietnamese skincare with constraint."},
  {"query_id": "q027", "raw_query": "cáp sạc bền cho điện thoại android", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["durable", "charging_cable"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "electronics"], "notes": "Vietnamese electronics, durability concern."},
  {"query_id": "q028", "raw_query": "son dưỡng môi có SPF chống nắng", "language": "vi", "topic": "beauty", "intent_tags": ["lip_care", "sun_protection"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "beauty"], "notes": "Vietnamese beauty, lip care with SPF."},
  {"query_id": "q029", "raw_query": "mieng dan man hinh samsung", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["screen_protector", "compatibility"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese_no_diacritic", "electronics", "compatibility"], "notes": "No-diacritic Vietnamese. Should be miếng dán màn hình. detect_language will return en — known risk."},
  {"query_id": "q030", "raw_query": "kem duong am tot nhat", "language": "vi", "topic": "skincare", "intent_tags": ["moisturizer", "best"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese_no_diacritic", "beauty"], "notes": "No-diacritic Vietnamese. Should be kem dưỡng ẩm tốt nhất."},
  {"query_id": "q031", "raw_query": "sac nhanh iphone 15 chinh hang", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["fast_charging", "genuine"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese_no_diacritic", "electronics", "compatibility"], "notes": "No-diacritic Vietnamese: sạc nhanh chính hãng."},
  {"query_id": "q032", "raw_query": "tai nghe khong day duoi 500k", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["wireless", "budget"], "expected_filters": {"in_stock": true, "price_max": 500000}, "slices": ["vietnamese_no_diacritic", "electronics", "price_filter"], "notes": "No-diacritic Vietnamese with price. Price regex may not match duoi (dưới)."},
  {"query_id": "q033", "raw_query": "sua rua mat cho da dau", "language": "vi", "topic": "skincare", "intent_tags": ["cleanser", "oily_skin"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese_no_diacritic", "beauty"], "notes": "No-diacritic: sữa rửa mặt cho da dầu."},
  {"query_id": "q034", "raw_query": "wireless charger under 300k", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["wireless_charging", "price_constrained"], "expected_filters": {"in_stock": true, "price_max": 300000}, "slices": ["english", "electronics", "price_filter"], "notes": "English + explicit price ceiling."},
  {"query_id": "q035", "raw_query": "skincare set for beginners under 500k", "language": "en", "topic": "skincare", "intent_tags": ["starter_kit", "budget"], "expected_filters": {"in_stock": true, "price_max": 500000}, "slices": ["english", "beauty", "price_filter", "persona"], "notes": "Price + persona (beginner)."},
  {"query_id": "q036", "raw_query": "Bluetooth speaker between 200k and 400k", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["speaker", "price_range"], "expected_filters": {"in_stock": true, "price_min": 200000, "price_max": 400000}, "slices": ["english", "electronics", "price_filter"], "notes": "English price range."},
  {"query_id": "q037", "raw_query": "kem chống nắng dưới 300k", "language": "vi", "topic": "skincare", "intent_tags": ["sunscreen", "budget"], "expected_filters": {"in_stock": true, "price_max": 300000}, "slices": ["vietnamese", "beauty", "price_filter"], "notes": "Vietnamese + price."},
  {"query_id": "q038", "raw_query": "earbuds under 200k for gym", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["earbuds", "workout", "budget"], "expected_filters": {"in_stock": true, "price_max": 200000}, "slices": ["english", "electronics", "price_filter", "occasion"], "notes": "Price + occasion (gym)."},
  {"query_id": "q039", "raw_query": "cáp sạc nhanh từ 50k đến 150k", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["charging_cable", "price_range"], "expected_filters": {"in_stock": true, "price_min": 50000, "price_max": 150000}, "slices": ["vietnamese", "electronics", "price_filter"], "notes": "Vietnamese price range."},
  {"query_id": "q040", "raw_query": "serum dưỡng trắng da tối đa 400k", "language": "vi", "topic": "skincare", "intent_tags": ["whitening", "budget"], "expected_filters": {"in_stock": true, "price_max": 400000}, "slices": ["vietnamese", "beauty", "price_filter"], "notes": "Vietnamese tối đa (max) price pattern."},
  {"query_id": "q041", "raw_query": "birthday gift for girlfriend who loves skincare", "language": "en", "topic": "skincare", "intent_tags": ["gift", "birthday", "skincare_lover"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "gift", "persona", "occasion"], "notes": "Gift + persona + occasion."},
  {"query_id": "q042", "raw_query": "gift set for men grooming", "language": "en", "topic": "beauty", "intent_tags": ["gift", "mens_grooming"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "gift", "persona"], "notes": "Gift for specific persona (men)."},
  {"query_id": "q043", "raw_query": "quà tặng bạn gái thích skincare dịp valentine", "language": "vi", "topic": "skincare", "intent_tags": ["gift", "valentine", "skincare_lover"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "beauty", "gift", "persona", "occasion"], "notes": "Vietnamese gift+occasion+persona query."},
  {"query_id": "q044", "raw_query": "stocking stuffer beauty products small", "language": "en", "topic": "beauty", "intent_tags": ["gift", "small_size", "holiday"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "gift", "occasion"], "notes": "Holiday gift occasion query."},
  {"query_id": "q045", "raw_query": "accessories for Samsung Galaxy S23 Ultra", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["accessories", "compatibility"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "compatibility"], "notes": "Broad compatibility query for specific model."},
  {"query_id": "q046", "raw_query": "acne treatment for teenage skin", "language": "en", "topic": "skincare", "intent_tags": ["acne", "teenage_skin"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "persona", "problem"], "notes": "Persona (teenager) + problem (acne)."},
  {"query_id": "q047", "raw_query": "waterproof phone pouch for beach", "language": "en", "topic": "cell_phone_accessory", "intent_tags": ["waterproof", "beach"], "expected_filters": {"in_stock": true}, "slices": ["english", "electronics", "constraint", "occasion"], "notes": "Constraint (waterproof) + occasion (beach)."},
  {"query_id": "q048", "raw_query": "travel size skincare set TSA approved", "language": "en", "topic": "skincare", "intent_tags": ["travel", "small_size"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "constraint", "occasion"], "notes": "Travel constraint + occasion."},
  {"query_id": "q049", "raw_query": "phụ kiện điện thoại cho người già dễ dùng", "language": "vi", "topic": "cell_phone_accessory", "intent_tags": ["elderly", "easy_use"], "expected_filters": {"in_stock": true}, "slices": ["vietnamese", "electronics", "persona"], "notes": "Vietnamese persona query: elderly users, easy to use."},
  {"query_id": "q050", "raw_query": "night cream anti wrinkle over 40", "language": "en", "topic": "skincare", "intent_tags": ["anti_aging", "night_cream", "age_specific"], "expected_filters": {"in_stock": true}, "slices": ["english", "beauty", "persona", "problem"], "notes": "Persona (40+) + problem (wrinkles)."}
]
```

Slice coverage summary:

| Slice | Query IDs | Count |
|---|---|---|
| `english` | q001-q020, q034-q036, q038, q041-q042, q044-q048, q050 | 30 |
| `vietnamese` | q021-q028, q037, q039-q040, q043, q049 | 13 |
| `vietnamese_no_diacritic` | q029-q033 | 5 |
| `beauty` | q001-q010, q021, q024, q026, q028, q030, q033, q035, q037, q040-q044, q046, q048, q050 | 24 |
| `electronics` | q011-q020, q022-q023, q025, q027, q029, q031-q032, q034, q036, q038-q039, q045, q047, q049 | 23 |
| `price_filter` | q032, q034-q040 | 8 |
| `compatibility` | q011, q013, q019-q020, q023, q025, q029, q031, q045 | 9 |
| `persona` | q009, q018, q024, q035, q041-q043, q046, q049-q050 | 10 |
| `gift` | q041-q044 | 4 |
| `occasion` | q006, q038, q043-q044, q047-q048 | 6 |
| `problem` | q002, q008, q024, q046, q050 | 5 |
| `constraint` | q003-q004, q010, q014, q026, q047-q048 | 7 |

Queries may belong to multiple slices. Every query has at least one slice.

### 5.2 Relevance Judgments

Create:

```text
evaluation/judgments/retrieval_judgments_seed.json
```

Shape:

```json
[
  {
    "query_id": "q001",
    "item_id": "B000EXAMPLE",
    "relevance": 3,
    "reason": "Direct match: product is a wireless charger and price satisfies the query.",
    "labels": ["exact_intent", "price_match"]
  }
]
```

Relevance scale:

- `3`: exact or highly useful.
- `2`: useful but not exact.
- `1`: weakly related.
- `0`: not relevant.

Binary metrics treat `2` and `3` as relevant. `NDCG` uses the full graded value.

#### Labeling Rules With Domain Examples

**Rule 1 — Product type mismatch is always 0:**

```text
Query: "moisturizing cream for dry skin" (q001)
  Result: CeraVe Moisturizing Cream 340g       → relevance 3 (exact)
  Result: Neutrogena Sunscreen SPF50            → relevance 0 (sunscreen ≠ moisturizer)
  Result: USB-C charging cable                  → relevance 0 (wrong category entirely)
```

**Rule 2 — Price constraints:**

```text
Query: "wireless charger under 300k" (q034) → price_max = 300000 VND

  Result: Anker 313 Wireless Charger, 250,000₫  → max relevance 3 (within budget)
  Result: Belkin MagSafe Charger, 320,000₫       → max relevance 1 (≤ 15% over = 345k, still OK)
  Result: Samsung Wireless Fast Charger, 600,000₫ → relevance 0 (> 15% over max price)
  Result: Generic Qi Charger, price unknown       → max relevance 2 (type matches but price unverified)
```

**Rule 3 — Compatibility queries:**

```text
Query: "USB-C fast charger for iPhone 15" (q011)

  Result: Apple 20W USB-C Charger               → relevance 3 (exact compatibility)
  Result: Anker 30W USB-C GaN Charger            → relevance 3 (universal USB-C, compatible)
  Result: Samsung 25W USB-C Charger              → relevance 2 (USB-C works but Samsung-branded)
  Result: Apple Lightning cable                  → relevance 0 (wrong connector for iPhone 15)
  Result: Apple 5W USB-A charger                 → relevance 1 (Apple but wrong port, needs adapter)
```

**Rule 4 — Persona and occasion queries:**

```text
Query: "birthday gift for girlfriend who loves skincare" (q041)

  Result: Skincare gift set with serum + cream    → relevance 3 (strong gift + skincare fit)
  Result: Face sheet mask variety pack             → relevance 2 (reasonable gift alternative)
  Result: Single tube of hand cream                → relevance 1 (skincare but weak gift item)
  Result: Phone case with floral design            → relevance 0 (wrong category)
```

**Rule 5 — Constraint-heavy queries:**

```text
Query: "sunscreen SPF50 for oily skin non-greasy" (q004)

  Result: Biore UV Aqua Rich Watery Essence SPF50 → relevance 3 (SPF50, designed for oily skin, light texture)
  Result: La Roche-Posay Anthelios SPF50+          → relevance 2 (SPF50 but no explicit oily skin claim)
  Result: Neutrogena Ultra Sheer SPF30             → relevance 1 (lower SPF than requested)
  Result: Heavy mineral sunscreen SPF50            → relevance 1 (SPF50 but greasy texture contradicts constraint)
```

**Rule 6 — Vietnamese queries use the same rules after translation:**

```text
Query: "kem chống nắng cho da dầu" (q021) → translates to "sunscreen for oily skin"

  Same labeling rules as English equivalent. Relevance is judged on the product-query
  semantic match, not on translation quality. Translation quality is Layer 1.
```

#### Full Labeling Decision Tree

```text
1. Is the product category correct for the query?
   NO  → relevance 0 (stop)
   YES → continue

2. Does the query specify a price constraint?
   YES → Is the product within range?
         Within range         → continue (max relevance 3)
         ≤ 15% above max      → continue (max relevance 1)
         > 15% above max      → relevance 0 (stop)
         Price unknown         → continue (max relevance 2)
   NO  → continue

3. Does the query specify a compatibility constraint (brand/model)?
   YES → Does the product match?
         Exact model match     → continue (max relevance 3)
         Universal + evidence  → continue (max relevance 2 or 3)
         Same brand wrong model → continue (max relevance 1)
         No compatibility info → continue (max relevance 1)
   NO  → continue

4. Does the query specify other constraints (skin type, texture, ingredient, durability)?
   YES → Are constraints satisfied?
         Explicitly satisfied   → max relevance 3
         Unclear                → max relevance 2
         Contradicted           → max relevance 0 or 1
   NO  → continue

5. Is the product a strong intent/persona/occasion match?
   Strong fit               → relevance 3
   Reasonable alternative   → relevance 2
   Weakly related           → relevance 1
```

### 5.3 Pooling Workflow

Because complete relevance judgments are unknown, use pooled judging:

1. Run `title_only`, `vector_only`, `bm25_only`, `hybrid_union`, and `hybrid_no_cold_boost`.
2. Save top 20 candidates per variant.
3. Deduplicate by `(query_id, item_id)`.
4. Export `judgment_pool.csv`.
5. Manually assign `relevance`, `reason`, and optional labels.
6. Convert accepted labels to `retrieval_judgments_seed.json`.

Expected pool size estimate:

```text
50 queries × 5 variants × 20 results = 5,000 raw pairs
After dedup by (query_id, item_id):  ~800–1,200 unique pairs
  (overlap is high because hybrid_union shares results with vector_only and bm25_only)

Labeling time estimate:
  ~1,000 pairs × 30 seconds/pair = ~8 hours
  → Split across 2 sessions or 2 labelers
```

Generated pool path:

```text
.runtime/evaluation/<run_id>/judgment_pool.csv
```

Pool columns:

```text
query_id,raw_query,slices,variant,rank,item_id,title,brand,category_id,price_vnd,price_bucket,matched_intent,matched_fact,score,channels,relevance,reason,labels
```

## 6. Metrics Specification

### Denominator-Zero Metric Rule

If a metric denominator is zero, report the metric as `null` / `N/A`, not `0`.

Affected examples:

- `ColdShareOfRelevant@K` when there are no relevant results in top K.
- `Recall@K` when the query has no known relevant judgments.
- `NDCG@K` when `IDCG@K = 0`.
- `result_judgment_coverage_rate` when no results are returned.
- Slice-level metrics when the slice has no judged queries.

Reports may show `0` only when the metric is mathematically defined and the numerator is zero.

### Aggregating Null Metrics

For aggregate metrics:

```text
macro_metric = average(non_null_per_query_values)
```

Rules:

- Ignore `null` / `N/A` per-query values when computing macro averages.
- Report `valid_metric_count`.
- Report `null_metric_count`.
- If `valid_metric_count = 0`, the aggregate metric is `null` / `N/A`.
- Do not silently coerce `null` to `0`.

Example output fields:

```text
ndcg_at_10_macro
ndcg_at_10_valid_count
ndcg_at_10_null_count
```

### 6.1 Layer 1 Metrics

Diagnostic metrics:

- `language_detection_pass_rate`
- `price_filter_pass_rate`
- `fixture_validity_rate`
- `known_risk_count`
- `expected_unsupported_count`
- `unexpected_failure_count`

Layer 1 should produce failure rows with:

```text
probe_id,probe_type,raw_query,expected,actual,status,next_file_to_inspect,next_function_to_inspect
```

### 6.2 Layer 2 Metrics

Compute at the `RunConfig.k_values` values. Default: `K = 1, 3, 5, 10`.

Binary relevance uses `RunConfig.relevance_threshold`. Default: `relevance >= 2`.

Reports must print:

```text
k_values
relevance_threshold
```

Per query and variant:

- `result_count`
- `judged_result_count`
- `unjudged_result_count`
- `precision_at_k`
- `recall_at_k`
- `hit_rate_at_k`
- `mrr_at_k`
- `dcg_at_k`
- `idcg_at_k`
- `ndcg_at_k`
- `cold_relevant_rate_at_k`
- `cold_share_of_relevant_at_k`
- `raw_cold_coverage_at_k`

Aggregate:

- Macro average by variant.
- Macro average by query slice.
- Per-query delta against `title_only`.
- Per-query delta between `hybrid_union` and each ablation.
- Empty result count.
- Failure count.

Primary decision table:

```text
variant | NDCG@10 | Recall@10 | MRR@10 | Precision@5 | HitRate@10 | ColdRelevantRate@10 | empty_results | failures
```

#### Slice-level Reporting Rules

Each query slice must report:

- `slice_query_count`
- `slice_judged_query_count`
- `slice_positive_judged_query_count`
- `slice_confidence`

Rules:

```text
If slice_judged_query_count < 5:
  slice_confidence = "low"
  mark slice metrics as "directional_only"
```

```text
If slice_judged_query_count >= 5 and < 15:
  slice_confidence = "medium"
```

```text
If slice_judged_query_count >= 15:
  slice_confidence = "high"
```

Do not make strong claims from low-confidence slices.

#### Metric Confidence

Every aggregate and slice-level metric table must include `metric_confidence`.

Overall confidence:

```text
high    = judged_query_count >= 30
medium  = judged_query_count >= 15 and < 30
low     = judged_query_count < 15
```

Slice confidence:

```text
high    = slice_judged_query_count >= 15
medium  = slice_judged_query_count >= 5 and < 15
low     = slice_judged_query_count < 5
```

Low-confidence metrics may be displayed but must not be used for strong claims.

### 6.3 Layer 3 Metrics

Business/demo metrics:

- `zero_result_rate`
- `p50_total_latency_ms`
- `p95_total_latency_ms`
- `p95_query_processing_latency_ms`
- `p95_search_latency_ms`
- `vietnamese_failure_rate`
- `vietnamese_no_diacritic_failure_rate`
- `price_filter_failure_rate`
- `channel_vector_only_rate`
- `channel_bm25_only_rate`
- `channel_both_rate`
- `explanation_coverage`
- `cold_start_hit_rate_at_10`
- `cold_start_window_seconds_at_10` only when timestamp data exists

Latency measurement should use `time.perf_counter()` around:

1. fixture generation
2. MongoDB search
3. full per-query execution

Do not mix first-run model download time into normal latency claims. If first-run download happens, mark the run as `warm_cache=false`.

#### Latency Sample-size Guardrail

P95 latency should not be used as a headline performance claim when the sample is too small.

Rules:

```text
If latency_sample_count < 20:
  latency_confidence = "low"
  mark P95 latency as "directional_only"
```

```text
If latency_sample_count >= 20 and < 50:
  latency_confidence = "medium"
```

```text
If latency_sample_count >= 50:
  latency_confidence = "high"
```

Low-confidence latency metrics may be displayed, but they must not be used as headline performance claims.

## 7. Variant Implementation Design

### 7.1 Required Variants

`hybrid_union`

- Uses existing `run_search(fixture, mode="unionWith")`.
- This is the main system.

`vector_only`

- Uses `vector_subpipeline()` plus item lookup/projection.
- Searches only `unit_type = hype_question`.

`bm25_only`

- Uses `bm25_subpipeline()` plus item lookup/projection.
- Searches only `unit_type = proposition`.

`title_only`

- Evaluation-only weak baseline that bypasses retrieval units entirely.
- Queries the `items` collection directly with `$match` regex on `title_en` and `brand`.
- Does NOT use Atlas Search `$search` because `atlas_search_compound()` already searches `item_title_en` and `item_brand` through `retrieval_units` — using the same Atlas Search index would make `title_only` overlap with the BM25 channel rather than being a genuinely weaker baseline.
- If the `items` collection is unavailable or the regex pipeline fails, mark as `variant_unavailable` with a recoverable failure.
- Do not fail the full evaluation only because `title_only` is unavailable.

Implementation:

```python
def title_only_pipeline(
    bm25_search_query_en: str,
    hard_filters: dict[str, Any] | None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Weak baseline: regex keyword match on items.title_en + items.brand.

    This searches the items collection directly, NOT retrieval_units.
    It does not use Atlas Search, $vectorSearch, or any retrieval unit.
    """
    filters = normalize_hard_filters(hard_filters)
    tokens = [t for t in bm25_search_query_en.split() if len(t) > 1]
    if not tokens:
        return []
    regex_pattern = "|".join(re.escape(t) for t in tokens)

    match_stage: dict[str, Any] = {
        "$match": {
            "$or": [
                {"title_en": {"$regex": regex_pattern, "$options": "i"}},
                {"brand": {"$regex": regex_pattern, "$options": "i"}},
            ],
            "in_stock": filters.get("in_stock", True),
        }
    }

    # Apply price filters if present
    if filters.get("max_price_vnd") is not None:
        match_stage["$match"]["price_vnd"] = {"$lte": int(filters["max_price_vnd"])}
    if filters.get("min_price_vnd") is not None:
        match_stage["$match"].setdefault("price_vnd", {})
        match_stage["$match"]["price_vnd"]["$gte"] = int(filters["min_price_vnd"])

    return [
        match_stage,
        {"$addFields": {
            "match_score": {
                "$size": {
                    "$regexFindAll": {
                        "input": {"$toLower": "$title_en"},
                        "regex": regex_pattern,  # "term1|term2|term3" — same as $match
                    }
                }
            },
        }},
        {"$sort": {"match_score": -1, "price_vnd": 1}},
        {"$limit": top_k},
        {"$project": {
            "_id": 0,
            "item_id": "$_id",
            "title": "$title_en",
            "brand": 1,
            "category_id": 1,
            "price_vnd": 1,
            "price_bucket": 1,
            "is_cold_item": "$cold_start.is_cold_item",
            "score": "$match_score",
            "matched_intent": "",
            "matched_fact": "",
            "rank_vector": None,
            "rank_bm25": None,
            "fusion_score": 0,
            "debug": {
                "matched_channels": [],
                "variant": "title_only",
            },
        }},
    ]
```

Run against the `items` collection (not `retrieval_units`):

```python
def run_title_only(fixture: dict, top_k: int, items_collection) -> list[dict]:
    pipeline = title_only_pipeline(
        bm25_search_query_en=fixture["bm25_search_query_en"],
        hard_filters=fixture.get("hard_filters"),
        top_k=top_k,
    )
    return list(items_collection.aggregate(pipeline))
```

Why this design matters:

```text
bm25_only:    Atlas Search $search on retrieval_units (item_title_en + item_brand + text_search + ...)
title_only:   Simple $match regex on items.title_en + items.brand

If title_only used Atlas Search on the same fields as bm25_only,
it would not be a weaker baseline — it would be a slightly different
version of the same channel. The regex approach creates a genuinely
weak catalog-search baseline that the hybrid system must clearly beat.
```

`hybrid_no_cold_boost`

- Evaluation-only ablation.
- Same as `hybrid_union`, but score should exclude `COLD_START_BOOST`.
- Do not mutate global constants in `src/search_pipeline.py` at runtime.
- Prefer a parameterized scoring-stage builder if it is a low-risk change.
- If parameterization would require broad refactoring, use an evaluation-only ablation builder, but keep it small and document exactly which scoring stage differs.

#### Ablation Implementation Guardrail

Ablation variants must not mutate global constants such as `COLD_START_BOOST`.

Prefer a parameterized scoring-stage builder:

```python
def build_post_fusion_stages(
    *,
    include_cold_boost: bool = True,
    include_content_bonus: bool = True,
    include_multi_channel_bonus: bool = True,
) -> list[dict]:
    ...
```

Variant settings:

```text
hybrid_union:
  include_cold_boost=True
  include_content_bonus=True
  include_multi_channel_bonus=True

hybrid_no_cold_boost:
  include_cold_boost=False
  include_content_bonus=True
  include_multi_channel_bonus=True
```

Evaluation variants should call the same pipeline builders as production wherever practical and only change explicit scoring flags. Avoid copying the full production pipeline into evaluation code unless no reusable builder exists.

### 7.2 Optional Variants

Add only after required variants work:

- `hybrid_no_content_bonus`
- `hybrid_vector_heavy`
- `hybrid_bm25_heavy`
- `rank_fusion`

Optional variants should be gated by CLI args and documented as experimental.

## 8. Proposed File Structure

Create:

```text
evaluation/
  README.md
  queries/
    diagnostic_probes.json
    retrieval_queries_seed.json
  judgments/
    retrieval_judgments_seed.json

src/evaluation/
  __init__.py
  contracts.py
  dataset.py
  diagnostics.py
  metrics.py
  variants.py
  runner.py
  reporting.py

scripts/
  run_eval_diagnostics.py
  build_eval_pool.py
  run_evaluation.py
  summarize_evaluation.py

tests/
  test_evaluation_dataset.py
  test_evaluation_diagnostics.py
  test_evaluation_guardrails.py
  test_evaluation_metrics.py
  test_evaluation_runner.py
  test_evaluation_variants.py
```

Generated outputs:

```text
.runtime/evaluation/<run_id>/
  config.json
  query_fixtures.json
  failures.json
  layer1_diagnostics.json
  layer1_diagnostics.csv
  layer1_summary.md
  judgment_pool.csv
  layer2_raw_results.json
  layer2_normalized_results.csv
  layer2_metrics_by_query.csv
  layer2_metrics_summary.json
  layer2_variant_comparison.md
  layer3_demo_readiness.json
  layer3_demo_readiness.md
  latency_by_query.csv
  failure_slices.csv
  metrics_summary.md
```

Use `.runtime/evaluation/` because `.runtime/` is already ignored.

## 9. Implementation Tasks

### Import Safety

Importing any `src/evaluation/*` module must not:

- connect to MongoDB
- start Ollama
- load embedding models
- read `.env`
- run queries
- write files

All side effects must happen inside explicit CLI entrypoints or runner functions.

Add test:

```python
def test_evaluation_modules_are_import_safe():
    ...
```

### Task 1: Add Evaluation Contracts

**Files:**

- Create: `src/evaluation/__init__.py`
- Create: `src/evaluation/contracts.py`
- Test: `tests/test_evaluation_dataset.py`

- [x] Step 1: Define dataclasses.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiagnosticProbe:
    probe_id: str
    raw_query: str
    probe_type: str
    expected_language: str = ""
    expected_filters: dict[str, Any] = field(default_factory=dict)
    expected_status: str = "pass"
    notes: str = ""


@dataclass(frozen=True)
class EvaluationQuery:
    query_id: str
    raw_query: str
    language: str
    topic: str
    intent_tags: list[str] = field(default_factory=list)
    expected_filters: dict[str, Any] = field(default_factory=dict)
    slices: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class RelevanceJudgment:
    query_id: str
    item_id: str
    relevance: int
    reason: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluationResult:
    query_id: str
    variant: str
    rank: int
    item_id: str
    score: float
    title: str = ""
    brand: str = ""
    category_id: str = ""
    price_vnd: int | None = None
    price_bucket: str = ""
    matched_intent: str = ""
    matched_fact: str = ""
    channels: list[str] = field(default_factory=list)
    is_cold_item: bool | None = None
    result_status: str = "ok"
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FailureRecord:
    stage: str
    error_type: str
    error: str
    recoverable: bool
    query_id: str = ""
    variant: str = ""
    next_file_to_inspect: str = ""
    next_function_to_inspect: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimStatus:
    claim: str
    status: str
    evidence: str = ""
    blocker: str = ""


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    queries_path: str
    judgments_path: str = ""
    output_dir: str = ""
    variants: list[str] = field(default_factory=list)
    top_k: int = 10
    k_values: list[int] = field(default_factory=lambda: [1, 3, 5, 10])
    relevance_threshold: int = 2
    use_cached_fixtures: bool = True
    warm_cache: bool | None = None
    mongodb_live: bool | None = None
    created_at: str = ""
    git_commit: str = ""
    plan_version: str = ""
    code_version: str = ""
    python_version: str = ""
    platform: str = ""


@dataclass(frozen=True)
class MetricGateResult:
    gate_name: str
    passed: bool
    status: str
    evidence: str = ""
    blocker: str = ""
```

- [x] Step 2: Validate contracts during loading.

Rules:

- ids and `raw_query` must be non-empty.
- `language` must be `en`, `vi`, or `mixed`.
- `relevance` must be one of `0`, `1`, `2`, `3`.
- `expected_status` must be one of `pass`, `fail`, `known_risk`, `expected_unsupported`, `skipped_dependency_missing`, or `error`.
- `EvaluationResult.result_status` must be one of `ok`, `ok_empty`, `failed`, or `skipped`.
- `ClaimStatus.status` must be one of `supported`, `unsupported`, or `needs_more_evidence`.
- `FailureRecord.error_type` must be in the allowed error taxonomy.
- Use `FailureRecord.details` for structured metadata. Keep `error` human-readable and concise.
- `RunConfig.top_k` must be positive.
- `RunConfig.k_values` must not be empty.
- all `RunConfig.k_values` must be positive.
- `RunConfig.top_k` must be greater than or equal to `max(k_values)`.
- `RunConfig.relevance_threshold` must be one of `1`, `2`, or `3`.
- duplicate `query_id`, `probe_id`, and `(query_id, item_id)` should fail.

### Task 2: Add Query, Probe, And Judgment Files

**Files:**

- Create: `evaluation/README.md`
- Create: `evaluation/queries/diagnostic_probes.json`
- Create: `evaluation/queries/retrieval_queries_seed.json`
- Create: `evaluation/judgments/retrieval_judgments_seed.json`
- Test: `tests/test_evaluation_dataset.py`

- [x] Step 1: Add 15-25 diagnostic probes.

Required probe groups:

- English language detection.
- Vietnamese with diacritics.
- Vietnamese without diacritics.
- English price max.
- Vietnamese price max.
- Price range.
- Unsupported negation.
- Empty/invalid query behavior.

- [x] Step 2: Add 40-60 retrieval queries.

Required slices:

- `english`
- `vietnamese`
- `vietnamese_no_diacritic`
- `price_filter`
- `beauty`
- `electronics`
- `compatibility`
- `persona`
- `occasion`
- `problem`
- `constraint`
- `gift`

- [x] Step 3: Create initial judgment file as:

```json
[]
```

Metrics must refuse to claim retrieval quality when judgment coverage is zero.

### Task 3: Implement Dataset Loading

**Files:**

- Create: `src/evaluation/dataset.py`
- Modify: `tests/test_evaluation_dataset.py`

- [x] Step 1: Add functions.

```python
def load_diagnostic_probes(path: str | Path) -> list[DiagnosticProbe]:
    ...


def load_eval_queries(path: str | Path) -> list[EvaluationQuery]:
    ...


def load_relevance_judgments(path: str | Path) -> list[RelevanceJudgment]:
    ...


def judgments_by_query(judgments: list[RelevanceJudgment]) -> dict[str, dict[str, int]]:
    ...
```

- [x] Step 2: Add tests for valid files, duplicate ids, invalid relevance, and empty judgments.

Run:

```bash
python -m pytest tests/test_evaluation_dataset.py -v
```

Expected: all dataset tests pass without MongoDB/Ollama/BGE-M3.

### Task 4: Implement Layer 1 Diagnostics

**Files:**

- Create: `src/evaluation/diagnostics.py`
- Create: `scripts/run_eval_diagnostics.py`
- Create: `tests/test_evaluation_diagnostics.py`

- [x] Step 1: Implement offline probe checks.

Required functions:

```python
def run_language_probe(probe: DiagnosticProbe) -> dict:
    ...


def run_price_filter_probe(probe: DiagnosticProbe) -> dict:
    ...


def run_diagnostic_probes(probes: list[DiagnosticProbe]) -> list[dict]:
    ...
```

- [x] Step 2: Mark unsupported probes explicitly.

For `probe_type = "negation"`, return:

```json
{
  "status": "expected_unsupported",
  "next_file_to_inspect": "src/query_processor.py",
  "next_function_to_inspect": "extract_hard_filters"
}
```

- [x] Step 3: Add CLI.

Command:

```bash
python scripts/run_eval_diagnostics.py \
  --probes evaluation/queries/diagnostic_probes.json \
  --out .runtime/evaluation/diagnostics_seed
```

Expected outputs:

- `layer1_diagnostics.csv`
- `layer1_diagnostics.json`
- `layer1_summary.md`
- `manifest.json`

### Task 5: Implement Metrics

**Files:**

- Create: `src/evaluation/metrics.py`
- Create: `tests/test_evaluation_metrics.py`

- [x] Step 1: Implement deterministic IR metrics.

Required functions:

```python
def binary_relevant(relevance: int, threshold: int = 2) -> bool:
    ...


def dcg(relevances: list[int]) -> float:
    ...


def compute_query_metrics(
    ranked_results: list[EvaluationResult],
    judgments: dict[str, int],
    k_values: list[int],
    relevance_threshold: int = 2,
) -> dict[str, float | int | bool]:
    ...


def aggregate_metrics(rows: list[dict[str, object]], group_by: list[str]) -> list[dict[str, object]]:
    ...
```

- [x] Step 2: Include cold-start relevance metrics.

For each `K`, compute:

- `cold_relevant_rate_at_k`
- `cold_share_of_relevant_at_k`
- `raw_cold_coverage_at_k`

Only the first two are quality metrics. `raw_cold_coverage_at_k` is diagnostic and must not be used as the headline cold-start quality metric.

If `EvaluationResult.is_cold_item is None`, exclude that result from cold-start numerators and report `unknown_cold_status_count`.

- [x] Step 3: Add tests for unjudged results.

Policy:

- Unjudged items count as not relevant for primary metrics.
- Report `judged_result_count` and `unjudged_result_count`.
- Mark `has_judgments = False` when no judgments exist for a query.

Run:

```bash
python -m pytest tests/test_evaluation_metrics.py -v
```

### Task 6: Implement Evaluation Variants

**Files:**

- Create: `src/evaluation/variants.py`
- Create: `tests/test_evaluation_variants.py`

- [x] Step 1: Define required variants.

```python
EVALUATION_VARIANTS = (
    "title_only",
    "vector_only",
    "bm25_only",
    "hybrid_union",
    "hybrid_no_cold_boost",
)
```

- [x] Step 2: Implement runner boundary.

```python
def run_variant(
    fixture: dict[str, object],
    variant: str,
    top_k: int,
    collection: object | None = None,
) -> list[dict]:
    ...
```

- [x] Step 3: Keep evaluation variants isolated.

Do not change production defaults in `src/search_pipeline.py`.

The first implementation pass must not modify:

- `src/search_pipeline.py::run_search` default behavior
- `hybrid_union` scoring
- `COLD_START_BOOST`
- existing MongoDB aggregation defaults used by demos

If `hybrid_no_cold_boost` cannot be implemented safely without touching production scoring, return a recoverable `variant_unavailable` failure for that variant.

- [x] Step 4: Test with mock collections.

Tests should verify:

- Unknown variant raises `ValueError`.
- `hybrid_union` uses `$unionWith`.
- `vector_only` starts with `$vectorSearch`.
- `bm25_only` starts with `$search`.
- `title_only` either builds a title/brand search pipeline or returns a recoverable `variant_unavailable` failure when current Atlas indexes do not support title/brand search.
- `hybrid_no_cold_boost` excludes the cold boost contribution.

### Task 7: Implement Runner And Fixture Cache

**Files:**

- Create: `src/evaluation/runner.py`
- Create: `tests/test_evaluation_runner.py`

- [x] Step 1: Implement fixture generation boundary.

```python
def build_query_fixture(query: EvaluationQuery) -> dict:
    ...


def load_or_build_fixtures(
    queries: list[EvaluationQuery],
    fixture_path: str | Path,
    use_cache: bool,
) -> tuple[dict[str, dict], list[dict]]:
    ...
```

#### Query Fixture Schema Versioning

Cached fixture files must include:

```text
fixture_schema_version
created_at
source_query_file
query_processor_version
fixtures
```

If `fixture_schema_version` does not match the current expected version, the runner must rebuild fixtures unless `--allow-stale-fixtures` is explicitly set.

Default behavior:

```text
--allow-stale-fixtures false
```

Default behavior is to reject stale fixture cache rather than silently using it.

- [x] Step 2: Measure latency separately.

Record:

- `query_processing_latency_ms`
- `search_latency_ms`
- `total_latency_ms`

- [x] Step 3: Record failures without stopping the full run.

Failure stages:

- `diagnostic`
- `fixture_generation`
- `search`
- `metrics`
- `reporting`

Every failure row must include:

- `stage`
- `error_type`
- `error`
- `recoverable`
- `next_file_to_inspect`
- `next_function_to_inspect`
- `details`

Use `details` for structured metadata such as dependency name, index name, exception class, collection name, variant, stage duration, or pipeline stage. Keep `error` human-readable and concise.

Allowed `error_type` values:

```text
invalid_input_file
invalid_query
invalid_judgment
duplicate_id
stale_fixture_schema
diagnostic_failed
fixture_generation_failed
language_detection_failed
translation_failed
embedding_failed
mongodb_connection_failed
mongodb_write_attempted
vector_index_unavailable
text_index_unavailable
aggregation_failed
variant_unavailable
empty_results
normalization_failed
metrics_failed
reporting_failed
import_side_effect
dependency_missing
unknown_error
```

Normal empty results should be represented as an outcome, not an infrastructure failure.

Use `result_status`:

```text
ok        = query ran and returned one or more results
ok_empty  = query ran successfully but returned zero results
failed    = query could not run successfully
skipped   = query or variant was intentionally skipped
```

Use `error_type = "empty_results"` only when empty results are caused by an actual failure or invalid pipeline behavior.

For normal empty retrieval results, record:

```json
{
  "query_id": "q012",
  "variant": "hybrid_union",
  "result_status": "ok_empty",
  "result_count": 0
}
```

Do not count normal `ok_empty` outcomes as infrastructure failures.

Failure shape:

```json
{
  "query_id": "q005",
  "variant": "hybrid_union",
  "stage": "search",
  "error_type": "aggregation_failed",
  "error": "MongoDB aggregation failed during unionWith search: ...",
  "recoverable": true,
  "next_file_to_inspect": "src/search_pipeline.py",
  "next_function_to_inspect": "run_search",
  "details": {
    "collection": "retrieval_units",
    "exception_class": "OperationFailure"
  }
}
```

Reports must aggregate failures by `error_type`.

### Task 8: Implement Pool Builder

**Files:**

- Create: `scripts/build_eval_pool.py`
- Modify: `src/evaluation/runner.py`
- Modify: `src/evaluation/reporting.py`
- Test: `tests/test_evaluation_runner.py`

- [x] Step 1: Add CLI.

```bash
python scripts/build_eval_pool.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --out .runtime/evaluation/pool_seed \
  --top-k 20 \
  --variants title_only vector_only bm25_only hybrid_union hybrid_no_cold_boost
```

- [x] Step 2: Write `judgment_pool.csv`.

Columns:

```text
query_id,raw_query,slices,variant,rank,item_id,title,brand,category_id,price_vnd,price_bucket,matched_intent,matched_fact,score,channels,relevance,reason,labels
```

- [x] Step 3: Write `failures.json` and `manifest.json`.

`manifest.json` must list `judgment_pool.csv` and `failures.json`.

- [x] Step 4: Print labeling instructions at the end.

Expected message:

```text
Judgment pool written to .runtime/evaluation/pool_seed/judgment_pool.csv
Fill relevance, reason, and labels columns. Then convert judged rows into evaluation/judgments/retrieval_judgments_seed.json.
```

### Task 9: Implement Full Evaluation CLI

**Files:**

- Create: `scripts/run_evaluation.py`
- Modify: `src/evaluation/runner.py`
- Modify: `src/evaluation/reporting.py`
- Test: `tests/test_evaluation_runner.py`

- [x] Step 1: Add CLI.

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/eval_seed \
  --top-k 10 \
  --k-values 1 3 5 10 \
  --relevance-threshold 2 \
  --variants title_only vector_only bm25_only hybrid_union hybrid_no_cold_boost
```

- [x] Step 2: Write all layer outputs.

Required outputs:

- `config.json`
- `query_fixtures.json`
- `failures.json`
- `layer2_raw_results.json`
- `layer2_normalized_results.csv`
- `layer2_metrics_by_query.csv`
- `layer2_metrics_summary.json`
- `layer2_variant_comparison.md`
- `layer3_demo_readiness.json`
- `layer3_demo_readiness.md`
- `latency_by_query.csv`
- `failure_slices.csv`
- `metrics_summary.md`
- `manifest.json`

Manifest shape:

```json
{
  "run_id": "eval_seed",
  "created_at": "...",
  "config_path": "config.json",
  "artifacts": [
    {
      "path": "layer2_metrics_summary.json",
      "type": "metrics_summary",
      "required": true
    },
    {
      "path": "metrics_summary.md",
      "type": "markdown_report",
      "required": true
    }
  ],
  "failures_path": "failures.json"
}
```

- [x] Step 3: Exit behavior.

Exit `0` when evaluation completed with recorded failures.

Exit `1` when:

- input files are invalid
- no query can be evaluated
- requested variants are invalid

All evaluation CLIs must:

- expose `--help`
- validate all input paths before running
- create the output directory if it does not exist
- write `config.json`
- include `run_id`, `created_at`, `git_commit`, `plan_version`, `code_version`, `k_values`, and `relevance_threshold` in `config.json` when available
- write `failures.json` even when there are no failures
- write `manifest.json` before exiting successfully
- print final artifact paths
- exit `1` for invalid input files
- exit `1` for invalid variants
- exit `1` when no query can be evaluated
- exit `0` when the run completes with recoverable recorded failures

- [x] Step 4: Add offline smoke-test mode.

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/smoke \
  --top-k 10 \
  --k-values 1 3 5 10 \
  --relevance-threshold 2 \
  --variants title_only vector_only bm25_only hybrid_union \
  --use-fake-results
```

Expected:

- no MongoDB required
- no Ollama required
- no BGE-M3 required
- `metrics_summary.md` is generated
- `failures.json` is generated
- `manifest.json` is generated

### Task 10: Implement Reporting

**Files:**

- Create: `src/evaluation/reporting.py`
- Create: `scripts/summarize_evaluation.py`
- Test: `tests/test_evaluation_runner.py`

- [x] Step 1: Generate the main Markdown report.

`metrics_summary.md` should include:

- Executive summary.
- Layer 1 diagnostic summary if diagnostics were run.
- Layer 2 variant comparison.
- Layer 2 slice analysis.
- Layer 3 demo/business readiness.
- Judgment coverage gates and metric confidence.
- Run configuration, including `k_values`, `relevance_threshold`, `created_at`, and `git_commit` when available.
- Variant Availability table.
- Worst 10 queries by `NDCG@10`.
- Empty-result queries.
- Vietnamese failure table.
- Price-filter failure table.
- Channel coverage table.
- Failure summary grouped by `error_type`.
- Claim status table.
- Recommended next fixes mapped to files/functions.

- [x] Step 2: Add automatic recommendations.

Rules:

- If `title_only` is close to `hybrid_union`, inspect HyPE/proposition generation quality.
- If `vector_only` beats `hybrid_union`, inspect BM25 noise in `atlas_search_compound()`.
- If `bm25_only` beats `hybrid_union`, inspect HyPE quality and `build_contextual_header()`.
- If `hybrid_no_cold_boost` beats `hybrid_union`, inspect `COLD_START_BOOST`.
- If Vietnamese no-diacritic slice underperforms, inspect `detect_language()`.
- If price-filter slice underperforms, inspect `extract_hard_filters()` and `item_match_stage()`.

- [x] Step 3: Include mandatory report tables.

`metrics_summary.md` must include:

Variant Availability:

```text
variant | availability | reason | recoverable | included_in_comparison
```

Allowed availability values:

```text
available
unavailable
failed
skipped
```

If `title_only` is unavailable, the report must not claim hybrid beats title baseline. That claim should be `needs_more_evidence`.

Main Variant Comparison:

```text
variant | judged_queries | metric_confidence | NDCG@10 | Recall@10 | MRR@10 | Precision@5 | HitRate@10 | ColdRelevantRate@10 | empty_results | failures
```

Query Slice Comparison:

```text
slice | judged_queries | confidence | best_variant | hybrid_NDCG@10 | vector_NDCG@10 | bm25_NDCG@10 | title_NDCG@10 | main_failure_pattern
```

Ablation Impact:

```text
comparison | delta_NDCG@10 | delta_MRR@10 | delta_ColdRelevantRate@10 | interpretation
```

Failure Summary:

```text
error_type | count | affected_queries | affected_variants | next_file_to_inspect | next_function_to_inspect
```

Claim Status:

```text
claim | status | evidence | blocker
```

Allowed claim statuses:

```text
supported
unsupported
needs_more_evidence
```

- [x] Step 4: Add deterministic claim status rules.

The report must generate Claim Status rows using explicit gates, not free-form judgment.

Required claims:

1. Hybrid beats title baseline.
2. Hybrid beats single-channel baselines.
3. Cold-start retrieval is useful.
4. Cold-start window was measured.
5. Vietnamese robustness.
6. Live end-to-end latency.

Example rules:

```text
Hybrid beats title baseline is supported only if:
  - judgment gates pass
  - title_only is available
  - hybrid_union beats title_only on NDCG@10, Recall@10, and MRR@10
```

If `title_only` is unavailable, Hybrid beats title baseline must be `needs_more_evidence`, not `supported`.

```text
Cold-start window was measured is supported only if:
  - indexed_at exists
  - first_seen_in_top_k_at exists
  - ColdStartWindowSeconds@K was computed from those timestamps
```

```text
Live end-to-end latency is supported only if:
  - used_cached_fixtures = false
  - model_download_observed = false
  - mongodb_live = true
  - latency_sample_count >= 20
```

Suggested function boundary:

```python
def decide_claim_status(metrics: dict, gates: dict) -> list[ClaimStatus]:
    ...
```

- [x] Step 5: Add claim guardrails.

The final report must include:

- Supported Claims
- Unsupported Claims
- Claims Requiring More Evidence

Unsupported claims must include any claim blocked by insufficient data, missing timestamps, missing live dependencies, or low judgment coverage.

Examples:

```text
Do not claim ColdStartWindowSeconds@K unless indexed_at and first_seen_in_top_k_at were measured.
```

```text
Do not claim hybrid superiority unless judgment coverage gates pass.
```

```text
Do not claim Vietnamese robustness unless the Vietnamese slice has enough judged queries.
```

```text
Do not claim live end-to-end latency if cached query fixtures were used.
```

### Task 11: Add Offline Tests

**Files:**

- Modify: `tests/test_evaluation_dataset.py`
- Modify: `tests/test_evaluation_diagnostics.py`
- Create: `tests/test_evaluation_guardrails.py`
- Modify: `tests/test_evaluation_metrics.py`
- Modify: `tests/test_evaluation_runner.py`
- Modify: `tests/test_evaluation_variants.py`

- [x] Step 1: Run evaluation tests.

```bash
python -m pytest tests/test_evaluation_dataset.py tests/test_evaluation_diagnostics.py tests/test_evaluation_metrics.py tests/test_evaluation_runner.py tests/test_evaluation_variants.py -v
```

Expected: all pass without MongoDB, Ollama, or BGE-M3.

- [x] Step 2: Run guardrail tests.

```bash
python -m pytest tests/test_evaluation_guardrails.py -v
```

Required cases:

- `test_cold_start_metric_names_are_distinct`
- `test_cold_start_window_requires_timestamps`
- `test_query_and_result_judgment_coverage_are_separate`
- `test_positive_judged_query_count_is_query_level`
- `test_denominator_zero_metrics_return_none`
- `test_ok_empty_not_counted_as_infrastructure_failure`
- `test_judgment_coverage_blocks_claims`
- `test_low_count_slice_is_directional_only`
- `test_expected_unsupported_not_counted_as_failure`
- `test_failure_error_type_required`
- `test_failure_record_requires_error_type`
- `test_failure_record_supports_details`
- `test_claim_status_only_allows_known_statuses`
- `test_title_only_unavailable_is_recoverable`
- `test_variant_unavailable_blocks_hybrid_beats_title_claim`
- `test_hybrid_no_cold_boost_does_not_mutate_global_constant`
- `test_low_latency_sample_marks_p95_directional_only`
- `test_claim_status_requires_judgment_gates`
- `test_latency_claim_blocked_when_cached_fixtures_used`
- `test_report_contains_claim_status_table`
- `test_is_cold_item_unknown_does_not_count_as_cold`
- `test_run_config_records_reproducibility_fields`
- `test_macro_average_ignores_null_metrics_and_reports_counts`
- `test_evaluation_runner_never_calls_write_methods`
- `test_stale_fixture_schema_is_rejected_by_default`
- `test_manifest_is_written_for_successful_run`
- `test_evaluation_modules_are_import_safe`
- `test_metric_config_is_taken_from_run_config`

Expected: all pass without MongoDB, Ollama, or BGE-M3.

Read-only guardrail tests should use a fake MongoDB collection whose write methods raise immediately. Evaluation code must never call `insert_one`, `insert_many`, `update_one`, `update_many`, `replace_one`, `delete_one`, `delete_many`, `bulk_write`, `create_index`, or `drop_index`.

- [x] Step 3: Run related existing tests.

```bash
python -m pytest tests/test_pipeline.py tests/test_validation.py tests/test_llm_client.py -v
```

Expected: all pass.

- [x] Step 4: Run full suite only after implementation is complete.

```bash
python -m pytest tests/ -v
```

Expected: all pass. If any live-service tests are added later, they must be opt-in.

### Task 12: Update Documentation

**Files:**

- Modify: `TESTING.md`
- Modify: `RUNBOOK.md`
- Create or update: `evaluation/README.md`

- [x] Step 1: Document the three-layer evaluation model.

Include:

- Layer 1 diagnostics.
- Layer 2 retrieval quality.
- Layer 3 demo/business readiness.

- [x] Step 2: Document commands.

Commands:

```bash
python scripts/run_eval_diagnostics.py --help
python scripts/build_eval_pool.py --help
python scripts/run_evaluation.py --help
python scripts/summarize_evaluation.py --help
```

- [x] Step 3: Document safety.

State:

- Evaluation is read-only against MongoDB.
- Evaluation tests enforce read-only behavior with fake collections.
- Query fixture generation may call Ollama and BGE-M3.
- Cached query fixtures have a schema version and stale fixtures are rejected by default.
- Generated outputs go under `.runtime/evaluation/`.
- Successful runs write `manifest.json`.
- Smoke mode can run with `--use-fake-results` without live services.
- Empty judgment files cannot support retrieval-quality claims.

## 10. Manual Operating Procedure

### Step 1: Run Offline Diagnostics

```bash
python scripts/run_eval_diagnostics.py \
  --probes evaluation/queries/diagnostic_probes.json \
  --out .runtime/evaluation/diagnostics_seed
```

Expected:

- `layer1_summary.md`
- `layer1_diagnostics.csv`
- `manifest.json`

### Step 2: Build Judgment Pool

```bash
python scripts/build_eval_pool.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --out .runtime/evaluation/pool_seed \
  --top-k 20 \
  --variants title_only vector_only bm25_only hybrid_union hybrid_no_cold_boost
```

Expected:

- `judgment_pool.csv`
- `failures.json`
- `manifest.json`

### Step 3: Label Candidates

Open:

```text
.runtime/evaluation/pool_seed/judgment_pool.csv
```

Fill:

- `relevance`: `0`, `1`, `2`, or `3`
- `reason`: concise explanation
- `labels`: optional comma-separated tags

### Step 3.5: Import Labeled Judgments

Run the import script to convert the CSV to JSON and validate the data contract:

```bash
python scripts/import_eval_judgments.py \
  --csv .runtime/evaluation/pool_seed/judgment_pool.csv \
  --out evaluation/judgments/retrieval_judgments_seed.json
```

Expected:

- `evaluation/judgments/retrieval_judgments_seed.json` is updated and validated.

### Step 4: Run Full Evaluation

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/eval_seed \
  --top-k 10 \
  --k-values 1 3 5 10 \
  --relevance-threshold 2 \
  --variants title_only vector_only bm25_only hybrid_union hybrid_no_cold_boost
```

Expected:

- `metrics_summary.md`
- `layer2_variant_comparison.md`
- `layer3_demo_readiness.md`
- `failures.json`
- `manifest.json`

### Step 5: Run Offline Smoke Test

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/smoke \
  --top-k 10 \
  --k-values 1 3 5 10 \
  --relevance-threshold 2 \
  --variants title_only vector_only bm25_only hybrid_union \
  --use-fake-results
```

Expected:

- `metrics_summary.md`
- `failures.json`
- `manifest.json`
- no MongoDB, Ollama, or BGE-M3 required

## 11. Demo Readiness Gates

Use these as practical gates, not scientific claims:

- At least 40 retrieval queries exist.
- At least 30 queries have judgments.
- At least 20 queries have one or more relevant judged item.
- `query_judgment_coverage_rate >= 0.50`; otherwise aggregate metrics are preliminary.
- `hybrid_union` beats `title_only` on `NDCG@10`, `Recall@10`, and `MRR@10`.
- `hybrid_union` has `HitRate@10 >= 0.70`.
- `hybrid_union` has `Precision@5 >= title_only Precision@5`.
- `hybrid_union` has `NDCG@10 >= vector_only NDCG@10` or report explains why vector-only wins.
- `hybrid_union` has `NDCG@10 >= bm25_only NDCG@10` or report explains why BM25-only wins.
- `hybrid_union` performs at least as well as `hybrid_no_cold_boost` on `NDCG@10`, or the cold boost should be revisited.
- Zero-result rate is below `15%`.
- Vietnamese and price-filter failures are listed separately.
- P95 search latency is reported separately from query-processing latency.
- Claim Status table has no unsupported headline claim.

## 12. Likely Findings And Follow-Up Fix Areas

If `title_only` is too strong:

- HyPE or proposition generation is not adding enough recall/semantic value.
- Inspect `prompts/extract_propositions.txt`.
- Inspect `prompts/generate_hype.txt`.
- Inspect `src/indexing.py::build_contextual_header`.

If `vector_only` wins:

- BM25 may be adding noisy proposition matches.
- Inspect `src/search_pipeline.py::atlas_search_compound`.
- Inspect proposition `text_search` content.

If `bm25_only` wins:

- HyPE queries may be too generic.
- Inspect `src/llm_hype.py`.
- Inspect fallback HyPE rates.
- Inspect `embedding_text` headers.

If `hybrid_no_cold_boost` wins:

- Current unconditional `COLD_START_BOOST = 0.03` may be hurting relevance.
- Inspect `src/search_pipeline.py::post_fusion_stages`.

If Vietnamese queries underperform:

- Inspect `src/query_processor.py::detect_language`.
- Inspect `src/query_processor.py::translate_to_english`.
- Separate no-diacritic Vietnamese before changing ranking.

If price-filter queries underperform:

- Inspect `src/query_processor.py::extract_hard_filters`.
- Inspect `src/search_pipeline.py::normalize_hard_filters`.
- Inspect `src/search_pipeline.py::item_match_stage`.
- Check `price_vnd` quality from USD-to-VND conversion.

If channel coverage is low:

- If mostly vector-only, BM25 proposition quality or text index mappings may be weak.
- If mostly BM25-only, HyPE generation or embeddings may be weak.
- If both channels match but relevance is low, fusion scoring likely needs tuning.

## 13. Risks And Guardrails

- Manual judgments may be inconsistent. Mitigation: require `reason`, review worst-query table, optionally add second-pass adjudication.
- Optional later improvement: after the first candidate pool is labeled, sample the worst 10 queries and highest-disagreement cases for second-pass review. This should not block MVP implementation.
- Query set may overfit demo examples. Mitigation: report metrics by slice and keep broad query coverage.
- No-diacritic Vietnamese is likely weak. Mitigation: make it a separate slice before fixing it.
- Negation is unsupported. Mitigation: mark it as `expected_unsupported` in Layer 1.
- First-run BGE-M3 download can distort latency. Mitigation: mark `warm_cache=false`.
- Empty judgments can fake progress. Mitigation: block quality claims when judgment coverage is zero.
- Live Atlas index readiness can fail evaluation. Mitigation: keep offline diagnostics and metrics separate.
- Existing `.gitignore` is already modified. Mitigation: use `.runtime/evaluation/` and avoid `.gitignore` edits.

## 14. Implementation Order

Recommended order:

1. Contracts and dataset loading.
2. Missing contracts: `FailureRecord`, `ClaimStatus`, `RunConfig`, `MetricGateResult`.
3. Import-safety tests for `src/evaluation/*`.
4. Diagnostic status model.
5. Error taxonomy, `result_status`, and `FailureRecord.details`.
6. Diagnostic probes and Layer 1 runner.
7. Metrics, including renamed cold-start metrics, denominator-zero behavior, null aggregation, `k_values`, and `relevance_threshold`.
8. Judgment coverage gates.
9. Slice confidence rules.
10. Required variants.
11. Title-only fallback behavior.
12. Ablation guardrails for `hybrid_no_cold_boost` without production search mutation.
13. Query fixture cache with schema versioning.
14. Pool builder.
15. Full evaluation CLI with `manifest.json`.
16. Reporting with mandatory tables, Variant Availability, and deterministic claim decisions.
17. Claim guardrails.
18. Offline fake-result smoke mode.
19. Documentation.
20. Live read-only evaluation run.

Do not start with live MongoDB. The first useful milestone is offline diagnostics, metric tests, and guardrail tests passing against fake results.

## 15. Verification Checklist

Before calling the phase complete:

- [x] `python -m pytest tests/test_evaluation_dataset.py -v` passes.
- [x] `python -m pytest tests/test_evaluation_diagnostics.py -v` passes.
- [x] `python -m pytest tests/test_evaluation_guardrails.py -v` passes.
- [x] `python -m pytest tests/test_evaluation_metrics.py -v` passes.
- [x] `python -m pytest tests/test_evaluation_runner.py -v` passes.
- [x] `python -m pytest tests/test_evaluation_variants.py -v` passes.
- [x] `python -m pytest tests/test_pipeline.py tests/test_validation.py tests/test_llm_client.py -v` passes.
- [x] `scripts/run_eval_diagnostics.py --help` works.
- [x] `scripts/build_eval_pool.py --help` works.
- [x] `scripts/run_evaluation.py --help` works.
- [x] `scripts/run_evaluation.py --use-fake-results` can generate a smoke report without MongoDB/Ollama/BGE-M3.
- [x] Layer 1 diagnostics can run without MongoDB.
- [x] Layer 2 metrics can run from mocked or cached results.
- [x] Layer 3 report separates query-processing latency from search latency.
- [x] Claim Status table blocks unsupported claims.
- [x] Variant Availability table is present.
- [x] `title_only` unavailable behavior is recoverable.
- [x] `hybrid_no_cold_boost` does not mutate global constants.
- [x] Evaluation runner never calls MongoDB write/index methods.
- [x] Stale cached fixtures are rejected by default.
- [x] Every successful CLI writes `manifest.json`.
- [x] Importing `src/evaluation/*` modules has no side effects.
- [x] `evaluation/README.md` explains labeling rules and metric meaning.
- [x] Final report lists commands run and commands not run.

### Guardrail Patch Checklist

Before implementation starts, confirm:

- [x] `ColdStartHit@K` and `ColdStartWindowSeconds@K` are distinct.
- [x] `ColdRelevantRate@K`, `ColdShareOfRelevant@K`, and `RawColdCoverage@K` are defined.
- [x] `RawColdCoverage@K` is marked diagnostic-only.
- [x] First pass explicitly avoids changing production search behavior.
- [x] `EvaluationResult.is_cold_item` defaults to `None` or `False`, not `True`.
- [x] Unknown cold-start status is tracked separately.
- [x] `RunConfig` records reproducibility fields.
- [x] `RunConfig` includes `k_values` and `relevance_threshold`.
- [x] Metric configuration comes from `RunConfig`.
- [x] `query_judgment_coverage_rate` and `result_judgment_coverage_rate` are distinct.
- [x] `positive_judged_query_count` is query-level.
- [x] Zero-denominator metrics return `null` / `N/A`.
- [x] Macro averages ignore null metrics and report valid/null counts.
- [x] `result_status` supports `ok`, `ok_empty`, `failed`, and `skipped`.
- [x] Normal empty results are not infrastructure failures.
- [x] `FailureRecord`, `ClaimStatus`, `RunConfig`, and `MetricGateResult` contracts exist.
- [x] `FailureRecord.details` exists.
- [x] Judgment coverage gates are defined.
- [x] Slice-level minimum counts are defined.
- [x] Metric confidence levels are defined.
- [x] Diagnostic statuses are standardized.
- [x] Diagnostic pass-rate excludes `known_risk`, `expected_unsupported`, and `skipped_dependency_missing`.
- [x] Failure rows include `error_type`.
- [x] Error taxonomy is listed.
- [x] `title_only` fallback behavior is explicit.
- [x] Variant Availability table is required.
- [x] Unavailable `title_only` blocks the hybrid-beats-title claim.
- [x] `hybrid_no_cold_boost` avoids global mutation.
- [x] Scoring-stage parameterization is recommended when low-risk.
- [x] Read-only MongoDB enforcement is tested.
- [x] Cached fixtures have a schema version.
- [x] Stale fixture cache is rejected by default.
- [x] Each successful CLI writes `manifest.json`.
- [x] Evaluation modules are import-safe.
- [x] Latency guardrails include `warm_cache` and cached fixtures.
- [x] P95 latency has sample-size confidence.
- [x] Unsupported claim guardrails are required in the final report.
- [x] Claim status generation uses deterministic gates.
- [x] Detailed labeling rules are added.
- [x] Mandatory report tables are listed.
- [x] CLI validation requirements are listed.
- [x] Guardrail tests are listed.
- [x] Smoke test can run without MongoDB/Ollama/BGE-M3.

## 16. Open Decisions For The Human Team

Decide after the first candidate pool:

- Should binary relevance mean `relevance >= 2` or only `relevance == 3`?
- Should no-diacritic Vietnamese be part of the main score or a stress-test slice?
- Should price-filter mismatch cap relevance at `1` or force `0`?
- Should `ColdRelevantRate@10` be a headline metric or supporting metric?
- Should `ColdShareOfRelevant@10` be shown in the main table or only in detail sections?
- Should `hybrid_no_cold_boost` become a permanent regression check?
- Should LLM-as-judge be added later as secondary analysis after manual judgments exist?

### Optional RAGAS / LLM-as-Judge Scope

RAGAS or LLM-as-Judge must not be part of the first implementation milestone.

It may be added later only after:

- manual judgments exist
- Layer 2 IR metrics run successfully
- reports already distinguish supported and unsupported claims

If added, it should evaluate explanation quality, such as whether `matched_fact` and `matched_intent` support the shown result. It must not replace human relevance judgments or headline IR metrics.

### Optional Report Diffing

Report diffing is not required for the MVP implementation.

It may be added later as:

```bash
python scripts/compare_evaluation_runs.py \
  --before .runtime/evaluation/eval_old \
  --after .runtime/evaluation/eval_new
```

Use it to compare metric movement between retrieval or prompt changes after the base evaluation runner is stable.

### Optional Second-pass Judgment Review

Second-pass adjudication is not required for the MVP implementation.

After the first pool is labeled, it may be used to improve label consistency by reviewing:

- worst 10 queries by `NDCG@10`
- examples where variants disagree heavily
- high-impact labels that materially change `NDCG@10` or `MRR@10`

## 17. Definition Of Done

Evaluation phase is done when a teammate can:

1. Run offline diagnostics and know which component is weak.
2. Run a judged retrieval evaluation comparing `title_only`, `vector_only`, `bm25_only`, `hybrid_union`, and `hybrid_no_cold_boost`.
3. Open one Markdown report that explains retrieval quality, demo readiness, failures, and the next code area to improve.
