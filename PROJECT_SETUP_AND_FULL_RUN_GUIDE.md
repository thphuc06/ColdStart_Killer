# ColdStart Killer — Full Setup & Run Guide

This is the canonical setup and run guide for ColdStart Killer. Use this file as the primary GitHub/submission reference.

Do not put real secrets in this document. Do not commit `.env`.

## 1. Project Overview

ColdStart Killer is an ecommerce recommendation engine focused on cold-start shoppers and cold-start products.

It combines:

- MongoDB Atlas as the live product/recommendation datastore.
- MongoDB Vector Search for semantic and similarity retrieval.
- MongoDB Aggregation Pipeline for retrieval, ranking, filtering, evaluation, debug, and data processing workflows.
- Python-side behavior-derived Collaborative Filtering from `user_item_signals` into `item_item_cf_edges`.
- FastAPI backend APIs.
- React/Vite frontend demo.
- Behavior logging, user profiles, item-item CF, semantic neighbors, personalized homepage/search, item detail, similar products, and Debug/Admin lineage.
- Phase 14 features: onboarding, query embedding cache, evaluation persistence/dashboard, seller draft flow, Tavily/web enrichment, job registry, cache layer, auth/privacy, and fusion comparison.

Judge clarification: an Aggregation Pipeline CF proof is deferred/optional research. The project can satisfy the architecture by using Vector Search for semantic retrieval, Aggregation Pipeline for retrieval/ranking/filtering/evaluation/debug/data processing, and Python-side behavior-derived CF for collaborative filtering.

## 2. Architecture Overview

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                           Frontend: React + Vite                           │
│  Shopper login -> Home -> Search -> Item Detail -> Onboarding -> Debug     │
│  Optional seller draft UI and enrichment panel                             │
└───────────────────────────────┬────────────────────────────────────────────┘
                                │ HTTP REST via VITE_API_BASE_URL
┌───────────────────────────────▼────────────────────────────────────────────┐
│                            Backend: FastAPI                                 │
│  /api/health       /api/users          /api/feed          /api/search       │
│  /api/items        /api/events         /api/onboarding    /api/debug        │
│  /api/evaluation   /api/seller         /api/enrichment    /api/jobs         │
└───────────────┬──────────────────────┬────────────────────┬───────────────┘
                │                      │                    │
┌───────────────▼────────────┐ ┌───────▼──────────┐ ┌───────▼───────────────┐
│ MongoDB Atlas               │ │ Ollama Qwen3:8b  │ │ BGE-M3 embeddings     │
│ - items                     │ │ optional/recommended │ local Hugging Face  │
│ - retrieval_units           │ │ Vietnamese query │ │ 1024-dimensional     │
│ - users                     │ │ translation/query│ │ semantic vectors     │
│ - clickstream_events        │ │ processing       │ └───────────────────────┘
│ - user_item_signals         │ └──────────────────┘
│ - user_profiles             │ ┌──────────────────┐ ┌───────────────────────┐
│ - item_item_cf_edges        │ │ Tavily API       │ │ Redis optional         │
│ - evaluation_runs           │ │ optional web     │ │ API response cache     │
│ - seller_product_drafts     │ │ enrichment       │ │ backend=none default   │
│ - web_enrichment_requests   │ └──────────────────┘ └───────────────────────┘
│ - job_runs                  │
└─────────────────────────────┘
```

Production-grade OAuth, real worker queues, and Redis-backed async execution are outside this demo scope. The repo has lightweight auth guards, job registry/status tracking, and optional cache backends.

## 3. System Requirements

Recommended:

| Component | Recommended | Notes |
| --- | --- | --- |
| Python | 3.10 to 3.12 | Python 3.14 can warn/fail with some ML/Pydantic dependencies. |
| Node.js | 18+ or 20+ | Needed for React/Vite frontend. |
| npm | Bundled with Node | Use `npm install` inside `frontend/`. |
| MongoDB Atlas | Cluster with Atlas Search | Required for live demo/search. |
| Ollama | Latest | Recommended for Vietnamese query processing and local LLM steps. |
| Embedding model | `BAAI/bge-m3` | Required for vector/hybrid search workflows. |
| Tavily | Optional | Only needed when `ENABLE_WEB_ENRICHMENT=true`. |
| Redis | Optional | Only needed when `CACHE_BACKEND=redis`. |
| GPU/CUDA | Optional | CPU is supported with `USE_CUDA=false`. |

Check installed versions:

```bash
python --version
node --version
npm --version
```

## 4. Clone and Install

Clone:

```bash
git clone <your-repo-url>
cd ColdStart_Killer
```

Create Python virtual environment on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create Python virtual environment on macOS/Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If Python 3.12 is not available, use Python 3.10 or 3.11.

Install frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

## 5. MongoDB Atlas Setup

In MongoDB Atlas:

1. Create or select a project.
2. Create a cluster.
3. Create a database user.
4. Add your current IP in Network Access.
5. Copy the `mongodb+srv://...` connection string.
6. Put the URI only in local `.env`.

Recommended user permissions:

- Read-only demo/browsing: use a database user with read access to the target database.
- Full local demo with write-capable features: use a database user with `readWrite` on the target database.
- Avoid broad cluster-admin style permissions unless you fully understand the risk.

For a shared team database, do not seed/reset/write unless the team explicitly approves the action and you are using the correct database.

Minimal `.env` MongoDB values:

```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-host>/?retryWrites=true&w=majority
MONGODB_DB_NAME=coldstart_killer
MONGODB_TIMEOUT_MS=10000
```

Never paste a real URI into docs, issues, screenshots, logs, or chat.

## 6. Atlas Search Indexes

The search pipeline expects Atlas Search indexes on collection `retrieval_units`.

If the shared Atlas database is already prepared, just verify both indexes are `READY` or active:

- `vector_index`
- `text_index`

If you need to create indexes manually, use the following reference shapes and verify against the current code before creating them.

Vector Search index reference:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,
      "similarity": "cosine"
    },
    {
      "type": "filter",
      "path": "unit_type"
    },
    {
      "type": "filter",
      "path": "language"
    },
    {
      "type": "filter",
      "path": "in_stock"
    },
    {
      "type": "filter",
      "path": "is_cold_item"
    },
    {
      "type": "filter",
      "path": "price_bucket"
    },
    {
      "type": "filter",
      "path": "category_id"
    }
  ]
}
```

Text Search index reference:

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "text_search": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "embedding_text": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "raw_text": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "item_title_en": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "item_brand": {
        "type": "string",
        "analyzer": "lucene.standard"
      },
      "unit_type": {
        "type": "string"
      },
      "language": {
        "type": "string"
      },
      "in_stock": {
        "type": "boolean"
      },
      "is_cold_item": {
        "type": "boolean"
      },
      "category_id": {
        "type": "string"
      },
      "confidence": {
        "type": "number"
      },
      "proposition_type": {
        "type": "string"
      },
      "aspect": {
        "type": "string"
      }
    }
  }
}
```

Notes:

- `BAAI/bge-m3` vectors are 1024-dimensional.
- `retrieval_units` stores HyPE and proposition retrieval units.
- If Atlas blocks index creation until data exists, load data first using the existing runbook and only after a human review of write commands.

## 7. `.env` Setup

Copy the template:

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

Edit `.env` locally. Do not commit it.

### MongoDB

```env
MONGODB_URI=
MONGODB_DB_NAME=coldstart_killer
MONGODB_TIMEOUT_MS=10000
VECTOR_INDEX_NAME=vector_index
TEXT_INDEX_NAME=text_index
```

### Backend and CORS

```env
API_HOST=127.0.0.1
API_PORT=8000
CORS_ALLOW_ORIGINS=http://localhost:5173
```

### Models, Ollama, and Embeddings

```env
OLLAMA_MODEL=qwen3:8b
EMBEDDING_MODEL=BAAI/bge-m3
USE_CUDA=true
EMBEDDING_STORAGE_FORMAT=list_float
DEFAULT_INDEX_LIMIT=50
M0_SAFE_LIMIT=3000
DEDICATED_FULL_LIMIT=5000
```

If you do not have a CUDA GPU:

```env
USE_CUDA=false
```

### Auth and Privacy

```env
AUTH_MODE=demo
ADMIN_TOKEN=
SELLER_TOKEN=
AUTH_REQUIRE_ADMIN_FOR_DEBUG=true
AUTH_REQUIRE_ADMIN_FOR_WRITES=true
PRIVACY_MASK_DEBUG_DATA=true
```

`AUTH_MODE=demo` keeps public shopper read endpoints open and protects admin/write-capable actions. Use `AUTH_MODE=disabled` only for local emergency debugging, not for shared demos.

### Core Demo Flags

```env
DEMO_MODE=true
ENABLE_PERSONALIZATION=true
ENABLE_EVENT_LOGGING=true
```

### Onboarding

```env
ENABLE_ONBOARDING=true
ONBOARDING_MAX_SEED_ITEMS=8
ONBOARDING_PREVIEW_LIMIT=12
```

### Seller Draft Flow

```env
ENABLE_SELLER_TOOLS=false
SELLER_INDEX_CONFIRMATION=INDEX_SELLER_DRAFT
SELLER_DRAFT_MAX_PREVIEW_UNITS=20
```

### Tavily / Web Enrichment

```env
ENABLE_WEB_ENRICHMENT=false
WEB_ENRICHMENT_PROVIDER=tavily
TAVILY_API_KEY=
TAVILY_MAX_RESULTS=3
WEB_ENRICHMENT_TIMEOUT_SECONDS=10
WEB_ENRICHMENT_APPLY_CONFIRMATION=APPLY_WEB_ENRICHMENT
```

### Query Embedding Cache

```env
ENABLE_QUERY_EMBEDDING_CACHE=false
QUERY_CACHE_WRITE_ENABLED=false
QUERY_CACHE_VERSION=query_cache_v1
QUERY_CACHE_TTL_DAYS=0
```

### Jobs

```env
ENABLE_JOB_RUNS=true
ENABLE_JOB_TRIGGER_API=false
JOB_RUN_CONFIRMATION=RUN_JOB
JOB_RUN_MAX_HISTORY=50
```

### Cache / Redis

```env
CACHE_BACKEND=none
CACHE_DEFAULT_TTL_SECONDS=300
CACHE_KEY_VERSION=v1
REDIS_URL=
REDIS_SOCKET_TIMEOUT_SECONDS=2
REDIS_CONNECT_TIMEOUT_SECONDS=2
CACHE_DEBUG_HEADERS=false
```

### Versioning and Scoring

Keep these defaults unless you are running a controlled experiment:

```env
ALGORITHM_VERSION=rec_v2_negative_suppression_seed_guard
RANKING_VERSION=rank_v1_default_weights
SIGNAL_MODEL_VERSION=signal_v4_boundary_hygiene
PROFILE_MODEL_VERSION=profile_v4_negative_guard
CF_MODEL_VERSION=cf_v1_supported_edges
CF_RUNTIME_INPUT_POLICY=current_supported
EXPLANATION_VERSION=explain_v3_contribution_faithful
REASON_MIN_CONTRIBUTION=0.05
PROFILE_REASON_MIN_CONTRIBUTION=0.05
SIGNAL_CLICK_WEIGHT=0.35
SIGNAL_DETAIL_SHORT_MS=5000
SIGNAL_DETAIL_MEANINGFUL_MS=20000
SIGNAL_DETAIL_SHORT_WEIGHT=0.10
SIGNAL_DETAIL_MEDIUM_WEIGHT=0.50
SIGNAL_DETAIL_LONG_WEIGHT=1.25
SIGNAL_WISHLIST_WEIGHT=2.50
SIGNAL_ADD_TO_CART_WEIGHT=4.00
SIGNAL_PURCHASE_WEIGHT=7.00
SIGNAL_REPEAT_POSITIVE_BONUS=0.25
SIGNAL_REPEAT_POSITIVE_BONUS_CAP=1.50
SIGNAL_PREFERENCE_MIN_DELIBERATE_SCORE=0.50
SIGNAL_SEED_ELIGIBLE_MIN_DELIBERATE_SCORE=0.75
PROFILE_EXPLORATORY_WEIGHT=0.25
PROFILE_LABEL_MAX_LENGTH=80
EVENT_TTL_DAYS=0
```

## 8. Token and API Key Setup

Generate an admin token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in `.env`:

```env
ADMIN_TOKEN=<generated-admin-token>
```

Generate seller token the same way:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```env
SELLER_TOKEN=<generated-seller-token>
```

Tavily key is optional:

1. Open the Tavily dashboard.
2. Create an API key.
3. Put it only in local `.env`.
4. Enable web enrichment only when you intentionally want live Tavily calls.

```env
ENABLE_WEB_ENRICHMENT=true
TAVILY_API_KEY=<your-tavily-api-key>
```

Redis is optional:

```env
CACHE_BACKEND=redis
REDIS_URL=redis://localhost:6379/0
```

The app works without Tavily and without Redis.

## 9. Run Backend

From repo root:

```bash
python -m uvicorn src.api.app:app --reload
```

Default backend URL:

```text
http://127.0.0.1:8000
```

Useful endpoints:

```text
http://127.0.0.1:8000/api/health
http://127.0.0.1:8000/docs
```

Quick local smoke:

```bash
python -c "from fastapi.testclient import TestClient; from src.api.app import create_app; c=TestClient(create_app()); print(c.get('/api/health').status_code); print(c.get('/api/users/demo').status_code)"
```

## 10. Run Frontend

```bash
cd frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

Frontend API base env var:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

If backend or frontend ports change, update `CORS_ALLOW_ORIGINS` in backend `.env` and `VITE_API_BASE_URL` in `frontend/.env`.

## 11. Ollama and Embedding Model

Embeddings are required for vector/hybrid search workflows. The configured model is:

```env
EMBEDDING_MODEL=BAAI/bge-m3
```

Ollama is recommended and needed for Vietnamese query processing/translation and LLM-backed local steps:

```bash
ollama serve
ollama pull qwen3:8b
ollama list
```

If the machine has no GPU:

```env
USE_CUDA=false
```

English search may be easier to run if translation is not needed, but vector search still requires embeddings and Atlas Search indexes.

## 12. Verify MongoDB Live Connection

Read-only smoke:

```bash
python scripts/smoke_test_connection.py --counts
```

Expected demo database counts can be close to:

```text
database=coldstart_killer
items=3000
retrieval_units=29753
```

Counts may vary if the database has been rebuilt. If counts differ, do not seed or reset automatically. First verify `MONGODB_DB_NAME`, Atlas project, cluster, and target collections.

## 13. Safe Dry-run Checks

These commands are safe read-only or dry-run checks. They should not write MongoDB:

```bash
python scripts/reset_demo_behavior_data.py --soft --dry-run
python scripts/reset_demo_behavior_data.py --full --dry-run
python scripts/create_behavior_indexes.py --dry-run
python scripts/compare_fusion_strategies.py --dry-run
python scripts/run_job.py --list
python scripts/run_job.py --job fusion_comparison_dry_run --dry-run --no-track
python scripts/run_personalization_evaluation.py --dry-run --no-artifacts
```

Do not run live seller approve-index, live Tavily request, live reset, or write-capable jobs unless a human explicitly approves the action and confirmation string.

## 14. Test Suite

Core/API:

```bash
python -m pytest tests/test_api_smoke.py tests/test_pipeline.py -q -p no:cacheprovider
```

Phase 14 foundation:

```bash
python -m pytest tests/test_onboarding.py tests/test_query_embedding_cache.py tests/test_evaluation_persistence.py tests/test_api_evaluation_runs.py tests/test_personalization_evaluation.py tests/test_fusion_comparison.py -q -p no:cacheprovider
```

Seller/enrichment:

```bash
python -m pytest tests/test_seller_drafts.py tests/test_api_seller.py tests/test_enrichment_service.py tests/test_api_enrichment.py -q -p no:cacheprovider
```

Jobs:

```bash
python -m pytest tests/test_jobs_registry.py tests/test_jobs_runner.py tests/test_api_jobs.py -q -p no:cacheprovider
```

Cache:

```bash
python -m pytest tests/test_cache_keys.py tests/test_memory_cache.py tests/test_cache_service.py tests/test_api_cache_behavior.py -q -p no:cacheprovider
```

Auth/privacy:

```bash
python -m pytest tests/test_auth_dependencies.py tests/test_api_auth_guards.py tests/test_privacy_masking.py -q -p no:cacheprovider
```

Behavior/recommendation:

```bash
python -m pytest tests/test_behavior_schemas.py tests/test_behavior_indexes.py tests/test_homepage_feed.py tests/test_similar_products.py tests/test_search_personalizer.py -q -p no:cacheprovider
```

Frontend:

```bash
cd frontend
npm run build
npm run test:ui -- --run
cd ..
```

Full pytest:

```bash
python -m pytest tests -q -p no:cacheprovider
```

If full pytest fails because `datasets` is missing:

```bash
python -m pip install datasets
```

If you need to verify the broad app suite while skipping the legacy MVP-selection dependency:

```bash
python -m pytest tests -q -p no:cacheprovider --ignore=tests/test_mvp_selection.py
```

## 15. Main Demo Flow

Manual checklist:

1. Start backend.
2. Start frontend.
3. Open `http://localhost:5173`.
4. Select a saved/profile-backed shopper.
5. Verify homepage cards load from the API.
6. Expand score breakdown and recommendation evidence.
7. Search an English query.
8. Search a Vietnamese query if Ollama and embeddings are ready.
9. Open item detail.
10. Open similar products and verify semantic similarity is distinct from Collaborative Filtering.
11. Open `/onboarding`.
12. Preview onboarding preferences and confirm preview is read-only.
13. Skip or complete onboarding.
14. Open Debug/Admin.
15. Verify evaluation dashboard latest/empty state.
16. Verify jobs panel shows registry/runs and does not auto-trigger jobs.
17. Open seller draft route if seller tools are enabled; otherwise verify a readable disabled response (expected shape includes `ok=true`, `enabled=false`).
18. Verify enrichment disabled or provider-not-configured state if Tavily is not configured; disabled mode should be readable (not a hard failure response).
19. Check browser console/network for unexpected 500 errors.

Default demo does not require Tavily, Redis, seller catalog writes, or job trigger API.

## 16. Phase 13 Reset / Recovery Safety

Dry-run first:

```bash
python scripts/reset_demo_behavior_data.py --soft --dry-run
python scripts/reset_demo_behavior_data.py --full --dry-run
```

Dry-run must protect:

- `items`
- `retrieval_units`

Live reset is maintenance-only and must be human-approved:

```bash
python scripts/reset_demo_behavior_data.py --soft --write --confirm DEMO_RESET
python scripts/reset_demo_behavior_data.py --full --write --confirm FULL_DEMO_RESET
```

Do not run live reset on a submission/shared database unless you have verified the database name and the recovery plan.

## 17. Phase 14 Feature Flags

| Feature | Env flag | Default | Writes DB? | Safe to enable read-only? | Notes |
| --- | --- | --- | --- | --- | --- |
| Personalization | `ENABLE_PERSONALIZATION` | `true` | No by itself | Yes | Powers reranking/feed behavior. |
| Event logging | `ENABLE_EVENT_LOGGING` | `true` | Yes on event endpoints | Yes for demo | Normal clickstream logging. |
| Onboarding | `ENABLE_ONBOARDING` | `true` | Complete writes onboarding fields/events | Preview yes | Does not directly seed profiles or CF. |
| Query embedding cache | `ENABLE_QUERY_EMBEDDING_CACHE` | `false` | Reads only unless writes enabled | Yes | Separate from backend API cache. |
| Query cache writes | `QUERY_CACHE_WRITE_ENABLED` | `false` | Yes if enabled | Keep disabled for demo | Writes `query_embedding_cache`. |
| Seller tools | `ENABLE_SELLER_TOOLS` | `false` | Draft writes; approve-index writes catalog | Draft preview only when enabled | Catalog write needs auth and confirm. |
| Web enrichment | `ENABLE_WEB_ENRICHMENT` | `false` | Request/apply writes staging docs | Preview/query only | Tavily optional; no auto catalog write. |
| Job runs | `ENABLE_JOB_RUNS` | `true` | Only when tracking requested | Yes | Stores compact `job_runs`. |
| Job trigger API | `ENABLE_JOB_TRIGGER_API` | `false` | Potentially | Keep disabled | Browser cannot trigger by default. |
| Cache backend | `CACHE_BACKEND` | `none` | No | Yes | `none`, `memory`, optional `redis`. |
| Auth mode | `AUTH_MODE` | `demo` | No | Yes | Protects admin/write actions. |

Safe rollback values:

```env
ENABLE_QUERY_EMBEDDING_CACHE=false
QUERY_CACHE_WRITE_ENABLED=false
ENABLE_SELLER_TOOLS=false
ENABLE_WEB_ENRICHMENT=false
ENABLE_JOB_TRIGGER_API=false
CACHE_BACKEND=none
AUTH_MODE=demo
```

## 18. Seller Add Product Flow

Default:

```env
ENABLE_SELLER_TOOLS=false
```

Flow:

1. Seller creates a draft.
2. Draft is stored in `seller_product_drafts`.
3. Draft validation checks required fields.
4. Indexing preview builds proposed retrieval units.
5. Approve-index is blocked unless auth is present and both query params are correct:

```text
write=true&confirm=INDEX_SELLER_DRAFT
```

Approve-index behavior:

- Inserts one additive item into `items`.
- Inserts additive retrieval units into `retrieval_units`.
- Refuses item collisions.
- Refuses existing retrieval-unit collisions.
- Does not overwrite existing Amazon/MVP catalog items.
- Does not write `user_profiles`.
- Does not write `item_item_cf_edges`.
- Does not automatically rebuild `item_hype_profiles`.

After indexing a seller item, any deeper vector/profile/neighbor/evaluation coverage should be a separately reviewed workflow.

## 19. Tavily / Web Enrichment

Default:

```env
ENABLE_WEB_ENRICHMENT=false
```

Enable only when you have a real Tavily key in local `.env`:

```env
ENABLE_WEB_ENRICHMENT=true
WEB_ENRICHMENT_PROVIDER=tavily
TAVILY_API_KEY=<your-tavily-api-key>
```

Safety:

- Tests use fake providers and do not call live Tavily.
- Preview builds the query and should not write catalog.
- Request stores sourced results in `web_enrichment_requests` and draft enrichment metadata.
- Suggested fields must include source URLs/provenance and confidence.
- Apply requires:

```text
confirm=APPLY_WEB_ENRICHMENT
```

- Apply updates only selected fields on the seller draft.
- Enrichment never writes `items`, `retrieval_units`, `user_profiles`, `item_item_cf_edges`, or `item_hype_profiles`.
- Seller still needs validation, indexing preview, and approve-index separately.

## 20. Jobs / Batch Workers

Batch 14.7 is a lightweight job registry/status layer, not Celery, Redis Queue, or a real async worker system.

Defaults:

```env
ENABLE_JOB_RUNS=true
ENABLE_JOB_TRIGGER_API=false
```

List registered jobs:

```bash
python scripts/run_job.py --list
```

Run a safe dry-run job without tracking:

```bash
python scripts/run_job.py --job fusion_comparison_dry_run --dry-run --no-track
```

Rules:

- App startup never runs jobs.
- Debug UI should not auto-trigger jobs.
- API job trigger remains disabled unless `ENABLE_JOB_TRIGGER_API=true`.
- Write-capable jobs keep their own confirmation strings.
- `job_runs` stores compact sanitized summaries only.

## 21. Cache / Redis

There are two separate cache concepts:

- Query Embedding Cache from Batch 14.2 wraps `process_query()`.
- Backend API cache from Batch 14.8 wraps selected read-heavy read-only endpoints.

Default backend cache:

```env
CACHE_BACKEND=none
```

Local memory cache:

```env
CACHE_BACKEND=memory
```

Optional Redis:

```env
CACHE_BACKEND=redis
REDIS_URL=redis://localhost:6379/0
```

Safety:

- App works without Redis.
- Redis package/URL/connection failures fall back safely instead of crashing normal local demo.
- Current cached API paths are compact read-only evaluation/job endpoints.
- Write endpoints are not cached.
- Secrets, admin/seller tokens, provider keys, raw events, and personalized search/feed responses are not cached.
- Rollback is `CACHE_BACKEND=none`.

## 22. Auth / Privacy

Default:

```env
AUTH_MODE=demo
```

Modes:

- `disabled`: local emergency only; do not use for shared demos.
- `demo`: public reads open; admin/write actions require token.
- `production`: token required for protected actions; this is still not full OAuth/SSO.

Public endpoints:

- `GET /api/health`
- `GET /api/users/demo`
- `POST /api/users`
- `GET /api/feed/home`
- `GET /api/search`
- `GET /api/items/{item_id}`
- `GET /api/items/{item_id}/similar`
- `POST /api/events`
- onboarding options/preview/complete, according to the user-level demo flow

Protected/admin or write-capable actions:

- Debug/Admin data and write controls.
- Demo reset/seed/rebuild controls.
- Seller approve-index.
- Enrichment request/apply.
- Job trigger API.

Confirmation strings:

| Action | Required confirmation |
| --- | --- |
| Soft demo reset | `DEMO_RESET` |
| Full demo reset | `FULL_DEMO_RESET` |
| Demo synthetic seed | `SEED_DEMO_BEHAVIOR` |
| Process events write | `PROCESS_EVENTS_WRITE` |
| Apply pending behavior write | `APPLY_PENDING_BEHAVIOR_WRITE` |
| Rebuild profiles write | `REBUILD_PROFILES_WRITE` |
| Rebuild CF write | `REBUILD_CF_WRITE` |
| Persist evaluation run | `EVAL_RUN_WRITE` |
| Seller approve-index | `INDEX_SELLER_DRAFT` |
| Apply web enrichment | `APPLY_WEB_ENRICHMENT` |

Privacy:

- Debug payloads redact secret-like fields.
- Raw-ish user identifiers and emails are masked when `PRIVACY_MASK_DEBUG_DATA=true`.
- `.env`, MongoDB URI, tokens, Tavily key, Redis URL, and passwords must not be exposed.

## 23. API Reference

Base URL:

```text
http://127.0.0.1:8000
```

### Core

| Method | Endpoint | Notes |
| --- | --- | --- |
| `GET` | `/api/health` | Health check. |
| `GET` | `/api/users/demo` | Demo users/personas. |
| `POST` | `/api/users` | Create shopper. |

### Recommendation

| Method | Endpoint | Notes |
| --- | --- | --- |
| `GET` | `/api/feed/home` | Personalized homepage feed. |
| `GET` | `/api/search` | Hybrid search and personalization. |
| `GET` | `/api/items/{item_id}` | Item detail. |
| `GET` | `/api/items/{item_id}/similar` | Semantic and CF-aware similar products. |
| `POST` | `/api/events` | Log clickstream event. |

### Onboarding

| Method | Endpoint | Notes |
| --- | --- | --- |
| `GET` | `/api/onboarding/options` | Options and seed-item candidates. |
| `POST` | `/api/onboarding/preview` | Read-only preview. |
| `POST` | `/api/onboarding/complete` | Writes `users.onboarding` and onboarding events only. |

### Evaluation

| Method | Endpoint | Notes |
| --- | --- | --- |
| `GET` | `/api/evaluation/runs/latest` | Latest persisted run or empty state. |
| `GET` | `/api/evaluation/runs` | List compact sanitized runs. |
| `GET` | `/api/evaluation/runs/{run_id}` | Run detail. |

### Jobs

| Method | Endpoint | Notes |
| --- | --- | --- |
| `GET` | `/api/jobs/registry` | Job metadata. |
| `GET` | `/api/jobs/runs` | Recent compact run status. |
| `GET` | `/api/jobs/runs/{job_run_id}` | Job detail. |
| `POST` | `/api/jobs/run` | Admin protected and disabled by default. |

### Debug/Admin

All protected by admin auth when `AUTH_MODE=demo` or `production`.

| Method | Endpoint | Write guard |
| --- | --- | --- |
| `GET` | `/api/debug/user/{user_id}` | Read-only sanitized lineage. |
| `GET` | `/api/demo/status` | Read-only collection status. |
| `POST` | `/api/demo/reset` | Soft: `write=true&confirm=DEMO_RESET`; full: `write=true&full=true&confirm=FULL_DEMO_RESET`. |
| `POST` | `/api/demo/seed` | `write=true&confirm=SEED_DEMO_BEHAVIOR`. |
| `POST` | `/api/debug/process-events` | `write=true&confirm=PROCESS_EVENTS_WRITE`. |
| `POST` | `/api/debug/apply-pending-behavior` | `write=true&confirm=APPLY_PENDING_BEHAVIOR_WRITE`; optional `user_id_hash` scopes processing to one shopper. |
| `POST` | `/api/debug/rebuild-profiles` | `write=true&confirm=REBUILD_PROFILES_WRITE`. |
| `POST` | `/api/debug/rebuild-cf` | `write=true&confirm=REBUILD_CF_WRITE`. |

Example debug write request:

```bash
curl -X POST "http://127.0.0.1:8000/api/debug/process-events?write=true&confirm=PROCESS_EVENTS_WRITE" \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN"
```

### Seller

Requires `ENABLE_SELLER_TOOLS=true`.

| Method | Endpoint | Notes |
| --- | --- | --- |
| `POST` | `/api/seller/drafts` | Create staged draft. |
| `GET` | `/api/seller/drafts` | List drafts. |
| `GET` | `/api/seller/drafts/{draft_id}` | Draft detail. |
| `POST` | `/api/seller/drafts/{draft_id}/validate` | Validate draft. |
| `POST` | `/api/seller/drafts/{draft_id}/index-preview` | Preview retrieval units. |
| `POST` | `/api/seller/drafts/{draft_id}/approve-index` | Needs `write=true&confirm=INDEX_SELLER_DRAFT`. |

### Enrichment

Requires `ENABLE_WEB_ENRICHMENT=true` and provider configuration for live request.

| Method | Endpoint | Notes |
| --- | --- | --- |
| `POST` | `/api/enrichment/seller-drafts/{draft_id}/preview` | Preview enrichment query. |
| `POST` | `/api/enrichment/seller-drafts/{draft_id}/request` | Request provider results. |
| `GET` | `/api/enrichment/requests/{request_id}` | View stored sourced results. |
| `POST` | `/api/enrichment/requests/{request_id}/apply` | Needs `confirm=APPLY_WEB_ENRICHMENT`. |

### Example Requests

Search Vietnamese:

```bash
curl "http://127.0.0.1:8000/api/search?q=tai+nghe+bluetooth&user_id_hash=u_demo_1&session_id=sess_abc&top_k=10"
```

Homepage feed:

```bash
curl "http://127.0.0.1:8000/api/feed/home?user_id_hash=u_demo_1&session_id=sess_abc&top_k=20&personalized=true"
```

Log click event:

```bash
curl -X POST "http://127.0.0.1:8000/api/events" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id_hash": "u_demo_1",
    "session_id": "sess_abc",
    "item_id": "B09XXXXX",
    "event_type": "click",
    "surface": "home",
    "request_id": "req_home_abc123"
  }'
```

Persist compact evaluation run only after human approval:

```bash
python scripts/run_personalization_evaluation.py --write-evaluation-run --confirm EVAL_RUN_WRITE
```

## 24. Troubleshooting

### MongoDB SSL handshake / timeout

Common causes:

- Current IP is not allowlisted in Atlas.
- Wrong username/password in URI.
- Wrong cluster/database.
- Cluster is paused.
- Network/VPN blocks Atlas.
- Python/OpenSSL version mismatch.

Check read-only:

```bash
python scripts/smoke_test_connection.py --counts
```

### Atlas Search index not ready

Symptoms:

- Search returns Atlas Search index errors.
- Vector or text retrieval fails.

Fix:

- Verify index names: `vector_index`, `text_index`.
- Verify both indexes are ready/active.
- Verify indexes are on `retrieval_units`.
- Verify vector dimensions are `1024`.

### Missing `datasets`

If full pytest fails in `tests/test_mvp_selection.py`:

```bash
python -m pip install datasets
```

### Python 3.14 warning

Use Python 3.10 to 3.12 for the most stable demo environment:

```bash
py -3.12 -m venv .venv
```

### Missing `ADMIN_TOKEN`

Protected admin routes may return `admin_token_not_configured`.

Generate a local token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in `.env`, restart backend, and enter it in the Debug/Admin UI when needed.

### Missing Tavily key

If web enrichment is enabled but `TAVILY_API_KEY` is empty, API should return `provider_not_configured`.

Either disable:

```env
ENABLE_WEB_ENRICHMENT=false
```

or provide a real key only in local `.env`.

### Redis unavailable

Redis is optional. Roll back:

```env
CACHE_BACKEND=none
```

Restart backend.

### Frontend build or install errors

Windows PowerShell:

```powershell
cd frontend
Remove-Item -Recurse -Force node_modules
npm install
npm run build
```

macOS/Linux:

```bash
cd frontend
rm -rf node_modules
npm install
npm run build
```

### CORS or API URL issue

Backend `.env`:

```env
CORS_ALLOW_ORIGINS=http://localhost:5173
```

Frontend `frontend/.env`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Restart both servers after changing env.

### Ollama connection refused

Start Ollama:

```bash
ollama serve
```

Verify model:

```bash
ollama list
```

Download model:

```bash
ollama pull qwen3:8b
```

### Embedding model download is slow

The first BGE-M3 run can download model weights. Keep the virtual environment active and allow enough disk space. If no GPU is available, use:

```env
USE_CUDA=false
```

### No saved shopper in dropdown

Check:

- Backend is running.
- `/api/users/demo` returns data.
- `users` collection exists in the selected database.
- Auth settings are not blocking public user routes.

### Search fails

Check:

- `retrieval_units` count is nonzero.
- `vector_index` and `text_index` are ready.
- Embedding dependencies are installed.
- Ollama is running for Vietnamese query processing.
- `MONGODB_DB_NAME` points to the expected database.

## 25. Git / What Not To Commit

Do not commit:

- `.env`
- `.venv/`
- `frontend/node_modules/`
- `frontend/dist/`
- `*.tsbuildinfo`
- `.runtime/`
- `.pytest_cache/`
- real API keys/tokens/passwords/MongoDB URI
- duplicate draft setup guide unless it has been reviewed and intentionally promoted
- personal analysis reports unless you intentionally want them in the release

Check before commit:

```bash
git status --short
git diff --stat
```

Stage only specific reviewed files. Do not stage the entire repo with a recursive/all-files command.

Recommended canonical guide staging:

```bash
git add PROJECT_SETUP_AND_FULL_RUN_GUIDE.md
```

Keep this guide as the single setup/run source of truth for GitHub/submission.

## 26. Final Submission Checklist

Before submission:

1. `.env` exists locally and is not staged.
2. `python scripts/smoke_test_connection.py --counts` passes.
3. `python scripts/reset_demo_behavior_data.py --soft --dry-run` passes.
4. `python scripts/reset_demo_behavior_data.py --full --dry-run` passes.
5. `python scripts/create_behavior_indexes.py --dry-run` passes.
6. Backend targeted tests pass.
7. Frontend build and UI tests pass.
8. Homepage/search/item/detail/similar manual flow passes.
9. Onboarding preview/skip/complete behavior is checked.
10. Seller flow is disabled by default or explicitly reviewed before enabling.
11. Enrichment is disabled by default or has a local Tavily key only in `.env`.
12. Debug/Admin auth message is clear if token is missing.
13. Evaluation dashboard handles empty/latest state.
14. Jobs panel does not auto-trigger jobs.
15. No secret appears in `git diff`.
16. No generated artifact is staged.
17. Only the canonical guide is staged for setup/run instructions.

If all checks pass, the repo is ready for a controlled commit/push.
