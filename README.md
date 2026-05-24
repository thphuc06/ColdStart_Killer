# ColdStart Killer

ColdStart Killer is a MongoDB Hackathon project for bootstrapping retrieval for brand-new ecommerce products. The system builds a 3,000-item MVP dataset from Amazon Reviews 2023 metadata, generates HyPE queries and propositions via Qwen3:8b (Ollama), embeds with BAAI/bge-m3, and runs hybrid retrieval (vector + BM25) through MongoDB Atlas. The evaluation framework measures retrieval quality across 5 search variants and generates both technical and hackathon-facing reports.

## Current Phase Scope

This phase includes:

- Notebook dataset building from selected Amazon Reviews 2023 metadata.
- Notebook-driven MongoDB insertion.
- Buyer query processing and CLI search.
- Hybrid MongoDB retrieval with `$vectorSearch`, Atlas `$search`, and `$unionWith` RRF fallback.
- Native `$rankFusion` pipeline support for explicit testing.
- English propositions and English HyPE queries.
- BAAI/bge-m3 embeddings for HyPE queries only.
- Product images preserved for result display.
- User behavior logging, profile rebuilding, and item-item Collaborative Filtering recommendation services.
- A thin FastAPI layer for homepage feed, search, item detail, similar-items, users, events, and debug/demo operations.
- A React + Vite frontend demo under `frontend/` for homepage, search, detail, similar-products, and debug/admin flows.
- **Retrieval evaluation** with 5 variants, 50 queries, 20 diagnostic probes, AI-assisted conservative relevance judgments (2,119 query-item pairs labeled using LLM with conservative scoring — human audit recommended before claiming as full ground truth), and IR metrics (NDCG, Recall, MRR, Precision, HitRate, cold-start exposure quality).
- **Hackathon impact reporting** with variant deltas, qualitative examples, business-impact stories, Vietnamese slice analysis, and cold-start caveats.

This phase still does not include:

- A production-hardened seller-facing UI.
- A dedicated onboarding/session-management backend beyond the current demo contract.

## Current Evaluation Status

Latest verified live run:

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/plan_review_live
```

Result summary:

| Item | Current value |
|---|---:|
| Retrieval queries | 50 |
| AI-assisted conservative judgments | 2,119 |
| Judged queries | 50 |
| Queries with relevance >= 2 | 43 |
| Live retrieval results | 2,425 |
| Evaluation failures | 0 |
| Report status | sufficient |
| Dataset cold percentage | 100.0% |
| Search P95 latency | 116.5ms |
| Total P95 latency | 1173.0ms |

Live MongoDB data snapshot:

| Metric | Current value |
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

Live report artifacts:

- `.runtime/evaluation/plan_review_live/metrics_summary.md`
- `.runtime/evaluation/plan_review_live/hackathon_impact_report.md`
- `.runtime/evaluation/plan_review_live/config.json`
- `.runtime/evaluation/plan_review_live/layer2_metrics_summary.json`
- `.runtime/evaluation/plan_review_live/layer2_metrics_by_query.csv`
- `.runtime/evaluation/plan_review_live/layer2_raw_results.json`

Interpretation caveats:

> ⚠️ Evaluation labels are AI-assisted, not fully human-audited. NDCG and recall metrics reflect AI-label quality, not human oracle quality.

- The current relevance labels are AI-assisted conservative relevance judgments (2,119 query-item pairs labeled using LLM with conservative scoring — human audit recommended before claiming as full ground truth). They are sufficient for local evaluation gates, but a human audit is recommended before publication-grade claims.
- The live dataset is cold-dominant (`warm_items = 0` in the latest run), so cold-start metrics are framed as **exposure quality**, not cold-vs-warm lift.
- `Cold-start window was measured` remains `needs_more_evidence` until source data includes `indexed_at` and `first_seen_in_top_k_at`.
- Live MongoDB search latency is below the 400ms target in the latest run, but total reported latency is still above 400ms. Treat query processing and embedding/translation caching as demo hardening work.
- Python 3.14 currently runs the project, but `torch/sentence-transformers` emits a stability warning. Python 3.10-3.12 is still the safer demo runtime.

## Notebook-First Demo Philosophy

The notebooks are the technical proof:

- `notebooks/01_build_3k_mvp_dataset_from_amazon_reviews.ipynb` audits and builds the MVP dataset.
- `notebooks/02_insert_3k_mvp_to_mongodb.ipynb` estimates and inserts documents into MongoDB in controlled increments.
- `notebooks/03_buyer_search_pipeline_test.ipynb` verifies buyer search health against live MongoDB.
- `notebooks/04_demo_buyer_search.ipynb` runs the end-to-end buyer search demo.
- `notebooks/05_evaluation_retrieval_quality.ipynb` runs the 3-layer evaluation: diagnostics → IR metrics → demo readiness claims.

## Project Structure

- `src/query_processor.py` — query processing pipeline (language detection, translation via Qwen3:8b, price filter extraction, HyPE query generation, BGE-M3 embedding).
- `src/search_pipeline.py` — hybrid MongoDB search.
- `src/api/` — FastAPI adapter exposing recommendation, event, and debug/demo endpoints.
- `src/retrieval_output.py` — explainable result formatter.
- `frontend/` — React + Vite Phase 11 demo frontend.
- `src/evaluation/` — evaluation framework (contracts, dataset loading, diagnostics, metrics, variants, runner, reporting, hackathon report generation, explanation coverage checks).
- `scripts/run_search.py` — CLI search runner.
- `scripts/run_evaluation.py` — full evaluation CLI (supports `--use-fake-results` for smoke testing and writes `hackathon_impact_report.md` by default).
- `scripts/run_eval_diagnostics.py` — Layer 1 diagnostic probes CLI.
- `scripts/build_eval_pool.py` — judgment pool builder for manual labeling.
- `scripts/import_eval_judgments.py` — imports labeled CSV judgments to JSON format.
- `scripts/summarize_evaluation.py` — re-summarize an existing evaluation run.
- `evaluation/` — evaluation data (queries, probes, judgments).
- `notebooks/05_evaluation_retrieval_quality.ipynb` — evaluation notebook.
- `PLAN_EVALUATION.md` — current evaluation implementation status and verification record.
- `task.md` — compact task tracking summary for the evaluation improvement work.
- `TESTING.md` — testing guide.

## Verified Implementation Notes

Implementation details were checked against official documentation:

- Hugging Face Datasets streaming/loading: https://huggingface.co/docs/datasets/dataset_streaming
- Amazon Reviews 2023 dataset card: https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023
- MongoDB Atlas Vector Search index fields: https://www.mongodb.com/docs/atlas/atlas-vector-search/create-index/
- MongoDB Atlas Search field mappings and standard analyzer: https://www.mongodb.com/docs/atlas/atlas-search/define-field-mappings/
- PyMongo bulk writes and `UpdateOne(..., upsert=True)`: https://www.mongodb.com/docs/languages/python/pymongo-driver/current/write/bulk-write/
- Ollama chat `think` parameter: https://docs.ollama.com/api/chat
- SentenceTransformers `encode(..., normalize_embeddings=True)`: https://www.sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html
- BAAI/bge-m3 model card: https://huggingface.co/BAAI/bge-m3

## Setup

Use a virtual environment, install dependencies, then copy `.env.example` to `.env` and fill in the values.

Phase 11 frontend demo additionally requires Node.js and npm. The frontend ships with `frontend/.env.example`; copy it to `frontend/.env` only when the API is not running at `http://127.0.0.1:8000`.

Required environment variables:

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `OLLAMA_MODEL`
- `EMBEDDING_MODEL`
- `USE_CUDA`
- `EMBEDDING_STORAGE_FORMAT`

Default embedding storage is `list_float` for simplicity in this MVP. The code is organized so a later `bindata_float32` option can be added without changing the retrieval-unit schema contract.

LLM: Qwen3:8b running locally via Ollama. Used for Vietnamese→English translation, HyPE query generation, and proposition extraction.

## MongoDB Atlas Manual Steps

Create the Atlas cluster and database manually. This code does not create Atlas indexes automatically.

Collections:

- `items`
- `retrieval_units`

### Vector Search Index

Create this Atlas Vector Search index manually on `retrieval_units`.

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    },
    { "type": "filter", "path": "unit_type" },
    { "type": "filter", "path": "aspect" },
    { "type": "filter", "path": "language" },
    { "type": "filter", "path": "category_id" },
    { "type": "filter", "path": "price_bucket" },
    { "type": "filter", "path": "in_stock" },
    { "type": "filter", "path": "is_cold_item" }
  ]
}
```

### Atlas Search Text Index

Create this Atlas Search index manually on `retrieval_units` and name it `text_index`.

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "text_search": { "analyzer": "lucene.standard", "type": "string" },
      "embedding_text": { "analyzer": "lucene.standard", "type": "string" },
      "raw_text": { "analyzer": "lucene.standard", "type": "string" },
      "item_title_en": { "analyzer": "lucene.standard", "type": "string" },
      "item_brand": { "analyzer": "lucene.standard", "type": "string" },
      "unit_type": { "type": "string" },
      "language": { "type": "string" },
      "in_stock": { "type": "boolean" },
      "is_cold_item": { "type": "boolean" },
      "category_id": { "type": "string" },
      "confidence": { "type": "number" },
      "proposition_type": { "type": "string" },
      "aspect": { "type": "string" }
    }
  }
}
```

`text_index` must include the fields used by proposition BM25 search and buyer-search debug/explain output.

## Run Order

1. Build the MVP dataset in Notebook 01.
2. Run Notebook 02 through the dry-run and small write cells to create/populate `items` and `retrieval_units`.
3. Create the MongoDB Atlas Vector Search and Atlas Search indexes manually once `retrieval_units` exists.
4. Continue larger Notebook 02 batches with `resume=True`.
5. Run buyer search checks in Notebook 03 or `scripts/run_search.py`.
6. Run Notebook 04 for the end-to-end buyer demo.

For the full operator walkthrough, use [`RUNBOOK.md`](RUNBOOK.md).

## Data Policy

Dataset loading uses selected Amazon Reviews 2023 metadata only:

- All_Beauty metadata: full parquet first, streaming JSONL fallback.
- Cell_Phones_and_Accessories metadata: streaming JSONL, first 20,000 rows.
- Optional All_Beauty review sample: audit metadata only.

Dataset covers 2 source categories: All_Beauty and Cell_Phones_and_Accessories.

Reviews are not used as retrieval features.

## MVP Selection Policy

The primary insert/test dataset is `analysis/mvp_3000_items_diverse.csv`.

Required filters:

- `parent_asin`, title, store, category, price, and product text present.
- Price parsed and non-zero.
- Description or features present.
- Combined text words >= 150 when enough data is available.
- Unique `parent_asin`.

Fallback thresholds are 120, 100, then 80 if 3,000 useful items cannot be reached at 150. Image rows are preferred, with a 95% coverage target when the source data makes it possible.

## Retrieval Units

HyPE units:

- `unit_type = "hype_question"`
- English only.
- Dynamic 3 to 6 per item.
- Required aspects: function, persona, occasion.
- Embedded with BAAI/bge-m3.
- Stored in `retrieval_units.embedding`.

Proposition units:

- `unit_type = "proposition"`
- English only.
- Dynamic 3 to 8 per item.
- Confidence >= 0.60.
- Stored in `retrieval_units.text_search`.
- Not embedded.

## Limits

- Default indexing limit: 50.
- Dev limit: 500.
- M0 safe limit: 3000.
- Dedicated full limit: 5000.

Bulk MVP indexing is sequential for Ollama calls and defaults to MongoDB dry-run behavior in the script unless `--write` is passed. `--dry-run` still calls Ollama and BAAI/bge-m3 to prepare documents; it only skips MongoDB writes.

## Commands

```bash
cd ColdStart_Killer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python scripts/smoke_test_connection.py

jupyter lab

python scripts/build_3k_mvp_dataset.py
python scripts/index_mvp.py --limit 50 --dry-run
python scripts/index_mvp.py --limit 10 --write
python scripts/test_llm_generation.py
python scripts/test_embeddings.py
python scripts/run_search.py --help

# Full unit/integration-style test suite
python -m pytest tests/ -v

# Evaluation (no MongoDB required)
python scripts/run_eval_diagnostics.py --probes evaluation/queries/diagnostic_probes.json --out .runtime/evaluation/diagnostics

# Build or refresh evaluation judgment pool (requires MongoDB + Ollama + BGE-M3)
python scripts/build_eval_pool.py --queries evaluation/queries/retrieval_queries_seed.json --out .runtime/evaluation/pool_seed --top-k 20

# Import labeled CSV pool back to JSON format.
# Current seed JSON is already populated; rerun this only after relabeling judgment_pool.csv.
python scripts/import_eval_judgments.py --csv .runtime/evaluation/pool_seed/judgment_pool.csv --out evaluation/judgments/retrieval_judgments_seed.json --strict

# Evaluation smoke test (no MongoDB/Ollama/BGE-M3 required)
python scripts/run_evaluation.py --queries evaluation/queries/retrieval_queries_seed.json --judgments evaluation/judgments/retrieval_judgments_seed.json --out .runtime/evaluation/smoke --use-fake-results

# Full live evaluation (requires MongoDB + Ollama + BGE-M3)
python scripts/run_evaluation.py --queries evaluation/queries/retrieval_queries_seed.json --judgments evaluation/judgments/retrieval_judgments_seed.json --out .runtime/evaluation/eval_seed
```

macOS/Linux activation:

```bash
source .venv/bin/activate
```
