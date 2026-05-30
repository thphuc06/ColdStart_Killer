# ColdStart Killer Runbook

This runbook is the operator guide for the current phase. Follow it when you are ready to run the project on a machine that can download datasets/models, call Ollama, and connect to MongoDB Atlas.

## Current Phase Boundary

This phase does:

- Pull selected Amazon Reviews 2023 product metadata.
- Normalize and audit metadata.
- Build a 3,000-item MVP dataset across 2 source categories: All_Beauty and Cell_Phones_and_Accessories.
- Generate English propositions and English HyPE queries.
- Embed HyPE queries only with BAAI/bge-m3.
- Insert `items` and `retrieval_units` into MongoDB.
- Process buyer queries into search-ready fixtures.
- Run hybrid buyer search with MongoDB aggregation and `unionWith` RRF fallback.
- Test buyer search through CLI and notebooks.
- Run a React + Vite website demo backed by the FastAPI adapter.
- Show personalized homepage, query-first search, product detail, similar products, score breakdown, CF evidence, and Debug/Admin lineage.
- Capture optional cold-shopper onboarding preferences without direct profile or CF seeding.
- Safely inspect demo reset/recovery with dry-run-first scripts.

This phase does not do:

- Production auth/privacy.
- Production seller marketplace hardening or Tavily/web enrichment. The optional seller draft flow is staged and disabled by default.
- Redis/async worker infrastructure.
- Live reset/seed without explicit human confirmation.

Verified live MongoDB data snapshot:

| Metric | Value |
|--------|------:|
| items | 3,000 |
| retrieval_units | 29,753 |
| HyPE units | 13,580 |
| proposition units | 16,173 |
| cold items | 3,000 (100% cold — interaction_count=0) |
| categories | All_Beauty, Cell_Phones_and_Accessories |
| VECTOR_NUM_CANDIDATES | 400 |
| VECTOR_CHANNEL_LIMIT | 20 |

`category_id` is NOT a hard filter — category intent is handled by BGE-M3 embedding semantics in `$vectorSearch`. `hard_filters` only supports: `in_stock`, `price_max`, `price_min`.

## Website Demo Quickstart

Run from repo root unless noted.

Backend:

```bash
python -m uvicorn src.api.app:app --reload
```

API smoke:

```bash
python -m pytest tests/test_api_smoke.py -q -p no:cacheprovider
```

Frontend:

```bash
cd frontend
npm install
npm run build
npm run test:ui -- --run
npm run dev
```

Manual browser flow:

1. Select a profile-backed user from the user/persona selector.
2. Optionally create a new shopper and open Preferences onboarding.
3. Preview preferences read-only, then skip or complete onboarding.
4. Verify homepage cards load from the API.
5. Expand score breakdown and explanation on a product card.
6. Click a product and verify product detail.
7. Verify similar products distinguish `Semantic similarity` from `Collaborative Filtering`.
8. Run search and verify query-first messaging.
9. Open Debug/Admin and verify lineage: recommendation logs -> clickstream events -> user signals -> profile -> item-item CF edges.
10. Verify Demo Recovery shows protected collections and reset warnings.

Important CF wording:

- `item_semantic_neighbors` is semantic similarity, not CF.
- True CF is `item_item_cf_edges` built from `user_item_signals`.

## Demo Reset and Recovery

Dry-run reset commands are safe and should be run before any live reset:

```bash
python scripts/reset_demo_behavior_data.py --soft --dry-run
python scripts/reset_demo_behavior_data.py --full --dry-run
```

Soft reset keeps precomputed demo artifacts such as `item_item_cf_edges` for quick recovery. Full reset clears behavior-derived artifacts and requires rebuilding synthetic events, signals, profiles, item stats, and item-item CF.

Protected collections:

```text
items
retrieval_units
```

Live reset requires explicit write mode plus confirmation:

```bash
python scripts/reset_demo_behavior_data.py --soft --write --confirm DEMO_RESET
python scripts/reset_demo_behavior_data.py --full --write --confirm FULL_DEMO_RESET
```

Do not run live reset on a final/judging database unless the target DB is printed, reviewed, and approved by a human. The old `scripts/clear_demo_data.py` is quarantined and should not be used.

Common troubleshooting:

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: datasets` in full pytest | Optional dataset-selection dependency missing | Install the dependency only if running old dataset-selection tests, or run targeted demo tests. |
| `node_modules` missing | Frontend dependencies not installed | `cd frontend && npm install`. |
| Python 3.14 warning from torch/sentence-transformers | Runtime newer than recommended ML stack | Prefer Python 3.10-3.12 for demo machines. |
| MongoDB timeout | IP not whitelisted or wrong URI | Check Atlas Network Access and `.env`, without printing secrets. |
| BM25/vector search fails | Atlas Search index missing/not ready | Verify `text_index` and `vector_index` in Atlas UI. |

## Personalization Evaluation Smoke

Use this when you need a quick, honest demo-proof summary for personalization and CF.

Dry-run without MongoDB writes or local artifacts:

```bash
python scripts/run_personalization_evaluation.py --dry-run
python scripts/run_personalization_evaluation.py --dry-run --no-artifacts
```

Save local artifacts intentionally:

```bash
python scripts/run_personalization_evaluation.py --dry-run --write-artifacts
```

Persist a compact MongoDB `evaluation_runs` summary only after human approval:

```bash
python scripts/run_personalization_evaluation.py --write-evaluation-run --confirm EVAL_RUN_WRITE
```

This writes a compact, caveated summary only. It does not write local report artifacts unless `--write-artifacts` is also provided. Rollback is operational: do not pass `--write-evaluation-run`; any cleanup of persisted test runs should be a separate human-approved admin action.

The Debug/Admin evaluation dashboard is read-only. It lists the latest persisted `evaluation_runs` summary, shows baseline metrics and the synthetic/demo caveat, and never starts an evaluation job from the browser. If the collection is empty, the UI shows the command above as text for a human-approved run.

The terminal summary should show:

- `content_only`, `exploration_only`, `popularity`, `profile_only`, and `profile_plus_cf`.
- HitRate@10, Recall@20, MAP@20.
- Coverage, cold-start exposure, and CF-supported recommendation count/rate.
- `algorithm_version` and `ranking_version` for reproducibility.

Interpretation rule:

> Synthetic/demo metrics are indicative only. They help explain system behavior and compare baselines, but they are not human-audited ground truth.

## Fusion Comparison Smoke

Batch 14.10 adds a read-only comparison utility for the stable `$unionWith` / manual RRF path versus optional native `$rankFusion` support:

```bash
python scripts/compare_fusion_strategies.py --dry-run
```

By default this smoke uses a catalog-backed query fixture from `item_hype_profiles`
so it can compare fusion modes without loading the local embedding model. For a
true `process_query()` comparison, use:

```bash
python scripts/compare_fusion_strategies.py --dry-run --live-query-processing
```

Write a local JSON artifact only when needed:

```bash
python scripts/compare_fusion_strategies.py --dry-run --write-artifacts
```

Safety notes:

- This script never writes MongoDB.
- The production default search mode remains `unionWith`.
- `$rankFusion` may be unsupported depending on Atlas tier/version; the script reports that gracefully unless `--strict` is used.
- `$scoreFusion` is not implemented in this repo and is reported as proposed-only.

Judge clarification: Aggregation Pipeline CF proof is not required for the current roadmap. Current CF remains Python-side behavior-derived item-item CF from `user_item_signals`; MongoDB Aggregation Pipeline remains used in retrieval/ranking/filtering/evaluation/debug processing.

## Optional Query Embedding Cache

Batch 14.2 adds an optional runtime cache around `process_query()` for repeated search queries. It is safe by default:

```text
ENABLE_QUERY_EMBEDDING_CACHE=false
QUERY_CACHE_WRITE_ENABLED=false
QUERY_CACHE_VERSION=query_cache_v1
QUERY_CACHE_TTL_DAYS=0
```

Rollback is immediate: set `ENABLE_QUERY_EMBEDDING_CACHE=false`. Cache writes require `QUERY_CACHE_WRITE_ENABLED=true`; leave writes disabled for judging/demo unless a human explicitly approves cache persistence.

## Optional Seller Draft Flow

Batch 14.5 adds a staged seller add-product flow. It is disabled by default:

```text
ENABLE_SELLER_TOOLS=false
SELLER_INDEX_CONFIRMATION=INDEX_SELLER_DRAFT
SELLER_DRAFT_MAX_PREVIEW_UNITS=20
```

When enabled for a reviewed local demo, use `/seller/drafts` in the React app or the API:

```text
POST /api/seller/drafts
POST /api/seller/drafts/{draft_id}/validate
POST /api/seller/drafts/{draft_id}/index-preview
POST /api/seller/drafts/{draft_id}/approve-index?write=true&confirm=INDEX_SELLER_DRAFT
```

Safety contract:

- Draft creation writes only to `seller_product_drafts`.
- Index preview runs Qwen proposition/HyPE generation and BGE-M3 embedding, stores the complete private bundle in `seller_indexing_previews`, and writes only a safe summary back to the draft; it does not write `items` or `retrieval_units`.
- Approve-index is the only catalog-write path, requires `write=true` plus the exact confirmation string, and commits the exact ready preview bundle without regenerating text or embeddings.
- Approve-index refuses existing `items._id` collisions and existing `retrieval_units.item_id` collisions.
- Seller indexing adds both proposition and HyPE vector retrieval units. It immediately upserts `item_hype_profiles`; profile failure is retryable and does not roll back searchable catalog data.
- Rollback is immediate: set `ENABLE_SELLER_TOOLS=false`; staged drafts can remain in `seller_product_drafts`.

## Optional Web Enrichment for Seller Drafts

Batch 14.6 adds optional Tavily/web enrichment for staged seller drafts. It is disabled by default and the app runs without an API key:

```text
ENABLE_WEB_ENRICHMENT=false
WEB_ENRICHMENT_PROVIDER=tavily
TAVILY_API_KEY=
TAVILY_MAX_RESULTS=3
WEB_ENRICHMENT_MAX_QUERIES=3
WEB_ENRICHMENT_TIMEOUT_SECONDS=10
WEB_ENRICHMENT_APPLY_CONFIRMATION=APPLY_WEB_ENRICHMENT
```

Safety contract:

- Preview displays the filtered product context and deterministic query preview only; it performs no writes or provider calls.
- Requesting enrichment requires `ENABLE_WEB_ENRICHMENT=true` and a configured provider; Qwen produces one to three queries, Tavily searches them concurrently, and Qwen synthesizes grounded output. It writes only `web_enrichment_requests` plus draft enrichment metadata.
- Suggestions must include source URLs and confidence. Do not use suggestions without provenance.
- Applying suggestions requires `confirm=APPLY_WEB_ENRICHMENT`, updates only selected `seller_product_drafts` fields, and invalidates any earlier indexing preview when indexed content changed.
- Enrichment never writes `items`, `retrieval_units`, `user_profiles`, `item_item_cf_edges`, or `item_hype_profiles`; those last indexing artifacts are produced only by the separately confirmed indexing flow.
- Seller validation, index preview, and approve-index remain separate steps.
- Rollback is immediate: set `ENABLE_WEB_ENRICHMENT=false`; staged enrichment requests can remain ignored.

## Lightweight Job Registry

Batch 14.7 adds a small job registry and compact `job_runs` status layer. This is not Celery/Redis and it does not replace the existing scripts.

```text
ENABLE_JOB_RUNS=true
ENABLE_JOB_TRIGGER_API=false
JOB_RUN_CONFIRMATION=RUN_JOB
JOB_RUN_MAX_HISTORY=50
```

Safe CLI checks:

```bash
python scripts/run_job.py --list
python scripts/run_job.py --job fusion_comparison_dry_run --dry-run --no-track
```

Safety contract:

- Debug/Admin can read `/api/jobs/registry` and `/api/jobs/runs`.
- The browser does not run jobs while `ENABLE_JOB_TRIGGER_API=false`.
- CLI dry-runs do not write `job_runs` unless `--track` is explicitly passed.
- Write-capable jobs remain manual-only and keep their own confirmation strings.
- Redis/real async workers are still future work.

## Optional Backend Cache Layer

Batch 14.8 adds a small cache abstraction for safe read-heavy API paths. It is disabled by default and is separate from the query embedding cache.

```text
CACHE_BACKEND=none
CACHE_DEFAULT_TTL_SECONDS=300
CACHE_KEY_VERSION=v1
REDIS_URL=
REDIS_SOCKET_TIMEOUT_SECONDS=2
REDIS_CONNECT_TIMEOUT_SECONDS=2
CACHE_DEBUG_HEADERS=false
```

Supported backends:

- `none`: default no-op behavior.
- `memory`: in-process TTL cache for local/dev.
- `redis`: optional lazy backend; app falls back to no-op if `REDIS_URL` is missing, Redis is unavailable, or the package is not installed.

Current cached paths:

- `GET /api/evaluation/runs/latest`
- `GET /api/evaluation/runs`
- `GET /api/evaluation/runs/{run_id}`
- `GET /api/jobs/registry`
- `GET /api/jobs/runs`
- `GET /api/jobs/runs/{job_run_id}`

Safety contract:

- Write endpoints are not cached.
- Raw event histories, secrets, admin tokens, and provider keys are not used in cache keys.
- Personalized homepage/search/similar responses are not cached in this first pass.
- Rollback is immediate: set `CACHE_BACKEND=none`.

## Auth / Privacy Guardrails

Batch 14.9 adds lightweight token guards without changing the public shopper demo flow:

```text
AUTH_MODE=demo
ADMIN_TOKEN=
SELLER_TOKEN=
AUTH_REQUIRE_ADMIN_FOR_DEBUG=true
AUTH_REQUIRE_ADMIN_FOR_WRITES=true
PRIVACY_MASK_DEBUG_DATA=true
```

Use a locally generated token for admin actions:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Policy:

- Public reads remain open: homepage feed, search, item detail, similar products, user selection, and onboarding.
- Debug/Admin and demo reset/seed/rebuild controls require `ADMIN_TOKEN` when `AUTH_MODE=demo` or `production`.
- Live Debug/Admin write controls require exact confirmation strings: `SEED_DEMO_BEHAVIOR`, `PROCESS_EVENTS_WRITE`, `APPLY_PENDING_BEHAVIOR_WRITE`, `REBUILD_PROFILES_WRITE`, and `REBUILD_CF_WRITE`.
- Seller approve-index and enrichment request/apply require an admin or seller token plus their existing confirmation strings.
- Job trigger API requires admin token and remains disabled unless `ENABLE_JOB_TRIGGER_API=true`.
- Debug payloads redact secret-like fields and mask raw user identifiers when `PRIVACY_MASK_DEBUG_DATA=true`.

Rollback for local-only emergency: set `AUTH_MODE=disabled`. Do not use disabled mode for shared demos or production-like runs.

## Optional Shopper Onboarding

Batch 14.1 adds an optional Preferences route for cold shoppers:

```text
ENABLE_ONBOARDING=true
ONBOARDING_MAX_SEED_ITEMS=8
ONBOARDING_PREVIEW_LIMIT=12
```

Safety contract:

- `GET /api/onboarding/options` and `POST /api/onboarding/preview` are read-only.
- `POST /api/onboarding/complete` writes only `users.onboarding` and onboarding `clickstream_events` for selected real catalog seed items.
- It does not write `user_profiles`, `item_item_cf_edges`, `items`, or `retrieval_units`.
- To derive profiles from onboarding choices, run the existing behavior processing flow in Debug/Admin or scripts after human approval.

Rollback is immediate: set `ENABLE_ONBOARDING=false`. The login/demo user selector and existing recommendation demo continue to work.

## Phase 0: Setup

Run from the parent folder:

```bash
cd coldstart-killer
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS/Linux activation:

```bash
source .venv/bin/activate
```

Create your environment file:

```bash
copy .env.example .env
```

Fill in:

- `MONGODB_URI`
- `MONGODB_DB_NAME`
- `OLLAMA_MODEL=qwen3:8b`
- `EMBEDDING_MODEL=BAAI/bge-m3`
- `USE_CUDA=true` if your machine has CUDA

Expected result:

- Virtual environment exists.
- Dependencies install.
- `.env` exists and has MongoDB credentials.

## Phase 1: MongoDB Atlas Manual Setup

Create an Atlas cluster and database manually.

Database:

```text
coldstart_killer
```

Collections:

```text
items
retrieval_units
```

If Atlas does not let you create search indexes until data exists, run the Notebook 02 dry-run and small write first, then come back to this phase and create the indexes. Inserts do not require these indexes, but retrieval tests do.

Create the Atlas Vector Search index manually on `retrieval_units`:

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

Create the Atlas Search text index manually on `retrieval_units` and name it `text_index`:

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

`text_index` must include the fields used by proposition BM25 search and buyer-search explain/debug output.

Then smoke-test connection:

```bash
python scripts/smoke_test_connection.py --counts
```

Expected result:

- `ok: true`
- collection counts are visible, usually `0` before indexing

## Phase 2: Pull, Normalize, Filter, and Build the 3K Dataset

Preferred path: open Notebook 01.

```bash
jupyter lab
```

Run:

```text
notebooks/01_build_3k_mvp_dataset_from_amazon_reviews.ipynb
```

What it does:

- Loads All_Beauty metadata.
- Streams a Cell_Phones_and_Accessories metadata sample.
- Normalizes title, store, category, price, details, features, description, and images.
- Builds `product_text_for_llm`.
- Scores richness.
- Builds a highest-quality control dataset.
- Builds a 3,000-item dataset across All_Beauty and Cell_Phones_and_Accessories.

Script alternative:

```bash
python scripts/build_3k_mvp_dataset.py
```

Expected output files:

Note: these files are generated by Phase 2 and are not expected to exist in a fresh clone before you run the dataset build step.

```text
analysis/mvp_3000_items.csv
analysis/mvp_3000_items_diverse.csv
analysis/mvp_3000_selection_report.json
analysis/data_audit_report.md
analysis/data_profile.json
analysis/needs_enrichment_items.csv
```

Expected success checks:

- `analysis/mvp_3000_items_diverse.csv` exists.
- Row count is 3,000 if enough source data is available.
- `parent_asin` is unique.
- `combined_words` is at or above the selected threshold.
- `description_text`, `features_text`, `details_text`, `product_text_for_llm`, `primary_image_url`, and `image_urls` are present.
- Image coverage is reported.

If fewer than 3,000 rows are produced:

- Open `analysis/mvp_3000_selection_report.json`.
- Check selected threshold and warnings.
- Do not fake success; use the best available dataset only if the report explains why.

## Phase 3: Local LLM and Embedding Readiness

Make sure Ollama is installed and the model exists:

```bash
ollama pull qwen3:8b
```

Optional single-call LLM check:

```bash
python scripts/test_llm_generation.py
```

Expected result:

- JSON-like output with `propositions` and `hype`.
- Propositions: 3 to 8.
- HyPE queries: 3 to 6.

Optional embedding check:

```bash
python scripts/test_embeddings.py
```

Expected result:

- `embedding_count: 1`
- `dimension: 1024`
- no NaN/inf/norm validation errors

Note:

- This phase may download BAAI/bge-m3 the first time.
- Use CUDA if available and configured.

## Phase 4: Insert MVP Data into MongoDB

Preferred path: open Notebook 02.

```text
notebooks/02_insert_3k_mvp_to_mongodb.ipynb
```

What it does:

- Loads `analysis/mvp_3000_items_diverse.csv`.
- Validates required columns.
- Estimates vector memory and retrieval-unit counts.
- Dry-runs a few items.
- Shows sample item/proposition/HyPE docs.
- Inserts 10 items.
- Inserts 50 items.
- Leaves 500, 1000, and 3000 inserts as optional cells.
- Supports `resume=True` so repeated batches continue from the first CSV row that is not already present in MongoDB.

Script dry-run:

```bash
python scripts/index_mvp.py --limit 50 --dry-run
```

Important:

- `--dry-run` still calls Ollama and BAAI/bge-m3.
- `--dry-run` only skips MongoDB writes.

Small write test:

```bash
python scripts/index_mvp.py --limit 10 --write
```

Resume from the next missing CSV row after an interrupted or partial insert:

```bash
python scripts/index_mvp.py --limit 500 --write --resume
```

Expected MongoDB document behavior:

- `items` are upserted by `_id`.
- Existing `retrieval_units` for those `item_id`s are deleted.
- New retrieval units are inserted.
- Re-running the same item does not duplicate retrieval units.

Expected counts after 10-item write:

- `items`: at least 10
- `retrieval_units`: roughly 60 to 140, depending on LLM output
- HyPE units have `embedding`
- Proposition units have `text_search` and no `embedding`

## Phase 5: Buyer Search Pipeline

Quick CLI check:

```bash
python scripts/run_search.py --help
```

Notebook health test:

```bash
jupyter lab
```

Then open:

```text
notebooks/03_buyer_search_pipeline_test.ipynb
```

End-to-end demo:

```text
notebooks/04_demo_buyer_search.ipynb
```

Expected behavior:

- Notebook 03 reports collection health, pipeline results, hybrid channel status, and field contract status.
- Notebook 04 processes a raw query, embeds the HyPE intent with BAAI/bge-m3, runs MongoDB hybrid search, and displays explainable results.
- `scripts/run_search.py` runs from a precomputed fixture and defaults to stable `unionWith` mode.

## Phase 6: Optional Cleanup

The old `scripts/clear_demo_data.py` script is quarantined and must not be used
for cleanup. Demo reset/recovery is behavior-only and dry-run-first.

Safe preview commands:

```bash
python scripts/reset_demo_behavior_data.py --soft --dry-run
python scripts/reset_demo_behavior_data.py --full --dry-run
```

Only run live reset after the target database has been reviewed by a human and
the correct confirmation string is provided:

```bash
python scripts/reset_demo_behavior_data.py --soft --write --confirm DEMO_RESET
python scripts/reset_demo_behavior_data.py --full --write --confirm FULL_DEMO_RESET
```

These reset paths protect `items` and `retrieval_units`; do not use any cleanup
path that targets catalog collections.

## Phase 7: Evaluation

Run retrieval evaluation to measure search quality across 5 variants.

### Step 1: Layer 1 Diagnostics (no MongoDB required)

```bash
python scripts/run_eval_diagnostics.py \
    --probes evaluation/queries/diagnostic_probes.json \
    --out .runtime/evaluation/diagnostics
```

Expected result:

- Diagnostics summary with pass rate.
- Known risks documented.

### Step 2: Smoke Test (no MongoDB/Ollama/BGE-M3 required)

```bash
python scripts/run_evaluation.py \
    --queries evaluation/queries/retrieval_queries_seed.json \
    --judgments evaluation/judgments/retrieval_judgments_seed.json \
    --out .runtime/evaluation/smoke \
    --use-fake-results
```

Expected result:

- `Evaluation completed in 0.1s`
- `Results: 750`, `Failures: 0`
- `metrics_summary.md` generated in output directory.

### Step 3: Build Judgment Pool (requires MongoDB + Ollama + BGE-M3)

```bash
python scripts/build_eval_pool.py \
    --queries evaluation/queries/retrieval_queries_seed.json \
    --out .runtime/evaluation/pool \
    --top-k 20
```

Expected result:

- `judgment_pool.csv` with (query, item) pairs for manual labeling under `.runtime/evaluation/pool/`.

### Step 3.5: Import Judgments (converts CSV to validated JSON)

After labeling the CSV file (filling in the `relevance` column from 0-3), run:

```bash
python scripts/import_eval_judgments.py \
    --csv .runtime/evaluation/pool/judgment_pool.csv \
    --out evaluation/judgments/retrieval_judgments_seed.json
```

Expected result:

- `evaluation/judgments/retrieval_judgments_seed.json` is populated with AI-assisted conservative relevance judgments.

### Step 4: Full Evaluation (requires judgments)

```bash
python scripts/run_evaluation.py \
    --queries evaluation/queries/retrieval_queries_seed.json \
    --judgments evaluation/judgments/retrieval_judgments_seed.json \
    --out .runtime/evaluation/eval_seed
```

Expected result:

- `metrics_summary.md` with Variant Comparison, Claim Status, Latency, Recommendations.
- All 9 output artifacts in the output directory.

### Step 5: Evaluation Notebook

Open `notebooks/05_evaluation_retrieval_quality.ipynb`, set `USE_FAKE_RESULTS = True` or `False`, Run All Cells.

LLM model: Qwen3:8b chạy local bằng Ollama. Cấu hình trong `.env` với `OLLAMA_MODEL=qwen3:8b`.

## Phase 8: Optional Cleanup

## Troubleshooting

MongoDB connection fails:

- Check `MONGODB_URI`.
- Check Atlas IP allowlist.
- Check username/password.
- Check cluster is running.

Dataset loading fails:

- Check network access.
- Check Hugging Face dataset URLs.
- Open `analysis/mvp_3000_selection_report.json` if partial output exists.

Ollama generation fails:

- Run `ollama list`.
- Pull `qwen3:8b`.
- Confirm Ollama server is running.

Embedding fails:

- First run may download BAAI/bge-m3.
- If CUDA is not available, set `USE_CUDA=false`.
- Dimension must be 1024.


