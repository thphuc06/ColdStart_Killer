# ColdStart Killer — Phase-by-Phase Implementation Roadmap

## Status Update - 2026-05-25

This roadmap is now partly historical.

Current repo state:

- Phases 0 through 13 have been implemented and validated for the current demo branch.
- The FastAPI-backed API and React frontend are live; any roadmap text below that says API/frontend are future phases should be read as pre-implementation planning context.
- Bundle A personalization correctness is complete; Bundle B correctness for negative suppression/search seed handling has been applied, while the qualified-CF evidence decision remains open in `RECOMMENDATION_ENHANCEMENT_PLAN_AFTER_AUDIT.md`.
- Bundle C explanation faithfulness is complete in code: structured primary-reason attribution, material-contribution badge policy, honest cold/diversity attribution, and backend-driven UI badge display are implemented without ranking tuning.
- Bundle D safety/evidence closeout is complete in code and live data: scheduler-ready pending behavior processing, component-level freshness/CF lag status, runtime-policy CF write guard, runtime-parity qualified-CF evaluation, and persisted CF lineage metadata on current-policy edges.
- After tests and read-only evaluation, an explicitly approved controlled rebuild produced v4 signal/profile lineage and current-policy CF edges sourced from signal v4.
- Bundle C is explanation-only (`explain_v3_contribution_faithful`) and requires no derived-data rebuild; its read-only `phuc_demo` sample produced `0` primary attribution mismatches across top `10` cards.
- Read-only CF comparison can be regenerated with `python scripts/run_personalization_evaluation.py --dry-run --write-artifacts --out .runtime/evaluation/bundle_b_cf_gate_<timestamp> --print-json-summary`; `.runtime` outputs are ignored local artifacts.
- Contribution-faithfulness can be rechecked with `python scripts/report_personalization_baseline.py --user-id u_api_5ea7eb5ac87d4abe --top-k 10`.
- Pending refresh can be previewed without live writes with `python scripts/process_pending_behavior.py --dry-run --max-events 100`.
- Active forward-looking scope is qualified-CF promotion only after sufficient deliberate multi-user overlap and any production scheduler/SLO rollout.
- The 2026-05-25 comparison returned `needs_more_evidence`: current CF had `278` train directional edges and `MAP@20=0.019393`, while qualified CF had `0` edges and `MAP@20=0.010767`; runtime CF policy was intentionally left unchanged during the approved lineage rebuild.
- Bundle D's runtime-parity rerun still returns `needs_more_evidence`: current CF now measures `268` train directional edges with `MAP@20=0.023210` and `NDCG@20=0.047865`, while qualified CF remains at `0` edges. A later current-policy CF rewrite refreshed live edges only to persist lineage metadata; no runtime policy switch occurred.

Use this file as:

- the historical execution roadmap for how the repo was phased,
- a reference for acceptance criteria and guardrails,
- not the primary source of current implementation status.

## 0. Purpose

This file is the implementation roadmap for the ColdStart Killer recommendation upgrade.

It is **not** the canonical design plan. The canonical design plan remains:

```text
ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md
```

This roadmap translates that plan into small, safe implementation phases that Codex/Antigravity can execute one at a time.

Use this file to:

- split work into AI-safe prompts,
- define allowed and forbidden files per phase,
- prevent accidental rewrites of the existing retrieval core,
- define phase acceptance criteria,
- define tests and human review checkpoints,
- coordinate repo code, MongoDB Atlas state, HTTP API, and React website work,
- keep MongoDB Atlas operations dry-run-first.

Do not use this roadmap to replace the canonical master plan. If this roadmap and the canonical plan conflict, stop and report the conflict before implementation.

---

## 0.1 Website-first Implementation Principle

The final product demo is a **React website**, not notebooks.

Rules:

- Notebooks may be used for exploration/debug only.
- Every backend service should eventually be callable through the HTTP API.
- Every user-facing behavior must be visible in React:
  - homepage feed,
  - search and filters,
  - product detail,
  - similar products,
  - event logging,
  - score breakdown,
  - CF evidence,
  - debug/admin lineage.
- API + frontend integration is Core Required for the final demo, not polish.
- Phase 10 and Phase 11 are required delivery phases before final demo sign-off.

Implementation consequence:

```text
If a feature only works in a script/notebook but not through API + React,
it is not demo-complete.
```

---

## 1. Source of Truth

| Source | Role |
|---|---|
| `ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md` | Canonical product/architecture plan |
| Current repo code | Source of truth for function names, imports, existing schemas, and current behavior |
| `src/search_pipeline.py` | Source of truth for existing HyPE + BM25 + `$unionWith` retrieval |
| `src/query_processor.py` | Source of truth for query fixture generation |
| `src/mongodb.py` | Source of truth for MongoDB connection lifecycle |
| `src/schemas.py` | Source of truth for existing `items` and `retrieval_units` contracts |

Conflict rule:

```text
If canonical plan and current code disagree, do not guess.
Report the mismatch and wait for human review before implementation.
```

---

## 2. Global Guardrails

These guardrails apply to every phase and every AI coding prompt.

1. **Do not rewrite `src/search_pipeline.py`.**
   - This is the working HyPE + BM25 + `$unionWith` RRF core.
   - Personalized search must call existing search, then lightly rerank returned candidates.

2. **Do not rewrite `src/query_processor.py`.**
   - Reuse or wrap `process_query()`.
   - Do not add a second query-processing path.

3. **Do not rewrite `src/indexing.py`.**
   - Existing dataset/LLM/embedding/indexing flow remains protected.

4. **Do not change `items` or `retrieval_units` contracts without a separate reviewed phase.**

5. **Do not duplicate MongoDB connector logic.**
   - Extend `src/mongodb.py`.
   - Do not create a parallel `MongoClient`.
   - Do not create `src/storage/mongo.py` if it only duplicates `src/mongodb.py`.

6. **Do not call semantic similarity Collaborative Filtering.**
   - HyPE/profile/semantic neighbors = semantic/content-based personalization.
   - True CF = `item_item_cf_edges` built from multi-user `user_item_signals`.

7. **Do not seed perfect `user_profiles` directly.**
   - Correct flow:

```text
synthetic_personas
  -> recommendation_logs
  -> clickstream_events
  -> user_item_signals
  -> user_profiles
  -> item_item_cf_edges
```

8. **Do not run realtime all-pair CF.**
   - `item_item_cf_edges` must be batch/precomputed.

9. **Do not let profile override query intent.**
   - Search is query-first.
   - Profile/CF only rerank inside an already query-relevant candidate set.

10. **Do not let React duplicate impressions.**
    - One surface view has one stable `request_id`.
    - Impression idempotency uses `idempotency_key` or partial unique index.
    - Do not create a global unique `{request_id,item_id,event_type}` constraint for all event types.

11. **Do not one-shot implement the full update.**
    - Each phase must pass tests and human review before the next phase.

12. **Do not edit real `.env` secrets.**
    - Update `.env.example` or docs only in the relevant phase.

13. **Do not run live migrations/index creation/seeding by default.**
    - Scripts must support dry-run first.
    - Live writes require explicit human confirmation.

---

## 3. Current Repo Audit Summary

### 3.1 Repo Structure

Current top-level structure verified from repo:

```text
src/                         # Python core modules
scripts/                     # CLI/data/evaluation scripts
tests/                       # pytest suite
evaluation/                  # retrieval queries/judgments/docs
notebooks/                   # build/demo/evaluation notebooks
prompts/                     # LLM prompt templates
assets/                      # diagrams
analysis/                    # local/generated data artifacts, gitignored by pattern
data/                        # local/generated data artifacts, gitignored
README.md
RUNBOOK.md
TESTING.md
requirements.txt
.env.example
.gitignore
ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md
```

### 3.2 Existing MongoDB Usage

Verified file: `src/mongodb.py`.

Existing functions:

```text
get_mongo_client()
get_database()
get_items_collection()
get_retrieval_units_collection()
ping_mongodb()
collection_counts()
```

Current connector behavior:

- uses `MongoClient` from `pymongo`,
- caches client with `@lru_cache(maxsize=1)`,
- database name comes from `get_settings().mongodb_db_name`,
- URI comes from `MONGODB_URI`,
- timeout comes from `MONGODB_TIMEOUT_MS`.

Implementation consequence:

```text
All new collection getters must be added to src/mongodb.py.
No new MongoClient should be created elsewhere.
```

### 3.3 Existing Config / Env Usage

Verified file: `src/config.py`.

Current settings:

```text
MONGODB_URI
MONGODB_DB_NAME
OLLAMA_MODEL
EMBEDDING_MODEL
USE_CUDA
EMBEDDING_STORAGE_FORMAT
DEFAULT_INDEX_LIMIT
M0_SAFE_LIMIT
DEDICATED_FULL_LIMIT
MONGODB_TIMEOUT_MS
```

Verified `.env.example` includes the same core settings except `MONGODB_TIMEOUT_MS` was not present in the sample file at audit time.

Real `.env` exists locally but was not printed or included in this roadmap.

### 3.4 Existing Schemas

Verified file: `src/schemas.py`.

Existing Pydantic models:

```text
TextStats
ColdStartState
DescriptionEnriched
SourceText
ItemDocument
RetrievalUnitBase
HypeRetrievalUnit
PropositionRetrievalUnit
to_mongo_dict()
```

Existing collections covered:

- `items`
- `retrieval_units`

Recommendation upgrade schemas can be added either:

1. to `src/schemas.py` if the team wants one schema file, or
2. to new focused modules such as `src/behavior/schemas.py` and `src/recommendation/schemas.py`.

Recommendation:

```text
Use focused new schema modules for behavior/recommendation collections,
but do not duplicate existing ItemDocument/RetrievalUnit contracts.
```

### 3.5 Existing Retrieval / Search Flow

Verified files:

```text
src/query_processor.py
src/search_pipeline.py
src/retrieval_output.py
scripts/run_search.py
tests/test_pipeline.py
```

Important functions to reuse:

```text
src.query_processor.process_query(raw_query: str) -> dict
src.search_pipeline.run_search(fixture: dict, top_k: int = 10, mode: "unionWith", collection=None) -> list[dict]
src.search_pipeline.build_union_with_pipeline(...)
src.retrieval_output.build_explainable_result(result: dict) -> dict
src.retrieval_output.build_explainable_results(results: list[dict]) -> list[dict]
```

Fixture shape consumed by search:

```json
{
  "original_query": "string",
  "hype_search_query_en": "string",
  "bm25_search_query_en": "string",
  "hard_filters": {
    "in_stock": true,
    "price_max": 500000
  },
  "query_embedding": [1024 floats]
}
```

Current search constants from code:

```text
VECTOR_INDEX_NAME = "vector_index"
TEXT_INDEX_NAME = "text_index"
RRF_K = 60
EMBEDDING_DIM = 1024
VECTOR_NUM_CANDIDATES = 400
VECTOR_CHANNEL_LIMIT = 20
BM25_CHANNEL_LIMIT = 20
DEFAULT_TOP_K = 10
DEFAULT_WEIGHTS = {"vector": 0.60, "bm25": 0.40}
```

Important current behavior:

- `run_search()` defaults to `mode="unionWith"`.
- `is_rank_fusion_unavailable()` always returns `True`.
- BM25 exact filters are handled after `$search`, not inside `compound.filter`.
- Search results are explainable but not personalized yet.

### 3.6 Existing Embeddings

Verified file: `src/embeddings.py`.

Important functions:

```text
load_embedding_model()
embed_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]
embed_one(text: str) -> list[float]
estimate_vector_memory(num_vectors: int, dimensions: int = 1024) -> dict
```

Important behavior:

- model name comes from `EMBEDDING_MODEL`, default `BAAI/bge-m3`,
- embeddings are normalized (`normalize_embeddings=True`),
- vectors are validated as 1024-dimensional,
- model loading is lazy via `load_embedding_model()`.

Implementation consequence:

```text
All new embedding work should reuse src.embeddings.
Do not create a second embedding model path.
```

### 3.7 Existing Indexing

Verified file: `src/indexing.py`.

Important functions:

```text
build_item_doc_from_mvp_row(row)
build_contextual_header(item)
build_proposition_units(item, propositions)
build_hype_units(item, hype_queries, embeddings)
estimate_indexing_size(df)
first_uninserted_index_from_mongodb(df)
index_items_from_dataframe(...)
```

Verified script:

```text
scripts/index_mvp.py
```

Important behavior:

- builds `items`,
- builds proposition `retrieval_units`,
- builds HyPE `retrieval_units`,
- uses Qwen/Ollama and BGE-M3 embeddings,
- dry-run is default unless `--write` is passed.

Implementation consequence:

```text
Do not modify indexing flow for recommendation behavior features.
```

### 3.8 Existing Evaluation

Verified directory:

```text
src/evaluation/
evaluation/
scripts/run_evaluation.py
scripts/run_eval_diagnostics.py
```

Existing evaluation capabilities:

- diagnostic probes,
- query fixture generation,
- retrieval variants,
- NDCG/Precision/Recall/MRR/HitRate,
- cold-start quality metrics,
- reporting/hackathon report generation.

Important functions/modules:

```text
src.evaluation.metrics.compute_query_metrics()
src.evaluation.metrics.aggregate_metrics()
src.evaluation.runner.run_evaluation()
src.evaluation.variants.run_variant()
```

Implementation consequence:

```text
Personalization/CF evaluation should extend src/evaluation,
not replace the existing retrieval evaluation framework.
```

### 3.9 Existing Requirements

Verified `requirements.txt` currently includes:

```text
pymongo
pandas
datasets
pyarrow
python-dotenv
sentence-transformers
torch
pydantic
tqdm
ollama
numpy
pytest
ipykernel
```

Missing for planned API/frontend workflow:

```text
fastapi
uvicorn
httpx
```

Frontend dependencies do not exist yet because no `frontend/` directory exists at audit time.

### 3.10 Current MongoDB Atlas Assumptions

Verified from code/docs:

```text
database default: coldstart_killer
existing collections: items, retrieval_units
vector index name: vector_index
text index name: text_index
```

Live Atlas index definitions were **not verified from repo yet** in this task. Do not assume live index state beyond what code/docs say.

Existing live counts documented in the canonical plan:

```text
items: 3,000
retrieval_units: 29,753
HyPE units: 13,580
proposition units: 16,173
categories: All_Beauty, Cell_Phones_and_Accessories
```

### 3.11 Missing Pieces for the Upgrade

Not currently implemented:

- behavior collection getters,
- behavior/recommendation schemas,
- behavior indexes script,
- `item_hype_profiles` builder,
- recommendation attribution writer,
- clickstream logger,
- synthetic behavior generator,
- `user_item_signals` builder,
- `user_profiles` builder,
- `item_item_cf_edges` builder,
- `item_semantic_neighbors` builder,
- personalized ranking services,
- HTTP API layer,
- React frontend,
- personalization/CF evaluation,
- demo reset/recovery scripts.

---

## 4. Environment & Dependency Plan

### 4.1 Python Backend Dependencies

| Package | Current? | Needed for | Phase | Required? | Notes |
|---|---:|---|---:|---:|---|
| `pymongo` | yes | MongoDB access | all backend phases | yes | Already used by `src/mongodb.py` |
| `pydantic` | yes | schemas/validation | 1+ | yes | Existing repo uses Pydantic models |
| `python-dotenv` | yes | `.env` loading | all backend phases | yes | Already used by `src/config.py` |
| `numpy` | yes | vector math/scoring | 2, 6, 8, 9 | yes | Avoid heavy extra math deps |
| `pandas` | yes | data scripts/evaluation | existing + 12 | yes | Existing indexing/evaluation use it |
| `pytest` | yes | tests | all phases | yes | Existing test suite |
| `sentence-transformers` | yes | BGE-M3 embeddings | existing + 2/4 if embedding needed | yes on teammate machine | Do not import in API route modules at import time |
| `torch` | yes | embedding backend | existing | yes on teammate machine | Avoid loading in search-only tests |
| `ollama` | yes | Qwen translation/generation | existing query/indexing | yes on teammate machine | API should fail clearly if unavailable |
| `fastapi` | no | HTTP API layer | 10 | yes for recommended API adapter | Add when Phase 10 begins |
| `uvicorn` | no | local API server | 10 | yes for FastAPI dev server | `uvicorn[standard]` optional |
| `httpx` | no | API tests | 10+ | recommended | Better for FastAPI test client workflows |
| `tqdm` | yes | batch script progress | 2, 4, 7, 8 | optional | Already installed |

Do not add heavy packages such as Spark, Redis clients, vector DB SDKs, or ML training frameworks unless a future phase explicitly requires them.

### 4.2 Frontend Dependencies

Historical planning note: this section was written before Phase 11 shipped.

The frontend now exists under `frontend/` and the current package/source-of-truth state lives in `frontend/package.json`.

Keep the table below as dependency rationale and phase-planning context, not as the latest implementation status snapshot.

| Package | Purpose | Needed immediately? | Phase | Notes |
|---|---|---:|---:|---|
| `react` | UI runtime | yes | 11 | Via Vite template |
| `react-dom` | browser rendering | yes | 11 | Via Vite template |
| `vite` | frontend dev/build tool | yes | 11 | Use React + TypeScript template |
| `typescript` | typed frontend | yes | 11 | Keep UI contracts safer |
| `tailwindcss` | styling | recommended | 11 | Good hackathon speed/quality |
| `shadcn/ui` | component system | recommended | 11 | Can be added gradually |
| `react-router-dom` | pages/routes | recommended | 11 | Needed for home/search/detail/debug |
| `@tanstack/react-query` | API state/cache | recommended | 11 | Helps avoid duplicate fetch logic |
| `lucide-react` | icons | recommended | 11 | Lightweight icon set |
| chart library | debug/eval charts | optional | 12/13 | Use only if debug panel needs charts |

### 4.3 `.env` Variables

Existing env variables detected from `src/config.py` and `.env.example`:

```text
MONGODB_URI
MONGODB_DB_NAME
OLLAMA_MODEL
EMBEDDING_MODEL
USE_CUDA
EMBEDDING_STORAGE_FORMAT
DEFAULT_INDEX_LIMIT
M0_SAFE_LIMIT
DEDICATED_FULL_LIMIT
MONGODB_TIMEOUT_MS
```

Proposed backend env variables for later phases:

```text
VECTOR_INDEX_NAME=vector_index
TEXT_INDEX_NAME=text_index
API_HOST=127.0.0.1
API_PORT=8000
DEMO_MODE=true
ENABLE_PERSONALIZATION=true
ENABLE_EVENT_LOGGING=true
ALGORITHM_VERSION=rec_v1_profile_cf_hype
RANKING_VERSION=rank_v1_default_weights
EVENT_TTL_DAYS=0
CORS_ALLOW_ORIGINS=http://localhost:5173
```

Proposed frontend env variables:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_DEMO_MODE=true
```

Rules:

- Do not edit real `.env`.
- Update `.env.example` only in the phase that introduces the setting.
- Never commit secrets.
- Keep demo toggles explicit.
- `src/config.py` may be updated in Phase 1 or Phase 10 when typed settings are needed.
- Only add new settings with safe defaults.
- Do not change the semantics of existing environment variables.
- Do not print secrets.
- If typed config is not needed immediately, defer `src/config.py` changes until the phase that actually uses the setting.

### 4.4 MongoDB Atlas Live Setup

Existing assets to keep:

```text
database: coldstart_killer
collections: items, retrieval_units
Atlas vector index: vector_index
Atlas text index: text_index
```

New collections planned:

```text
users
sessions
recommendation_logs
clickstream_events
user_item_signals
user_profiles
item_hype_profiles
item_semantic_neighbors
item_item_cf_edges
item_stats
query_embedding_cache
synthetic_personas
evaluation_runs
```

Index creation rules:

- create a dry-run script first,
- dry-run prints exact index specs,
- live creation requires explicit `--write` or `--apply`,
- do not drop existing indexes,
- do not alter `items` / `retrieval_units` indexes unless a separate reviewed phase says so.

TTL rule:

```text
For demo, TTL should be disabled or long enough to avoid deleting seeded behavior before judging.
For production, use TTL/archive policies according to privacy requirements.
```

Vector Search rule:

```text
Reuse existing retrieval_units vector index for semantic neighbor building if possible.
Do not create a new vector index unless profiling proves it is required.
```

---

## Requirements Update Plan

### Backend Python Requirements

| Package | Add in phase | Why | Risk / note |
|---|---:|---|---|
| `fastapi` | 10 | HTTP API adapter for React | Keep business logic outside routes |
| `uvicorn` | 10 | Local API server | Use only for serving API |
| `httpx` | 10 | API tests | Lightweight test client |

Existing backend packages should remain unchanged until a phase requires a new dependency.

### Dev/Test Requirements

| Package | Current? | Add in phase | Why |
|---|---:|---:|---|
| `pytest` | yes | existing | unit/integration tests |
| `ipykernel` | yes | existing | notebooks |
| `httpx` | no | 10 | API tests |

### Frontend Requirements

Frontend dependencies belong in `frontend/package.json`, not `requirements.txt`.

| Package | Add in phase | Why |
|---|---:|---|
| `react` / `react-dom` | 11 | UI |
| `vite` | 11 | dev/build |
| `typescript` | 11 | UI type safety |
| `tailwindcss` | 11 | styling |
| `react-router-dom` | 11 | routes |
| `@tanstack/react-query` | 11 | API state |
| `lucide-react` | 11 | icons |

### Optional / Future Requirements

| Package / system | Phase | Why | Note |
|---|---:|---|---|
| Redis | future | cache/session speed | Not needed for hackathon MVP |
| Celery/RQ | future | async jobs | Batch scripts are enough first |
| chart library | 12/13 | dashboard charts | Only if debug UI needs it |

---

## Environment Variable Plan

### Existing Variables

Detected from code/config:

```text
MONGODB_URI
MONGODB_DB_NAME
OLLAMA_MODEL
EMBEDDING_MODEL
USE_CUDA
EMBEDDING_STORAGE_FORMAT
DEFAULT_INDEX_LIMIT
M0_SAFE_LIMIT
DEDICATED_FULL_LIMIT
MONGODB_TIMEOUT_MS
```

### Backend Variables to Add Later

```text
VECTOR_INDEX_NAME
TEXT_INDEX_NAME
API_HOST
API_PORT
DEMO_MODE
ENABLE_PERSONALIZATION
ENABLE_EVENT_LOGGING
ALGORITHM_VERSION
RANKING_VERSION
EVENT_TTL_DAYS
CORS_ALLOW_ORIGINS
```

### Frontend Variables to Add Later

```text
VITE_API_BASE_URL
VITE_DEMO_MODE
```

### Rules

- Update `.env.example` and docs, not real `.env`.
- Do not print secrets.
- Do not commit `.env`.
- Keep defaults safe for local demo.
- `src/config.py` is allowed in Phase 1/10 only when typed backend settings are needed.
- New config fields must have safe defaults and must not alter existing env behavior.

---

## MongoDB Atlas Live Checklist

For step-by-step live operations, use **MongoDB Atlas Live Operations Playbook** below. This checklist defines what must exist; the playbook defines the safe order of operations.

### Existing Atlas Assets to Keep

| Asset | Expected |
|---|---|
| Database | `coldstart_killer` |
| Collection | `items` |
| Collection | `retrieval_units` |
| Vector index | `vector_index` |
| Text index | `text_index` |

Live index definitions were not verified from repo yet. Confirm in Atlas before live demo.

### New Collections to Create

```text
users
sessions
recommendation_logs
clickstream_events
user_item_signals
user_profiles
item_hype_profiles
item_semantic_neighbors
item_item_cf_edges
item_stats
query_embedding_cache
synthetic_personas
evaluation_runs
```

### New Indexes

Recommended index specs:

```javascript
db.users.createIndex({ user_id_hash: 1 }, { unique: true })
db.users.createIndex({ profile_status: 1 })

db.sessions.createIndex({ session_id: 1 }, { unique: true })
db.sessions.createIndex({ user_id_hash: 1, started_at: -1 })

db.recommendation_logs.createIndex({ request_id: 1, item_id: 1 }, { unique: true })
db.recommendation_logs.createIndex({ user_id_hash: 1, shown_at: -1 })
db.recommendation_logs.createIndex({ session_id: 1, shown_at: -1 })
db.recommendation_logs.createIndex({ item_id: 1, shown_at: -1 })
db.recommendation_logs.createIndex({ surface: 1, shown_at: -1 })
db.recommendation_logs.createIndex({ algorithm_version: 1, ranking_version: 1 })

db.clickstream_events.createIndex({ event_id: 1 }, { unique: true })
db.clickstream_events.createIndex(
  { idempotency_key: 1 },
  { unique: true, partialFilterExpression: { idempotency_key: { $exists: true } } }
)
db.clickstream_events.createIndex(
  { request_id: 1, item_id: 1 },
  { unique: true, partialFilterExpression: { event_type: "impression" } }
)
db.clickstream_events.createIndex({ request_id: 1, item_id: 1, event_type: 1 })
db.clickstream_events.createIndex({ user_id_hash: 1, timestamp: -1 })
db.clickstream_events.createIndex({ session_id: 1, timestamp: -1 })
db.clickstream_events.createIndex({ item_id: 1, event_type: 1, timestamp: -1 })
db.clickstream_events.createIndex({ processed: 1, timestamp: 1 })
// TTL optional/disabled for demo; long TTL only if needed.

db.user_item_signals.createIndex({ user_id_hash: 1, item_id: 1 }, { unique: true })
db.user_item_signals.createIndex({ user_id_hash: 1, implicit_score: -1 })
db.user_item_signals.createIndex({ item_id: 1, implicit_score: -1 })
db.user_item_signals.createIndex({ updated_at: -1 })

db.user_profiles.createIndex({ user_id_hash: 1 }, { unique: true })
db.user_profiles.createIndex({ profile_status: 1 })
db.user_profiles.createIndex({ updated_at: -1 })

db.item_hype_profiles.createIndex({ item_id: 1 }, { unique: true })
db.item_hype_profiles.createIndex({ category_id: 1 })
db.item_hype_profiles.createIndex({ updated_at: -1 })

db.item_semantic_neighbors.createIndex({ item_id: 1 }, { unique: true })

db.item_item_cf_edges.createIndex({ item_id: 1, neighbor_item_id: 1 }, { unique: true })
db.item_item_cf_edges.createIndex({ item_id: 1, cf_score: -1 })
db.item_item_cf_edges.createIndex({ support: -1 })

db.item_stats.createIndex({ item_id: 1 }, { unique: true })
db.item_stats.createIndex({ interaction_count: -1 })

db.query_embedding_cache.createIndex({ query_hash: 1 }, { unique: true })
```

### Atlas Vector Search

- Reuse `retrieval_units` `vector_index` for query retrieval and semantic neighbor build.
- No new vector index is required for the first implementation path.
- If future profiling shows `item_hype_profiles.item_semantic_embedding` needs direct vector search, create a separate phase and human review.

### Safety

- No `dropCollection`.
- No `dropIndex`.
- No destructive reset on production DB.
- Dry-run index script first.
- Human confirmation required for live index creation.
- Phase 8 may be skipped temporarily if Atlas Vector Search is unavailable or `vector_index` is not ready.
- Do not create a new vector index automatically.
- Do not brute-force all item-by-item semantic similarity locally.

---

## Post-Phase 1 Human Atlas Apply Checkpoint

This checkpoint is not a coding phase. It is a required human gate after Phase 1 and before any live write in Phase 2/3/4/5+.

Detailed Atlas UI and command-order instructions are in **MongoDB Atlas Live Operations Playbook**. Do not apply behavior indexes live until that playbook's Sections 2-6 have been completed.

### Purpose

Phase 1 creates collection contracts and dry-run index specs. Before later phases write real data, the team must confirm that the live Atlas database is ready. This avoids the failure mode where code is correct but Atlas is missing collections, indexes, or points to the wrong database.

### Checklist

- Confirm `MONGODB_URI` points to the correct Atlas cluster.
- Confirm `MONGODB_DB_NAME` points to the intended database.
- Confirm existing collections:
  - `items`
  - `retrieval_units`
- Confirm existing indexes:
  - `vector_index`
  - `text_index`
- Run:

```bash
python scripts/create_behavior_indexes.py --dry-run
```

- Human reviews the dry-run output.
- Apply only after approval:

```bash
python scripts/create_behavior_indexes.py --write
```

- Verify indexes exist in Atlas UI or by a non-destructive list-index command.
- Confirm TTL policy for demo:
  - disabled, or
  - long enough that seeded behavior will not disappear before judging.
- Confirm no `dropCollection` or `dropIndex` operation exists in the script.

### Required Before

- Phase 3 event logger live test.
- Phase 4 synthetic seed live write.
- Phase 5+ builders using live DB.

### Stop Conditions

- Atlas index creation fails.
- DB name is wrong.
- Existing `items` or `retrieval_units` collection is missing.
- Existing `vector_index` or `text_index` is missing.
- Dry-run output includes destructive operations.

---

## MongoDB Atlas Live Operations Playbook

### 1. Purpose

This playbook is for real MongoDB Atlas operations.

The checklist above says **what must be checked**. This playbook says **which order to follow** when touching a live Atlas cluster. Its goal is to keep repo code, Atlas live data, the HTTP API, and the React website synchronized.

Use this playbook before:

- applying behavior indexes,
- writing `item_hype_profiles`,
- seeding synthetic behavior,
- building signals/profiles/CF,
- resetting demo data,
- running the React website against live Atlas data.

### 2. Atlas Environment Separation

Recommended database names:

```text
coldstart_killer_dev
coldstart_killer_demo
coldstart_killer_judging
```

Important:

- If the repo currently uses `coldstart_killer`, do not change the DB name in code.
- DB selection must go through `.env` via `MONGODB_DB_NAME`.
- Before every seed/reset/build command, confirm the terminal prints the intended database name.
- Never run reset/seed scripts unless the terminal prints the intended database name and a human confirms it.

Minimum environment policy:

| Environment | Purpose | Reset allowed? |
|---|---|---|
| local/dev | experiments and AI-generated code validation | yes, with dry-run first |
| demo | stable hackathon demo data | soft reset yes, full reset only with confirmation |
| judging/final | final recorded or submitted state | avoid reset; use backup/export first |

### 3. Atlas Access Setup

#### 3.1 Cluster Check

1. Log in to MongoDB Atlas.
2. Select the correct Atlas project.
3. Select the correct cluster.
4. Confirm cluster status is running/available.
5. Confirm the cluster is the one referenced by local `MONGODB_URI`.

Stop if the selected cluster does not match the intended demo cluster.

#### 3.2 Network Access / IP Access List

1. Open **Network Access**.
2. Add the current IP address.
3. For team demo work, add each teammate's current IP if needed.
4. Avoid `0.0.0.0/0` unless absolutely necessary.
5. If `0.0.0.0/0` is used temporarily for testing/demo, remove it after the session.

Common failure if this is wrong:

```text
ServerSelectionTimeoutError
```

#### 3.3 Database Access User

1. Open **Database Access**.
2. Confirm the database user exists.
3. Confirm the user has read/write permissions on the target DB.
4. Confirm the user can create indexes on the target DB.

Recommended role:

```text
readWrite on target database
plus index creation permission if Atlas role configuration requires it
```

Rules:

- Do not use admin/root credentials in `.env` unless there is no safe alternative.
- Do not commit username/password.
- Do not paste real credentials into chat, reports, or docs.

#### 3.4 Connection String

1. Copy the SRV connection string from Atlas.
2. Put it into local `.env` as `MONGODB_URI`.
3. Set `MONGODB_DB_NAME` explicitly.
4. Do not paste a password-bearing URI into Git, chat, screenshots, or reports.

### 4. Pre-flight Local Connection Verification

Before running any live script:

1. Confirm local `.env` exists.
2. Confirm `.env.example` contains no secrets.
3. Run the repo's read-only smoke test:

```bash
python scripts/smoke_test_connection.py --counts
```

If that script does not exist in a future branch, use the repo's equivalent read-only count command. If no equivalent exists, Phase 1 should add or document one safely.

Pre-flight must verify:

- cluster is reachable,
- database name is correct,
- `items` count > 0,
- `retrieval_units` count > 0,
- HyPE units exist,
- proposition units exist.

Stop conditions:

- DB name is wrong.
- `items` count is 0.
- `retrieval_units` count is 0.
- live smoke test cannot connect.

### 5. Existing Search Index Verification

#### 5.1 Atlas UI Verification

1. Atlas -> Database -> Browse Collections.
2. Open `retrieval_units`.
3. Open Search Indexes / Atlas Search.
4. Confirm:

```text
vector_index
text_index
```

#### 5.2 Code/Docs Consistency

Confirm code constants still match:

```text
VECTOR_INDEX_NAME = "vector_index"
TEXT_INDEX_NAME = "text_index"
```

#### 5.3 Stop Conditions

- If `vector_index` is missing, do not run Phase 8 semantic neighbors.
- If `text_index` is missing, search/BM25 may fail.
- Do not create a new vector/text index automatically.
- If a new search index is needed, create a separate reviewed phase.

### 6. Behavior Collections and Index Apply Procedure

Run dry-run:

```bash
python scripts/create_behavior_indexes.py --dry-run
```

Human review must check:

- target DB name is printed,
- collection names are correct,
- unique indexes are correct,
- partial unique impression index exists,
- TTL is disabled or long enough for demo,
- no `dropCollection`,
- no `dropIndex`.

Apply only after approval:

```bash
python scripts/create_behavior_indexes.py --write
```

Verify in Atlas UI or with a non-destructive list-index command:

- `recommendation_logs` unique `{request_id, item_id}`,
- `clickstream_events` unique `event_id`,
- `clickstream_events` partial unique `idempotency_key`,
- `clickstream_events` partial unique impression index,
- `user_item_signals` unique `{user_id_hash, item_id}`,
- `item_hype_profiles` unique `item_id`,
- `item_item_cf_edges` unique `{item_id, neighbor_item_id}`.

Stop conditions:

- script does not print target DB name,
- dry-run output includes `dropCollection` or `dropIndex`,
- partial unique impression index is missing,
- live apply fails,
- any behavior index is created on the wrong DB.

### 7. Live Data Build Order on Atlas

These command names are expected future commands from this roadmap. If implementation uses different names, update this playbook.

Step 0 — Confirm target DB:

```text
Script prints current DB name.
Human confirms.
```

Step 1 — Existing retrieval data:

```bash
python scripts/smoke_test_connection.py --counts
```

Step 2 — Behavior indexes:

```bash
python scripts/create_behavior_indexes.py --dry-run
python scripts/create_behavior_indexes.py --write
```

Step 3 — Build `item_hype_profiles`:

```bash
python scripts/build_item_hype_profiles.py --dry-run --limit 5
python scripts/build_item_hype_profiles.py --write
```

Step 4 — Seed synthetic behavior:

```bash
python scripts/seed_synthetic_clickstream.py --dry-run --users 5
python scripts/seed_synthetic_clickstream.py --write
```

Step 5 — Build `user_item_signals` + `item_stats`:

```bash
python scripts/build_user_item_signals.py --dry-run --limit 100
python scripts/build_user_item_signals.py --write --rebuild-item-stats
```

Step 6 — Build `user_profiles`:

```bash
python scripts/build_user_profiles.py --dry-run --limit-users 5
python scripts/build_user_profiles.py --write
```

Step 7 — Build `item_item_cf_edges`:

```bash
python scripts/build_item_item_cf.py --dry-run --limit-users 20
python scripts/build_item_item_cf.py --write --replace-existing
```

Step 8 — Build `item_semantic_neighbors` optional:

```bash
python scripts/build_item_semantic_neighbors.py --dry-run --limit 5
python scripts/build_item_semantic_neighbors.py --write
```

If Phase 8 fails because Atlas Vector Search is unavailable:

```text
mark semantic neighbors unavailable
continue with Phase 9 fallback
do not brute force
do not create a new vector index automatically
```

Step 9 — Start API:

```bash
python -m uvicorn src.api.app:app --reload
```

Step 10 — Start React:

```bash
cd frontend
npm run dev
```

Step 11 — Run evaluation:

```bash
python scripts/run_personalization_evaluation.py --dry-run
```

### 8. Atlas Verification Commands / Checks

| Check | What to verify | Command / UI |
|---|---|---|
| DB target | correct DB name | script prints DB |
| items count | > 0 | `python scripts/smoke_test_connection.py --counts` or Atlas UI |
| retrieval_units count | > 0 | smoke test or Atlas UI |
| behavior indexes | exist | Atlas UI / list indexes |
| item_hype_profiles | count reasonable | builder summary |
| clickstream_events | seeded count > 0 | seed summary |
| user_item_signals | count > 0 | builder summary |
| user_profiles | demo users exist | builder summary |
| item_item_cf_edges | support edges exist | CF builder summary |
| API | health/feed works | browser/curl |
| React | homepage/search works | browser |

### 9. Safe Reset Procedure

Command names are expected future commands from this roadmap.

#### Soft Reset

Use soft reset to clear live demo interactions while keeping precomputed data needed for quick recovery.

Deletes, depending on script mode:

```text
current demo recommendation_logs
current demo clickstream_events
current demo user_item_signals
current demo user_profiles
current demo item_stats
```

Keeps:

```text
items
retrieval_units
item_hype_profiles
item_semantic_neighbors
seeded/precomputed item_item_cf_edges if quick recovery needs them
```

Example:

```bash
python scripts/reset_demo_behavior_data.py --soft --dry-run
python scripts/reset_demo_behavior_data.py --soft --write --confirm DEMO_RESET
```

#### Full Reset

Use full reset to replay the full behavior -> signal -> profile -> CF pipeline.

Deletes behavior-derived collections:

```text
recommendation_logs
clickstream_events
user_item_signals
user_profiles
item_stats
item_item_cf_edges
```

Optionally deletes if rebuilding:

```text
item_semantic_neighbors
```

Never deletes:

```text
items
retrieval_units
```

Example:

```bash
python scripts/reset_demo_behavior_data.py --full --dry-run
python scripts/reset_demo_behavior_data.py --full --write --confirm FULL_DEMO_RESET
```

Required protections:

- dry-run default,
- script prints target DB,
- `--write` required for live changes,
- confirmation flag/string required,
- never run destructive reset on production/final judging DB unless explicitly approved.

### 10. Common Atlas Failure Modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `ServerSelectionTimeoutError` | IP not whitelisted or wrong URI | add IP, verify URI |
| Authentication failed | wrong username/password | reset DB user password |
| not authorized to create index | insufficient role | update DB user role |
| collection count 0 | wrong DB name | fix `MONGODB_DB_NAME` |
| vector search fails | missing `vector_index` | verify Atlas Search index |
| BM25 search fails | missing `text_index` | verify Atlas Search index |
| duplicate key on impression | idempotency works or bad key | check event idempotency |
| seed created no CF edges | insufficient overlap | adjust personas/anchor items |
| API returns empty feed | missing profiles/CF/stats or fallback bug | check Gates C-E |
| React logs duplicate impressions | request_id lifecycle bug | inspect frontend state/idempotency |
| reset deleted too much | wrong DB or unsafe reset | restore backup/reseed |

### 11. Atlas Backup / Export Recommendation

Before full reset or large seed:

- export/snapshot if the DB is important,
- for Atlas free/demo, at least export critical docs/counts,
- prefer a separate `coldstart_killer_demo` DB for experiments,
- never reset production/final judging DB without backup and explicit approval.

---

## 5. Phase Overview Table

| Phase | Goal | Priority | Depends on | Output | Risk | AI implementation |
|---:|---|---|---|---|---|---|
| 0 | Repo Audit & Guardrails | Guardrail | none | audit summary, mismatch list | low | yes |
| 1 | Data Models, MongoDB Getters, Index Specs | Core Required | 0 | getters, schemas, dry-run index script | medium | careful |
| 2 | Item HyPE Profiles Builder | Core Required | 1 | `item_hype_profiles` | medium | careful |
| 3 | Behavior Logging & Recommendation Attribution | Core Required | 1 | loggers for snapshots/events | high | careful |
| 4 | Synthetic Behavior Seed Data | Core Required | 2, 3 | synthetic logs/events | high | careful |
| 5 | User Item Signals + Item Stats Builder | Core Required | 3, 4 | `user_item_signals`, `item_stats` | medium | yes |
| 6 | User Profiles Builder | Core Required | 2, 5 | `user_profiles` | high | careful |
| 7 | Item-item Collaborative Filtering | Core Required | 5 | `item_item_cf_edges` | high | careful |
| 8 | Item Semantic Neighbors | Strongly Recommended | 2 | `item_semantic_neighbors` | medium | careful |
| 9 | Personalized Ranking Services | Core Required | 2, 3, 6, 7; Phase 8 optional | homepage/search/similar services | high | careful |
| 10 | HTTP API Layer | Core Required | 9 | API routes for React | medium | yes |
| 11 | React Frontend | Core Required | 10 | shopping UI | high | careful |
| 12 | Evaluation & Demo Proof | Core Required | 4-9 | personalization/CF evaluation | medium | careful |
| 13 | Demo Reset/Recovery & Polish | Strongly Recommended | 3-12 | soft/full reset and admin controls | medium | yes |
| 14 | Future Enhancements | Future | stable demo | optional polish | variable | careful |

Notes:

- The Post-Phase 1 Human Atlas Apply Checkpoint is required before any live data-writing phase.
- Phase 8 is Strongly Recommended but can be skipped temporarily if Atlas Vector Search is not ready.
- Phase 9 must support fallback ranking when `item_semantic_neighbors` is unavailable.
- Phase 10 and Phase 11 are Core Required because the final demo is website-first.

---

## 6. Repo / Atlas / Website Synchronization Matrix

| Subsystem | Repo files/modules | MongoDB Atlas collections/indexes | Env/config | Website/API dependency | Validation command/check |
|---|---|---|---|---|---|
| Existing search core | `src/query_processor.py`, `src/search_pipeline.py`, `src/retrieval_output.py` | `items`, `retrieval_units`, `vector_index`, `text_index` | `MONGODB_*`, `EMBEDDING_MODEL` | API search route wraps it | `python -m pytest tests/test_pipeline.py -v` |
| Item HyPE profiles | `src/recommendation/item_hype_profiles.py`, builder script | `item_hype_profiles` | none required | homepage/similar/search services read it | dry-run builder count + vector validation |
| Recommendation logs | `src/behavior/event_logger.py` | `recommendation_logs` unique `request_id,item_id` | `ALGORITHM_VERSION`, `RANKING_VERSION` | every feed/search/similar response logs snapshot | event logger tests |
| Clickstream events | `src/behavior/event_logger.py` | `clickstream_events`, unique `event_id`, partial impression idempotency | `ENABLE_EVENT_LOGGING`, `EVENT_TTL_DAYS` | React actions call `/api/events` | duplicate impression test |
| User item signals | `src/behavior/signal_builder.py` | `user_item_signals` | none required | debug panel shows signals | idempotent rebuild test |
| User profiles | `src/behavior/profile_builder.py` | `user_profiles` | optional thresholds later | homepage/search/similar personalize | profile changes after event |
| Item-item CF | `src/recommendation/item_item_cf.py` | `item_item_cf_edges` | optional CF thresholds later | homepage/similar show CF evidence | test builder reads `user_item_signals` |
| Item semantic neighbors | `src/recommendation/semantic_neighbors.py` | `item_semantic_neighbors`, existing `vector_index` | none required | similar/homepage if available | no self-neighbor, sorted top K |
| Homepage ranking | `src/recommendation/homepage_feed.py`, scoring/diversity/explanations | reads profiles/CF/semantic/items; writes logs | algorithm/ranking versions | `GET /api/feed/home`, React homepage | homepage non-empty |
| Personalized search | `src/recommendation/search_personalizer.py` | reads search results/profile/CF; writes logs | algorithm/ranking versions | `GET /api/search`, React search page | specific query dominates |
| Similar products | `src/recommendation/similar_products.py` | reads semantic neighbors/CF/items; writes logs | algorithm/ranking versions | `GET /api/items/{id}/similar` | fallback works without Phase 8 |
| API layer | `src/api/*` | via service modules only | `API_HOST`, `API_PORT`, CORS | required by React | API smoke tests |
| React frontend | `frontend/*` | none direct | `VITE_API_BASE_URL` | primary demo surface | frontend build + no duplicate impressions |
| Evaluation | `src/evaluation/*`, personalization eval script | reads behavior/profile/CF collections, optional `evaluation_runs` | algorithm/ranking versions | debug/admin can show metrics | evaluation dry-run/report |
| Reset/recovery | reset script, API demo route, React admin | behavior-derived collections | destructive reset flag optional | Debug/Admin panel | soft/full reset dry-run |

---

## 7. Live MongoDB Data State Gates

Use **MongoDB Atlas Live Operations Playbook** for the exact Atlas UI checks and command sequence behind these gates.

### Gate A — Existing Retrieval Data Ready

Required before Phase 2.

| Requirement | Health check |
|---|---|
| `items` exists | count > 0 |
| `retrieval_units` exists | count > 0 |
| HyPE units exist | `unit_type = "hype_question"` count > 0 |
| Vector/text index assumptions confirmed | Atlas UI or non-destructive check |

Validation:

```bash
python scripts/smoke_test_connection.py --counts
```

Stop if `items`, `retrieval_units`, `vector_index`, or `text_index` is missing.

### Gate B — Behavior Indexes Ready

Required before Phase 3/4 live write.

Required:

- behavior collections/indexes created,
- `recommendation_logs` unique `request_id + item_id`,
- `clickstream_events.event_id` unique index,
- partial unique impression index,
- TTL disabled or long enough for demo.

Validation:

```bash
python scripts/create_behavior_indexes.py --dry-run
```

Then human-approved live apply and non-destructive index verification.

Stop if partial impression idempotency index is missing.

### Gate C — Semantic Item Profiles Ready

Required before Phase 6/8/9 semantic/profile ranking.

Required:

- `item_hype_profiles` exists,
- count is reasonable relative to item count,
- embeddings are 1024-dim,
- no NaN/Inf,
- no empty centroid for items with HyPE units.

Validation:

```bash
python scripts/build_item_hype_profiles.py --dry-run --limit 5
```

Stop if vectors fail validation.

### Gate D — Synthetic Behavior Ready

Required before Phase 5/6/7.

Required:

- `recommendation_logs` seeded,
- `clickstream_events` seeded,
- enough demo users,
- enough positive items per user,
- enough overlap for CF support,
- no direct `user_profiles` seeding.

Validation:

```bash
python scripts/seed_synthetic_clickstream.py --dry-run --users 5
```

Stop if synthetic data cannot produce multi-user overlap.

### Gate E — Signals / Profiles / CF Ready

Required before Phase 9/10/11 full demo.

Required:

- `user_item_signals` built,
- `item_stats` built or rebuildable,
- `user_profiles` built,
- `item_item_cf_edges` built,
- optional `item_semantic_neighbors` built or fallback explicitly enabled.

Validation:

```bash
python scripts/build_user_item_signals.py --dry-run --limit 100
python scripts/build_user_profiles.py --dry-run --limit-users 5
python scripts/build_item_item_cf.py --dry-run --limit-users 20
```

Stop if `item_item_cf_edges` are missing and the demo claims CF.

### Gate F — Website Demo Ready

Required before final demo.

Required:

- API starts,
- frontend builds,
- homepage/search/similar works,
- events log,
- debug panel shows lineage,
- reset works.

Validation:

```bash
python -m uvicorn src.api.app:app --reload
cd frontend
npm run build
```

Stop if React cannot demonstrate homepage, search, similar products, logging, and debug lineage.

---

## 8. Seed and Rebuild Order

For live Atlas commands and safety confirmations, follow **MongoDB Atlas Live Operations Playbook**, especially Sections 7-9.

Correct order:

1. Existing `items` / `retrieval_units` already indexed.
2. Create behavior indexes.
3. Build `item_hype_profiles`.
4. Seed synthetic `recommendation_logs` + `clickstream_events`.
5. Build `user_item_signals`.
6. Build/update `item_stats`.
7. Build `user_profiles`.
8. Build `item_item_cf_edges`.
9. Optionally build `item_semantic_neighbors`.
10. Run ranking service smoke tests.
11. Start API.
12. Start React frontend.
13. Run evaluation.
14. Prepare demo reset mode.

Rules:

- If re-running synthetic seed, reset behavior-derived collections first.
- Do not run full reset on production DB.
- Soft reset keeps precomputed synthetic CF edges for quick demo recovery.
- Full reset deletes/rebuilds `item_item_cf_edges` to replay the full event -> signal -> profile -> CF path.
- `item_stats` is derived and can be rebuilt idempotently.

---

## 9. Phase Delivery Artifacts

Every phase must report these artifacts before moving on:

| Artifact | Required? | Notes |
|---|---:|---|
| Files changed | yes | exact list |
| Tests added/updated | yes | include test names |
| Commands run | yes | include pass/fail |
| Dry-run output | when applicable | index/seed/build/reset phases |
| Atlas status | when applicable | collections/indexes/counts verified |
| Env vars added | when applicable | `.env.example` only |
| Requirements changed | when applicable | include why |
| API/frontend proof | Phase 10/11+ | endpoint response or screenshot/build output |
| Known limitations | yes | honest caveats |
| Human review sign-off | yes | required before next phase |

---

## Phase 0 — Repo Audit & Guardrails

### Goal

Confirm the current repo state, exact function names, contracts, and guardrails before any implementation work.

### Why this phase exists

This prevents AI tools from inventing modules, duplicating MongoDB connectors, or rewriting the working retrieval core.

### Dependencies

None.

### Allowed files to modify/create

For a pure implementation run:

```text
none
```

For this planning task only:

```text
IMPLEMENTATION_PHASE_ROADMAP.md
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
src/mongodb.py
src/schemas.py
.env
requirements.txt
frontend/
```

### MongoDB Atlas changes

None.

### `.env` / config changes

None.

### Requirements/dependencies

None.

### Implementation tasks

- List repo files.
- Read canonical plan.
- Read `src/mongodb.py`, `src/config.py`, `src/schemas.py`.
- Read `src/query_processor.py`, `src/search_pipeline.py`, `src/retrieval_output.py`.
- Read `src/embeddings.py`, `src/indexing.py`.
- Read `src/evaluation/` overview.
- Read `requirements.txt` and `.env.example`.
- Identify mismatch between plan and code.
- Report exact function names to reuse.

### Acceptance criteria

- Repo audit summary exists.
- Exact search/query function names are documented.
- Existing env variables are documented.
- No source file changes.

### Tests / validation

```bash
python -m pytest tests/test_pipeline.py -v
```

Optional:

```bash
python scripts/smoke_test_connection.py --counts
```

Run the smoke test only when a human confirms live MongoDB access is desired.

### Human review checklist

- Confirm source of truth.
- Confirm no forbidden files changed.
- Confirm existing retrieval flow is understood.
- Confirm live Atlas state if needed.

### Common AI failure modes

- Treating plan text as code truth when repo differs.
- Inventing function names.
- Starting implementation before audit.

### Stop conditions

- Canonical plan conflicts with current code.
- Existing tests fail before changes.
- Live MongoDB credentials are missing and phase depends on live DB.

### Suggested Codex/Antigravity Implementation Prompt

```text
READ-ONLY PHASE 0.
Read ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md and current repo files.
Do not modify any file.
Do not touch src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env, or requirements.txt.
Report exact existing function names, MongoDB connector pattern, schema contracts, requirements, and any mismatch with the canonical plan.
Run only read-only commands and optionally pytest tests/test_pipeline.py if requested.
Report findings and changed files; changed files must be none.
```

---

## Phase 1 — Data Models, MongoDB Getters, Index Specs

### Goal

Add behavior/recommendation collection contracts, extend the existing MongoDB connector with new collection getters, and create a dry-run index creation script.

### Why this phase exists

All later phases depend on consistent collection names, schemas, and indexes. This phase must happen before behavior logging or ranking code.

### Dependencies

Phase 0.

### Allowed files to modify/create

```text
src/mongodb.py
src/behavior/__init__.py
src/behavior/schemas.py
src/recommendation/__init__.py
src/recommendation/schemas.py
src/config.py
scripts/create_behavior_indexes.py
tests/test_behavior_schemas.py
tests/test_behavior_indexes.py
.env.example
```

If the team chooses a single schema file:

```text
src/schemas.py
```

Human review required before editing `src/schemas.py`.

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
existing retrieval core
```

### MongoDB Atlas changes

Planned only. No live writes by default.

Collections:

```text
users
sessions
recommendation_logs
clickstream_events
user_item_signals
user_profiles
item_hype_profiles
item_semantic_neighbors
item_item_cf_edges
item_stats
query_embedding_cache
synthetic_personas
evaluation_runs
```

Indexes:

- define exact specs from MongoDB Atlas Live Checklist,
- include partial unique impression index,
- TTL disabled or long for demo,
- dry-run first.

### `.env` / config changes

Update `.env.example` only if adding:

```text
ALGORITHM_VERSION
RANKING_VERSION
EVENT_TTL_DAYS
DEMO_MODE
ENABLE_PERSONALIZATION
ENABLE_EVENT_LOGGING
```

Do not modify `.env`.

`src/config.py` may be updated in this phase only to add typed settings with safe defaults. Do not change existing setting semantics, do not print secrets, and defer config edits if the new settings are not used yet.

### Requirements/dependencies

No new required dependency.

### Implementation tasks

- Add collection getters to `src/mongodb.py`.
- Define behavior/recommendation schema contracts.
- Implement index spec builder.
- Implement `scripts/create_behavior_indexes.py` with:
  - dry-run default,
  - `--write` or `--apply` for live creation,
  - no drop commands,
  - printed index plan.
- Add unit tests for:
  - getters use existing `get_database()`,
  - index script dry-run does not call live create,
  - impression partial unique index exists in planned specs.

### Acceptance criteria

- Imports pass.
- Dry-run prints planned collections/indexes.
- No live DB changes unless explicitly requested.
- No duplicate `MongoClient`.
- No changes to existing retrieval flow.
- Post-Phase 1 Human Atlas Apply Checkpoint is documented and must be completed before live writes in later phases.

### Tests / validation

```bash
python -m pytest tests/test_behavior_schemas.py tests/test_behavior_indexes.py -v
python scripts/create_behavior_indexes.py --dry-run
python -m pytest tests/test_pipeline.py -v
```

### Human review checklist

- Verify collection names match canonical plan.
- Verify `src/mongodb.py` still has only one cached client path.
- Verify any `src/config.py` changes only add safe defaults.
- Verify no global unique `{request_id,item_id,event_type}` for all event types.
- Verify TTL is disabled/long for demo.
- Verify dry-run output is approved before live index apply.

### Common AI failure modes

- Creating `src/storage/mongo.py`.
- Creating a second `MongoClient`.
- Adding destructive index/drop commands.
- Overloading `src/schemas.py` with unrelated logic.

### Stop conditions

- Any duplicate MongoDB connection logic appears.
- Index script writes live by default.
- Partial unique impression index is missing.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 1 only.
Read ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md and IMPLEMENTATION_PHASE_ROADMAP.md first.
Allowed files: src/mongodb.py, src/config.py if typed settings are needed, src/behavior/__init__.py, src/behavior/schemas.py, src/recommendation/__init__.py, src/recommendation/schemas.py, scripts/create_behavior_indexes.py, tests/test_behavior_schemas.py, tests/test_behavior_indexes.py, .env.example.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env, existing retrieval code.
Extend src/mongodb.py; do not create a duplicate MongoClient.
If editing src/config.py, only add new settings with safe defaults and do not change existing env semantics.
Create index script dry-run by default; no live writes unless --write.
Report env changes and dry-run index output.
Add tests and run them.
Report changed files and validation results.
```

---

## Phase 2 — Item HyPE Profiles Builder

### Goal

Build `item_hype_profiles` from existing HyPE retrieval units and compute item-level semantic centroid embeddings.

### Why this phase exists

User profiles, homepage ranking, semantic neighbors, and similar products need item-level semantic embeddings. The existing embeddings live at retrieval-unit level.

### Dependencies

Phase 1.

### Allowed files to modify/create

```text
src/recommendation/item_hype_profiles.py
scripts/build_item_hype_profiles.py
tests/test_item_hype_profiles.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
items/retrieval_units contracts
.env
```

### MongoDB Atlas changes

Writes/upserts to:

```text
item_hype_profiles
```

Reads:

```text
retrieval_units
items
```

No changes to `items` or `retrieval_units`.

### `.env` / config changes

None required.

### Requirements/dependencies

Use existing:

```text
numpy
pymongo
pytest
```

### Implementation tasks

- Read HyPE units where `unit_type = "hype_question"`.
- Group by `item_id`.
- Do not sort all `retrieval_units` by `item_id` on Atlas M0.
  - The collection can exceed the 32MB in-memory sort limit.
  - Limited dry-runs should fetch item ids first, then fetch HyPE units per item.
  - Full builds should stream HyPE units and group client-side unless a supporting index or higher Atlas tier is confirmed.
- Validate `embedding` is 1024-dimensional.
- Reject/skip NaN/Inf embeddings with clear counters.
- Compute weighted centroid.
- Normalize centroid.
- Preserve useful metadata:
  - `item_id`,
  - `category_id`,
  - `price_bucket`,
  - `top_aspects`,
  - `unit_count`,
  - `updated_at`.
- Use idempotent upsert.
- Support:
  - dry-run,
  - limit/sample,
  - write mode.

### Acceptance criteria

- Count roughly matches items with HyPE units.
- Every written centroid is length 1024.
- No NaN/Inf.
- Re-running script does not duplicate docs.
- Dry-run works without writing.

### Tests / validation

```bash
python -m pytest tests/test_item_hype_profiles.py -v
python scripts/build_item_hype_profiles.py --dry-run --limit 5
python -m pytest tests/test_pipeline.py -v
```

Optional live write after human confirmation:

```bash
python scripts/build_item_hype_profiles.py --write
```

### Human review checklist

- Confirm centroid formula and normalization.
- Confirm no writes to `items` or `retrieval_units`.
- Confirm all embeddings use existing stored embeddings or `src.embeddings`.

### Common AI failure modes

- Re-embedding every item unnecessarily.
- Forgetting normalization.
- Loading all retrieval units into memory without batching.
- Writing malformed embeddings.

### Stop conditions

- Embedding dimension mismatch.
- NaN/Inf found without clear handling.
- Script attempts to modify existing core collections.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 2 only.
Read the canonical plan and roadmap first.
Allowed files: src/recommendation/item_hype_profiles.py, scripts/build_item_hype_profiles.py, tests/test_item_hype_profiles.py.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env, items/retrieval_units schema changes.
Build item_hype_profiles from existing retrieval_units hype_question embeddings.
Validate 1024 dims, normalize centroids, reject NaN/Inf, upsert idempotently.
Dry-run must be default.
Add tests and report changed files plus validation.
```

---

## Phase 3 — Behavior Logging & Recommendation Attribution

### Goal

Implement recommendation snapshots and clickstream event logging with correct idempotency.

### Why this phase exists

Every profile update and CF edge must trace back to what the system showed and what the user did. Without this phase, later personalization would look hardcoded.

### Dependencies

Phase 1.

### Allowed files to modify/create

```text
src/behavior/event_logger.py
tests/test_event_logger.py
```

Possible schema updates if not already done:

```text
src/behavior/schemas.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
```

### MongoDB Atlas changes

Uses collections:

```text
recommendation_logs
clickstream_events
```

Requires indexes from Phase 1.

### `.env` / config changes

Use:

```text
ALGORITHM_VERSION
RANKING_VERSION
ENABLE_EVENT_LOGGING
```

If not in `.env.example`, update `.env.example` only.

### Requirements/dependencies

No new dependency.

### Implementation tasks

- Implement `log_recommendation_snapshot(...)`.
- Implement `log_clickstream_event(...)`.
- Generate/validate:
  - `request_id`,
  - `event_id`,
  - optional `idempotency_key`,
  - `algorithm_version`,
  - `ranking_version`.
- Ensure duplicate impression returns idempotent success.
- Ensure repeated click/cart events can exist if `event_id` differs.
- Ensure event joins recommendation log by `request_id + item_id`.
- Include clear errors for missing required fields.

### Acceptance criteria

- Duplicate impression does not double insert.
- Click event can repeat when event IDs differ.
- Logs are joinable by `request_id + item_id`.
- Algorithm/ranking versions are stored.

### Tests / validation

```bash
python -m pytest tests/test_event_logger.py -v
python -m pytest tests/test_pipeline.py -v
```

### Human review checklist

- Verify no global unique `{request_id,item_id,event_type}` logic.
- Verify idempotency is impression-safe and event-safe.
- Verify no profile updates happen in event logger.

### Common AI failure modes

- Deduping all events too aggressively.
- Not recording algorithm/ranking version.
- Updating profiles inside event logger.
- Swallowing duplicate key errors incorrectly.

### Stop conditions

- Duplicate non-impression events cannot be represented.
- Event logger writes directly to profiles.
- Attribution join keys are missing.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 3 only.
Read ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md and roadmap.
Allowed files: src/behavior/event_logger.py, tests/test_event_logger.py, and src/behavior/schemas.py only if needed.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Implement log_recommendation_snapshot and log_clickstream_event.
Use idempotency_key for impressions; do not globally dedupe all event types by request_id/item_id/event_type.
Include algorithm_version and ranking_version.
Verify behavior indexes are ready before any live test; otherwise use mocks/dry-run.
Add tests for duplicate impressions and repeated clicks.
Report changed files, Atlas/index readiness, env changes, and test results.
```

---

## Phase 4 — Synthetic Behavior Seed Data

### Goal

Generate synthetic personas and behavior events without directly inserting perfect profiles.

### Why this phase exists

The project needs behavior data to demonstrate personalization and true item-item CF. Synthetic behavior is acceptable only if it flows through logs/events/signals/profiles/CF.

### Dependencies

Phase 2 and Phase 3.

### Allowed files to modify/create

```text
src/behavior/synthetic_generator.py
scripts/seed_synthetic_clickstream.py
tests/test_synthetic_generator.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
user_profiles direct seeding
item_item_cf_edges direct seeding
```

### MongoDB Atlas changes

Writes:

```text
synthetic_personas
recommendation_logs
clickstream_events
```

Does not write:

```text
user_profiles
item_item_cf_edges
```

### `.env` / config changes

Optional:

```text
DEMO_MODE
SYNTHETIC_USER_COUNT
```

Update `.env.example` only if used.

### Requirements/dependencies

Use existing:

```text
numpy
pymongo
tqdm
pytest
```

### Implementation tasks

- Define personas based on actual dataset:
  - beauty,
  - phone accessories,
  - charger/cable,
  - audio,
  - budget,
  - mixed explorer.
- Implement persona-item match formula:
  - category score,
  - price bucket score,
  - semantic score from item profile if available.
- Implement click probability with position bias.
- Implement cart/purchase probability.
- Add noise so behavior is not too perfect.
- Ensure anchor items overlap across users to create CF support.
- Generate recommendation snapshots first.
- Generate clickstream events second.
- Support dry-run and `--write`.

### Acceptance criteria

- Synthetic events exist after write.
- `user_profiles` remains empty before Phase 6.
- Enough positive items per user.
- Enough overlap for CF edges.
- All events have `request_id` and `item_id`.

### Tests / validation

```bash
python -m pytest tests/test_synthetic_generator.py -v
python scripts/seed_synthetic_clickstream.py --dry-run --users 5
```

Optional live write after human confirmation:

```bash
python scripts/seed_synthetic_clickstream.py --write
```

### Human review checklist

- Confirm profiles are not directly seeded.
- Confirm behavior is plausible.
- Confirm overlap exists for CF.
- Confirm categories use normalized `category_id`.

### Common AI failure modes

- Inserting `user_profiles` directly.
- Creating perfectly deterministic behavior.
- Generating no co-interaction overlap.
- Using raw `source_category` where normalized `category_id` is required.

### Stop conditions

- Profiles or CF edges are directly inserted.
- Synthetic events lack attribution snapshots.
- Generated data cannot produce CF edges.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 4 only.
Read canonical plan and roadmap first.
Allowed files: src/behavior/synthetic_generator.py, scripts/seed_synthetic_clickstream.py, tests/test_synthetic_generator.py.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Generate synthetic recommendation_logs and clickstream_events only.
Do not insert user_profiles or item_item_cf_edges.
Use current dataset categories and normalized category_id.
Dry-run must be default.
Verify Atlas behavior indexes before live write.
Report changed files, dry-run output, env changes, and validation commands.
```

---

## Phase 5 — User Item Signals Builder

### Goal

Aggregate raw clickstream events into `user_item_signals` and optionally rebuild the derived `item_stats` collection.

### Why this phase exists

`user_item_signals` is the shared behavior source for profiles and true item-item CF. `item_stats` is the item-level aggregate used by popularity baselines, ranking quality/popularity, and debug panels.

### Dependencies

Phase 3 and Phase 4.

### Allowed files to modify/create

```text
src/behavior/signal_builder.py
scripts/build_user_item_signals.py
tests/test_signal_builder.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
```

### MongoDB Atlas changes

Reads:

```text
clickstream_events
recommendation_logs
```

Writes:

```text
user_item_signals
item_stats
clickstream_events.processed flag or checkpoint fields
```

`item_stats` is a derived collection and can be rebuilt idempotently. It does not replace `items.cold_start`. Do not update `items.cold_start.interaction_count` directly in Phase 5 unless the team creates a separate reviewed mini-phase for syncing derived stats back to `items`.

### `.env` / config changes

None required.

### Requirements/dependencies

No new dependency.

### Implementation tasks

- Join events to recommendation snapshots by `request_id + item_id`.
- Apply event weights:
  - click positive,
  - view_detail weighted by dwell,
  - wishlist/add_to_cart/purchase strongly positive,
  - hide/dislike negative,
  - impression neutral or fatigue signal.
- Include attribution reason scores.
- Make aggregation idempotent.
- Mark events processed or maintain a processed checkpoint.
- Optionally rebuild/update `item_stats` from `clickstream_events` or `user_item_signals`.
- Compute item-level:
  - `impression_count`,
  - `click_count`,
  - `view_detail_count`,
  - `add_to_cart_count`,
  - `purchase_count`,
  - `hide_count`,
  - `ctr`,
  - `cart_rate`,
  - `purchase_rate`,
  - `interaction_count`,
  - `last_interaction_at`.
- Use `item_stats` as the source for popularity baseline.
- Support dry-run.

### Acceptance criteria

- Running twice does not double-count.
- Positive events increase positive score.
- Hide/dislike create negative score.
- Output supports CF builder.
- `item_stats` can be rebuilt idempotently.
- Popularity baseline can read from `item_stats`.

### Tests / validation

```bash
python -m pytest tests/test_signal_builder.py -v
python scripts/build_user_item_signals.py --dry-run --limit 100
python scripts/build_user_item_signals.py --dry-run --rebuild-item-stats --limit 100
```

### Human review checklist

- Verify event weights.
- Verify idempotency strategy.
- Verify signals preserve attribution.
- Verify negative behavior is handled.
- Verify `item_stats` is derived and rebuildable.
- Verify `items` is not modified directly.

### Common AI failure modes

- Double-counting events on rerun.
- Ignoring recommendation attribution.
- Treating impressions as strong positives.
- Losing negative feedback.
- Updating `items.cold_start` directly without a reviewed sync phase.
- Making `item_stats` non-idempotent.

### Stop conditions

- Rerun changes counts incorrectly.
- Signals cannot support pair generation.
- Missing user/item keys.
- Popularity/item stats cannot be rebuilt deterministically.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 5 only.
Read canonical plan and roadmap first.
Allowed files: src/behavior/signal_builder.py, scripts/build_user_item_signals.py, tests/test_signal_builder.py.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Aggregate clickstream_events + recommendation_logs into user_item_signals.
Also support derived item_stats rebuild for counts/rates/popularity baseline.
Do not modify items directly; item_stats is the derived collection.
Ensure idempotency: rerun must not double-count.
Add tests for positive, negative, and repeated runs.
Add tests for item_stats counts/rates and idempotent rebuild.
Dry-run must be available.
Report changed files, dry-run output, and validation commands.
```

---

## Phase 6 — User Profiles Builder

### Goal

Build/update behavior-derived `user_profiles` with short-term, long-term, and multi-interest vectors.

### Why this phase exists

Personalized homepage/search/similar products need user profiles, but profiles must be derived from behavior rather than seeded directly.

### Dependencies

Phase 2 and Phase 5.

### Allowed files to modify/create

```text
src/behavior/profile_builder.py
scripts/build_user_profiles.py
tests/test_profile_builder.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
direct profile seeding
```

### MongoDB Atlas changes

Reads:

```text
user_item_signals
clickstream_events
recommendation_logs
item_hype_profiles
items
```

Writes:

```text
user_profiles
```

### `.env` / config changes

Optional:

```text
MAX_INTERESTS_PER_USER
INTEREST_MERGE_THRESHOLD
```

Prefer constants first; env tuning can come later.

### Requirements/dependencies

Use existing:

```text
numpy
pytest
```

### Implementation tasks

- Create event vectors from search/home/similar/onboarding context.
- Maintain short-term and long-term embeddings.
- Implement multi-interest matching.
- Use `INTEREST_MERGE_THRESHOLD = 0.72` as starting point.
- Implement max interests policy.
- Track category/brand/price affinity.
- Track negative preferences.
- Validate vectors:
  - 1024 dims,
  - finite,
  - normalized.
- Provide threshold calibration diagnostics.

### Acceptance criteria

- Profile changes after behavior.
- No perfect direct seeding.
- User interests are sensible.
- No NaN/Inf vectors.
- Threshold validation reports interest distribution.

### Tests / validation

```bash
python -m pytest tests/test_profile_builder.py -v
python scripts/build_user_profiles.py --dry-run --limit-users 5
```

### Human review checklist

- Verify event vector formula.
- Verify profile does not override search later.
- Verify multi-interest behavior.
- Verify negative preferences do not over-penalize.

### Common AI failure modes

- Averaging all interests into one vector.
- Creating profiles directly from personas.
- Not normalizing vectors.
- Threshold causing too many/few interests.

### Stop conditions

- Profiles are not traceable to events/signals.
- Vector validation fails.
- Profile builder needs heavy model training.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 6 only.
Read canonical plan and roadmap first.
Allowed files: src/behavior/profile_builder.py, scripts/build_user_profiles.py, tests/test_profile_builder.py.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Build user_profiles only from user_item_signals/events/item_hype_profiles.
Implement multi-interest profiles with threshold and max-interest policy.
Validate 1024-dim finite normalized vectors.
Add tests and dry-run support.
Report changed files and validation.
```

---

## Phase 7 — Item-item Collaborative Filtering

### Goal

Build true `item_item_cf_edges` from multi-user implicit feedback.

### Why this phase exists

This is the actual Collaborative Filtering layer. It must be behavior-derived, not semantic-similarity-derived.

### Dependencies

Phase 5.

### Allowed files to modify/create

```text
src/recommendation/item_item_cf.py
scripts/build_item_item_cf.py
tests/test_item_item_cf.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
embedding-based CF implementation
```

### MongoDB Atlas changes

Reads:

```text
user_item_signals
items
```

Writes:

```text
item_item_cf_edges
```

### `.env` / config changes

Optional later:

```text
CF_MIN_SUPPORT
CF_MAX_ITEMS_PER_USER
```

### Requirements/dependencies

Use existing:

```text
numpy
pymongo
pytest
```

### Implementation tasks

- Read positive `user_item_signals`.
- Cap top positive items per user to prevent pair explosion.
- Generate item pairs per user.
- Count:
  - co-click,
  - co-cart,
  - co-purchase if available,
  - support.
- Normalize by popularity.
- Apply support threshold.
- Write symmetric edges A -> B and B -> A.
- Store evidence fields:
  - `support`,
  - `cf_score`,
  - `co_click_count`,
  - `co_cart_count`,
  - `co_purchase_count`.

### Acceptance criteria

- Edges require support >= threshold.
- Edges are symmetric.
- CF evidence is available for UI.
- Test proves builder reads `user_item_signals`, not embeddings.

### Tests / validation

```bash
python -m pytest tests/test_item_item_cf.py -v
python scripts/build_item_item_cf.py --dry-run --limit-users 20
```

### Human review checklist

- Confirm no embedding similarity is used.
- Confirm pair explosion is capped.
- Confirm score normalization is sensible.
- Confirm support threshold is not too low.

### Common AI failure modes

- Implementing CF as cosine similarity.
- Generating all-pairs across all catalog items.
- Missing symmetric edges.
- No popularity normalization.

### Stop conditions

- CF code imports embeddings.
- Edges can be created from one user only without support policy.
- Runtime/memory explodes.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 7 only.
Read canonical plan and roadmap first.
Allowed files: src/recommendation/item_item_cf.py, scripts/build_item_item_cf.py, tests/test_item_item_cf.py.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Build item_item_cf_edges only from user_item_signals.
Do not use embeddings or semantic similarity for CF.
Generate capped, support-thresholded, symmetric item-item edges.
Add tests proving CF input is user_item_signals.
Dry-run must be available.
Report changed files and validation.
```

---

## Phase 8 — Item Semantic Neighbors

### Goal

Build `item_semantic_neighbors` using item HyPE profiles and existing retrieval-unit vector search.

### Why this phase exists

Similar products and homepage expansion benefit from semantic item similarity, but this layer must remain separate from CF.

### Dependencies

Phase 2 and live MongoDB Atlas Vector Search readiness.

Fallback rule:

```text
If Atlas Vector Search is unavailable or vector_index is not ready,
skip Phase 8 temporarily and mark item_semantic_neighbors as unavailable.
Do not block Phase 9 entirely.
```

### Allowed files to modify/create

```text
src/recommendation/semantic_neighbors.py
scripts/build_item_semantic_neighbors.py
tests/test_semantic_neighbors.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
CF naming for semantic similarity
```

### MongoDB Atlas changes

Reads:

```text
item_hype_profiles
retrieval_units
items
```

Writes:

```text
item_semantic_neighbors
```

Uses existing:

```text
retrieval_units vector_index
```

No new vector index unless separately reviewed. Do not create a new vector index automatically.

### `.env` / config changes

None required.

### Requirements/dependencies

No new dependency.

### Implementation tasks

- For each item profile centroid, run `$vectorSearch` on `retrieval_units`.
- Filter to HyPE units when appropriate.
- Exclude same item.
- Group results by target item.
- Compute neighbor score:
  - max similarity,
  - average top-3 similarity.
- Store top K neighbors.
- Include matched aspects/unit IDs.
- Support batching and dry-run.
- If Atlas vector search is unavailable, exit clearly with a recoverable status and do not write partial neighbor docs.

### Acceptance criteria

- No self-neighbor.
- Top K capped.
- Scores sorted.
- Rebuild is idempotent.
- Documentation/tests call this semantic similarity, not CF.
- If skipped due to Atlas readiness, the script reports `semantic_neighbors_unavailable` clearly.
- No local brute-force all item x item similarity.

### Tests / validation

```bash
python -m pytest tests/test_semantic_neighbors.py -v
python scripts/build_item_semantic_neighbors.py --dry-run --limit 5
```

### Human review checklist

- Confirm vector index path matches current retrieval unit embeddings.
- Confirm no new Atlas vector index is required.
- Confirm no CF wording.
- Confirm fallback status is understood by Phase 9.

### Common AI failure modes

- Calling semantic neighbors CF.
- Not excluding source item.
- Querying all documents without vector search.
- Creating new index unnecessarily.

### Stop conditions

- Script attempts brute-force all item x all unit similarity.
- Self-neighbors appear.
- New vector index is proposed without review.
- Atlas vector search is not ready; mark Phase 8 unavailable and continue only with Phase 9 fallback plan.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 8 only.
Read canonical plan and roadmap first.
Allowed files: src/recommendation/semantic_neighbors.py, scripts/build_item_semantic_neighbors.py, tests/test_semantic_neighbors.py.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Use existing retrieval_units vector_index where possible.
Build item_semantic_neighbors; do not call this CF.
If Atlas Vector Search is unavailable, skip gracefully and mark item_semantic_neighbors unavailable.
Do not create a new vector index automatically.
Do not brute-force all item x item similarity locally.
Exclude same item, cap top K, dry-run by default.
Add tests and report changed files, Atlas readiness status, dry-run output, and validation.
```

---

## Phase 9 — Personalized Ranking Services

### Goal

Implement homepage feed, personalized search wrapper, similar products, scoring, diversity, and explanations.

### Why this phase exists

This phase turns behavior/profile/CF data into actual recommendation outputs.

### Dependencies

Phase 2, Phase 3, Phase 6, and Phase 7.

Phase 8 is optional for first full integration. If `item_semantic_neighbors` is unavailable, Phase 9 must still work with:

- profile candidates,
- item-item CF,
- same category/price fallback,
- cold-start quality fallback.

### Allowed files to modify/create

```text
src/recommendation/candidate_sources.py
src/recommendation/homepage_feed.py
src/recommendation/search_personalizer.py
src/recommendation/similar_products.py
src/recommendation/scoring.py
src/recommendation/diversity.py
src/recommendation/explanations.py
tests/test_homepage_feed.py
tests/test_search_personalizer.py
tests/test_similar_products.py
tests/test_recommendation_scoring.py
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
```

### MongoDB Atlas changes

Reads:

```text
items
retrieval_units via existing search only
item_hype_profiles
item_semantic_neighbors if available
item_item_cf_edges
user_profiles
user_item_signals
item_stats
```

Writes:

```text
recommendation_logs
```

through Phase 3 logger only.

### `.env` / config changes

Use:

```text
ALGORITHM_VERSION
RANKING_VERSION
ENABLE_PERSONALIZATION
```

### Requirements/dependencies

No new dependency.

### Implementation tasks

- Implement homepage feed:
  - new user fallback,
  - warming user mix,
  - warm user profile/CF/semantic mix,
  - cold-start exploration.
- Implement personalized search wrapper:
  - call `process_query()`,
  - call `run_search()`,
  - rerank lightly only inside returned candidates.
- Implement similar products:
  - semantic neighbors when available,
  - CF edges,
  - same category/price fallback,
  - profile rerank.
- Implement fallback when `item_semantic_neighbors` is unavailable:
  - use item-item CF,
  - same category/price candidates,
  - profile candidates,
  - cold-start quality candidates.
- Implement rank-based normalization.
- Implement diversity reranking.
- Implement explanation fields and badges.
- Log recommendation snapshot for every returned surface.

### Acceptance criteria

- Homepage is never empty if catalog has items.
- Specific query still dominates profile.
- Score breakdown exists for all items.
- CF-backed items show CF evidence.
- Similar products return semantic and/or CF evidence.
- Similar products still return results when Phase 8 is skipped.
- Algorithm/ranking version recorded.

### Tests / validation

```bash
python -m pytest tests/test_homepage_feed.py tests/test_search_personalizer.py tests/test_similar_products.py tests/test_recommendation_scoring.py -v
python -m pytest tests/test_pipeline.py -v
```

### Human review checklist

- Verify search core is only called, not rewritten.
- Verify query-first guardrail.
- Verify explanations are not fake.
- Verify scoring weights match canonical plan.

### Common AI failure modes

- Reimplementing MongoDB search pipeline.
- Letting profile dominate specific queries.
- Returning items without explanations.
- Mixing semantic neighbors and CF evidence.

### Stop conditions

- `src/search_pipeline.py` changes unexpectedly.
- Query results become irrelevant due to personalization.
- Score breakdown missing.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 9 only.
Read canonical plan and roadmap first.
Allowed files: src/recommendation/candidate_sources.py, homepage_feed.py, search_personalizer.py, similar_products.py, scoring.py, diversity.py, explanations.py, and related tests.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Personalized search must call process_query and run_search, then rerank lightly.
Do not rewrite search pipeline.
Support homepage/similar fallback when item_semantic_neighbors is unavailable.
Implement homepage, similar products, rank normalization, diversity, explanations, and recommendation snapshot logging.
Add tests proving query intent still dominates.
Report changed files, Atlas/data prerequisites checked, env changes, and test results.
```

---

## Phase 10 — HTTP API Layer

### Goal

Expose recommendation services to React through a thin HTTP API layer.

### Why this phase exists

React cannot call Python modules directly. The API must adapt HTTP requests to service functions without containing ranking logic.

This phase is Core Required because the final demo is website-first.

### Dependencies

Phase 9.

### Allowed files to modify/create

```text
src/api/__init__.py
src/api/app.py
src/api/routes_users.py
src/api/routes_feed.py
src/api/routes_search.py
src/api/routes_items.py
src/api/routes_events.py
src/api/routes_debug.py
src/config.py
tests/test_api_smoke.py
requirements.txt
.env.example
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
ranking logic inside route handlers
```

### MongoDB Atlas changes

None directly. API calls existing service modules.

### `.env` / config changes

Update `.env.example` only:

```text
API_HOST
API_PORT
CORS_ALLOW_ORIGINS
```

Do not edit `.env`.

`src/config.py` may be updated in this phase to expose typed API/CORS settings with safe defaults. Do not change existing MongoDB, Ollama, or embedding env semantics.

### Requirements/dependencies

Add:

```text
fastapi
uvicorn
httpx
```

### Implementation tasks

- Add FastAPI app.
- Add CORS config for local React dev.
- Add routes:
  - `GET /api/users/demo`,
  - `POST /api/users`,
  - `GET /api/feed/home`,
  - `GET /api/search`,
  - `GET /api/items/{item_id}`,
  - `GET /api/items/{item_id}/similar`,
  - `POST /api/events`,
  - `GET /api/debug/user/{user_id}`,
  - `POST /api/demo/reset`,
  - `POST /api/demo/seed`.
- Route handlers call service modules only.
- Add API smoke tests.

### Acceptance criteria

- API imports.
- API starts locally.
- `/api/feed/home` returns `request_id + items`.
- `/api/events` logs an event.
- `/api/debug/user/{id}` returns debug data.
- No ranking logic inside routes.

### Tests / validation

```bash
python -m pytest tests/test_api_smoke.py -v
python -m uvicorn src.api.app:app --reload
```

### Human review checklist

- Verify no business logic in routes.
- Verify CORS safe for local demo.
- Verify no secrets returned.
- Verify service-layer errors are clear.
- Verify config additions have safe defaults and do not print secrets.

### Common AI failure modes

- Putting ranking code inside route files.
- Creating new MongoDB clients in routes.
- Returning raw internal docs with too much data.
- Importing heavy embedding model at API startup.

### Stop conditions

- API imports torch/BGE-M3 on startup unnecessarily.
- Routes bypass service layer.
- API prints secrets.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 10 only.
Read canonical plan and roadmap first.
Allowed files: src/api/*, src/config.py if typed API settings are needed, tests/test_api_smoke.py, requirements.txt, .env.example.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Add FastAPI as a thin HTTP adapter. Service logic must stay in src/behavior and src/recommendation modules.
Do not create a new MongoClient.
If editing src/config.py, only add API/CORS settings with safe defaults.
Report requirements and env changes.
Add CORS for local React dev.
Add API smoke tests.
Report changed files, requirements changes, env changes, API smoke command, and validation results.
```

---

## Phase 11 — React Frontend

### Goal

Build a professional React shopping UI for the demo.

### Why this phase exists

The recommendation engine needs a visual demo surface for homepage personalization, search, similar products, behavior logging, and explainability.

This is the primary final demo path. Notebooks are not a substitute for this phase.

### Dependencies

Phase 10.

### Allowed files to modify/create

```text
frontend/
frontend/package.json
frontend/vite.config.ts
frontend/src/
README.md or TESTING.md only if documenting run commands
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
backend ranking logic
```

### MongoDB Atlas changes

None directly. Frontend talks only to API.

### `.env` / config changes

Frontend env file template only:

```text
frontend/.env.example
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_DEMO_MODE=true
```

Do not create real secret env files.

### Requirements/dependencies

Add frontend dependencies to `frontend/package.json`:

```text
react
react-dom
vite
typescript
tailwindcss
react-router-dom
@tanstack/react-query
lucide-react
shadcn/ui setup if chosen
```

### Implementation tasks

- Create Vite React TypeScript app.
- Add API client wrapper.
- Add user/persona selector.
- Add homepage feed.
- Add search page.
- Add product detail page.
- Add similar products section.
- Add debug/admin panel.
- Add score breakdown UI.
- Add CF evidence UI.
- Manage stable `request_id` per surface.
- Log impressions once per request.
- Log click/view/add_to_cart/wishlist/hide/dislike/purchase events.

### Acceptance criteria

- Frontend builds.
- User can select demo user.
- Homepage loads.
- Search works.
- Product actions call `/api/events`.
- React re-render does not duplicate impressions.
- Debug panel shows profile/events/signals/CF lineage.

### Tests / validation

```bash
cd frontend
npm install
npm run build
npm run dev
```

If test framework is added:

```bash
npm test
```

### Human review checklist

- Verify UI labels CF honestly.
- Verify stable request lifecycle.
- Verify no direct MongoDB access.
- Verify no secrets in frontend code.
- Verify score breakdown is understandable.

### Common AI failure modes

- Duplicate impression logging on re-render.
- Hardcoding fake data instead of calling API.
- Hiding score breakdown behind vague labels.
- Calling backend with inconsistent field names.

### Stop conditions

- Frontend directly connects to MongoDB.
- UI logs duplicate impressions.
- Demo data is hardcoded without API.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 11 only.
Read canonical plan and roadmap first.
Allowed files: frontend/* and docs only if run commands need documentation.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Build React + Vite + TypeScript UI that calls the HTTP API.
Do not hardcode recommendations; use API responses.
Implement stable request_id lifecycle and no duplicate impressions.
Add score breakdown and CF evidence UI.
Verify API base URL env usage.
Run frontend build.
Report changed files, frontend dependencies, env changes, validation commands, and any screenshots/UI proof if available.
```

---

## Phase 12 — Evaluation & Demo Proof

### Goal

Evaluate personalization, homepage recommendation, and item-item CF against baselines.

### Why this phase exists

The hackathon needs proof that personalization and CF improve the experience beyond content-only and popularity baselines.

### Dependencies

Phase 4 through Phase 9. Popularity baseline depends on Phase 5 `item_stats`.

### Allowed files to modify/create

```text
src/evaluation/personalization_eval.py
scripts/run_personalization_evaluation.py
tests/test_personalization_evaluation.py
evaluation/README.md
```

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
```

### MongoDB Atlas changes

Reads:

```text
recommendation_logs
clickstream_events
user_item_signals
user_profiles
item_item_cf_edges
item_stats
items
```

Writes optional:

```text
evaluation_runs
```

### `.env` / config changes

None required.

### Requirements/dependencies

Use existing:

```text
pandas
numpy
pytest
```

### Implementation tasks

- Add baselines:
  - content-only,
  - exploration only,
  - profile only,
  - profile + CF,
  - popularity baseline from `item_stats`.
- Implement temporal split:
  - first 70% train,
  - final 30% held-out positives.
- Compute metrics:
  - HitRate@10,
  - Recall@20,
  - MAP@20,
  - coverage,
  - novelty/diversity,
  - cold-start exposure,
  - CF-supported recommendation count.
- Track `algorithm_version` and `ranking_version`.
- Write reproducible report artifacts.

### Acceptance criteria

- Profile+CF is compared against profile-only.
- Popularity baseline exists.
- Evaluation reports are reproducible.
- Metrics are clearly labeled as synthetic/demo when based on synthetic data.

### Tests / validation

```bash
python -m pytest tests/test_personalization_evaluation.py -v
python scripts/run_personalization_evaluation.py --dry-run
```

### Human review checklist

- Verify baselines are fair.
- Verify labels do not overclaim human ground truth.
- Verify CF metric is behavior-derived.
- Verify synthetic data caveats are visible.

### Common AI failure modes

- Comparing against random only.
- Calling synthetic labels human labels.
- Measuring CF with semantic similarity.
- Ignoring temporal order.

### Stop conditions

- No popularity baseline.
- Evaluation uses future events in training.
- Report overclaims human validation.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 12 only.
Read canonical plan and roadmap first.
Allowed files: src/evaluation/personalization_eval.py, scripts/run_personalization_evaluation.py, tests/test_personalization_evaluation.py, evaluation/README.md.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Add personalization/CF evaluation with content-only, profile-only, profile+CF, exploration, and popularity baselines.
Use temporal split and track algorithm_version/ranking_version.
Do not call synthetic labels human ground truth.
Add tests and report changed files.
```

---

## Phase 13 — Demo Reset/Recovery & Polish

### Goal

Make the demo recoverable and safe with soft reset, full reset, and admin controls.

### Why this phase exists

Live demos fail when state becomes inconsistent. Reset/recovery keeps the team in control.

### Dependencies

Phase 3 through Phase 12.

### Allowed files to modify/create

```text
scripts/reset_demo_behavior_data.py
src/api/routes_debug.py
src/api/routes_demo.py
frontend/src/pages/DebugAdmin*
tests/test_demo_reset.py
```

Actual frontend path depends on Phase 11 structure.

### Forbidden files

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
production destructive reset without confirmation
```

### MongoDB Atlas changes

Soft reset deletes:

```text
clickstream_events
recommendation_logs
user_item_signals
user_profiles
item_stats
```

Soft reset keeps:

```text
item_item_cf_edges
item_hype_profiles
item_semantic_neighbors
items
retrieval_units
```

Full reset additionally deletes/rebuilds:

```text
item_item_cf_edges
```

### `.env` / config changes

Optional:

```text
ALLOW_DESTRUCTIVE_DEMO_RESET=false
```

### Requirements/dependencies

No new dependency.

### Implementation tasks

- Implement reset script dry-run by default.
- Add `--soft`, `--full`, `--write`.
- Require confirmation for live destructive mode.
- Add API endpoint for demo reset.
- Add Debug/Admin UI controls.
- Label when CF evidence is seeded/precomputed.
- Document rebuild order.
- Ensure reset docs explain when to rebuild `item_stats` from Phase 5 after reseeding.

### Acceptance criteria

- Soft reset works.
- Full reset works with confirmation.
- UI labels seeded/precomputed CF evidence.
- Demo can recover quickly.
- No production DB destructive reset by default.

### Tests / validation

```bash
python -m pytest tests/test_demo_reset.py -v
python scripts/reset_demo_behavior_data.py --soft --dry-run
python scripts/reset_demo_behavior_data.py --full --dry-run
```

### Human review checklist

- Verify destructive commands require explicit confirmation.
- Verify reset does not touch `items` or `retrieval_units`.
- Verify UI labels are honest.

### Common AI failure modes

- Deleting catalog collections.
- Making destructive reset default.
- Not distinguishing soft vs full reset.
- Hiding seeded CF caveat.

### Stop conditions

- Script can delete data without explicit write/confirm.
- Script touches `items` or `retrieval_units`.
- Full reset does not rebuild CF.

### Suggested Codex/Antigravity Implementation Prompt

```text
Implement Phase 13 only.
Read canonical plan and roadmap first.
Allowed files: scripts/reset_demo_behavior_data.py, relevant API debug/demo route files, relevant frontend debug/admin files, tests/test_demo_reset.py.
Forbidden files: src/search_pipeline.py, src/query_processor.py, src/indexing.py, .env.
Implement dry-run-first soft reset and full reset.
Do not touch items or retrieval_units.
Require explicit confirmation for live destructive reset.
Label seeded/precomputed CF evidence in UI.
Add tests.
Report changed files, dry-run reset output, Atlas safety notes, and validation results.
```

---

## Phase 14 — Future Enhancements

### Goal

Keep advanced ideas organized without blocking the core demo path.

### Why this phase exists

The canonical plan keeps a broad vision, but future enhancements should not destabilize the first working recommendation demo.

### Dependencies

Stable Phase 13.

### Allowed files to modify/create

Depends on enhancement. Must be reviewed individually.

### Forbidden files

Unless a future reviewed phase explicitly allows it:

```text
src/search_pipeline.py
src/query_processor.py
src/indexing.py
.env
```

### MongoDB Atlas changes

TBD per enhancement.

### `.env` / config changes

TBD per enhancement.

### Requirements/dependencies

TBD per enhancement. Avoid heavy dependencies unless the value is clear.

### Implementation tasks

Possible future work:

- onboarding polish,
- seller add product flow,
- Tavily/web enrichment,
- query embedding cache,
- Redis/cache layer,
- async/batch workers,
- observability,
- production auth/privacy,
- `$rankFusion` / `$scoreFusion` comparison on a tier that supports it.

### Acceptance criteria

Each future enhancement must have its own mini-plan, tests, and rollback path.

### Tests / validation

TBD per enhancement.

### Human review checklist

- Does this improve demo or production potential?
- Does it risk existing retrieval?
- Does it require new credentials/secrets?
- Does it need live Atlas changes?

### Common AI failure modes

- Sneaking future work into core phases.
- Adding dependencies too early.
- Rewriting stable code for polish.

### Stop conditions

- Enhancement threatens the working demo.
- Scope becomes unclear.
- No acceptance criteria.

### Suggested Codex/Antigravity Implementation Prompt

```text
Plan Phase 14 enhancement only.
Read canonical plan and roadmap first.
Do not implement until the enhancement has allowed files, forbidden files, acceptance criteria, tests, and rollback path.
Do not touch src/search_pipeline.py, src/query_processor.py, src/indexing.py, or .env unless explicitly approved.
Report the mini-plan before coding.
```

---

## Final Implementation Rule

Start with Phase 0 or Phase 1. Do not jump directly to UI, ranking, behavior generation, or CF.

Recommended next step:

```text
Run Phase 0 read-only audit once more immediately before coding,
then implement Phase 1 with dry-run indexes and tests.
After Phase 1, complete the Post-Phase 1 Human Atlas Apply Checkpoint
before any live write, seed, or builder phase.
Before Phase 1 live apply or any later live write, complete
MongoDB Atlas Live Operations Playbook Sections 2-6.
Do not consider the final demo complete until Phase 10 API and Phase 11 React website pass validation.
```
