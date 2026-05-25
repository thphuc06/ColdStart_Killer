# PHASE 14 FUTURE IMPLEMENTATION PLAN — ColdStart Killer

Ngày lập kế hoạch: 2026-05-25  
Phạm vi: **plan only**, chưa implement code, chưa write MongoDB, chưa seed/reset, chưa đổi schema live.

## 0. Executive Summary

Phase 14 demo-readiness đã hoàn thành đủ cho demo hiện tại:

- Atlas live đã verify: database `coldstart_killer`, `items=3000`, `retrieval_units=29753`.
- Atlas Search indexes đã verify READY: `vector_index`, `text_index`.
- Phase 13 soft/full reset dry-run PASS và bảo vệ `items` / `retrieval_units`.
- Backend API smoke, pipeline tests, frontend build/test, manual browser QA đã pass theo trạng thái gần nhất.
- Phase 14 selected scope trước đó gồm demo/runbook polish và evaluation/observability polish đã done enough.

Tài liệu này **không thay thế** `IMPLEMENTATION_PHASE_ROADMAP.md` hoặc `ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md`. Nó là plan triển khai chi tiết cho phần **Phase 14 Future Improvements** còn lại, để team có thể dùng Codex/Antigravity implement từng batch an toàn.

Mục tiêu của future implementation:

- Mở rộng UX onboarding, seller flow, observability và production hardening mà không phá demo-ready core.
- Thêm cache/job/auth/enrichment theo feature flag và optional dependency.
- Chứng minh thêm MongoDB Aggregation Pipeline cho CF mà không thay thế Python-side CF hiện tại.
- Giữ default search/recommendation path ổn định: `process_query()` + `run_search()` + personalized wrapper.

Nguyên tắc không phá architecture:

- Không rewrite `src/search_pipeline.py`, `src/query_processor.py`, `src/indexing.py`.
- Không đổi contract `items` / `retrieval_units` nếu chưa có batch riêng, dry-run, review và confirm.
- Không tạo duplicate MongoDB connector; mọi collection getter đi qua `src/mongodb.py`.
- Không gọi semantic similarity là Collaborative Filtering.
- Không seed direct `user_profiles` / `item_item_cf_edges`; behavior-derived flow vẫn là source of truth.
- Mọi write operation phải có dry-run/default safe mode hoặc explicit action + confirmation.
- Mọi feature lớn phải có feature flag, tests, docs và rollback path.

Thứ tự batch khuyến nghị:

1. 14.1 Onboarding Polish.
2. 14.2 Query Embedding Cache.
3. 14.3 Evaluation Runs Persistence.
4. 14.4 Evaluation Dashboard UI.
5. Cross-cutting Aggregation Pipeline CF Proof.
6. 14.10 Fusion Comparison.
7. 14.5 Seller Add Product Flow.
8. 14.6 Tavily / Web Enrichment.
9. 14.7 Async / Batch Workers.
10. 14.8 Redis / Cache Layer.
11. 14.9 Production Auth / Privacy.

## 1. Current Architecture Baseline

### Backend FastAPI

Current API entrypoint:

- `src/api/app.py`
- Existing routers:
  - `src/api/routes_users.py`
  - `src/api/routes_feed.py`
  - `src/api/routes_search.py`
  - `src/api/routes_items.py`
  - `src/api/routes_events.py`
  - `src/api/routes_debug.py`

Current important endpoints:

- `GET /api/health`
- `GET /api/users/demo`
- `POST /api/users`
- `GET /api/feed/home`
- `GET /api/search`
- `GET /api/items/{item_id}`
- `GET /api/items/{item_id}/similar`
- `POST /api/events`
- `GET /api/debug/user/{user_id}`
- `GET /api/demo/status`
- `POST /api/demo/reset`
- `POST /api/demo/seed`
- `POST /api/debug/process-events`
- `POST /api/debug/rebuild-profiles`
- `POST /api/debug/rebuild-cf`

Routes should remain thin. Business logic belongs in `src/behavior/`, `src/recommendation/`, `src/evaluation/`, or new batch-specific service modules.

### Frontend React/Vite

Current frontend:

- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/state/experience.tsx`
- Pages:
  - `frontend/src/pages/ShopperLoginPage.tsx`
  - `frontend/src/pages/HomePage.tsx`
  - `frontend/src/pages/SearchPage.tsx`
  - `frontend/src/pages/ItemDetailPage.tsx`
  - `frontend/src/pages/DebugPage.tsx`
- Components:
  - `AppShell`
  - `UserControlPanel`
  - `ProductCard`
  - `ProductImage`
  - `ScoreBreakdown`
  - `StatusBadge`
  - `StateViews`
  - `JsonCard`

Frontend uses real API through `frontend/src/lib/api.ts`. Future UI must not introduce local fake recommendation arrays.

### MongoDB Collections

Existing/core collections:

- `items`
- `retrieval_units`

Behavior/recommendation collections already planned/implemented:

- `users`
- `sessions`
- `recommendation_logs`
- `clickstream_events`
- `user_item_signals`
- `user_profiles`
- `item_hype_profiles`
- `item_semantic_neighbors`
- `item_item_cf_edges`
- `item_stats`
- `query_embedding_cache`
- `synthetic_personas`
- `evaluation_runs`

Current connector:

- `src/mongodb.py`
- Single cached `MongoClient` via `get_mongo_client()`.
- All future collection getters must extend this file; do not create another MongoDB connector.

### Search / Retrieval Pipeline

Current core:

- `src/query_processor.py`
  - `process_query(raw_query)`
  - produces language-aware query fixture, hard filters and BGE-M3 query embedding.
- `src/search_pipeline.py`
  - `run_search(query_fixture, top_k=...)`
  - default production search path remains existing HyPE + BM25 + `$unionWith` / RRF fallback path.
  - Optional `$rankFusion` code exists for explicit testing only; it must not become default in Phase 14 without a separate comparison batch and human review.
- `src/retrieval_output.py`
  - output formatting helpers/contracts.

Future enhancements must wrap or call this core; do not rewrite it.

### Behavior / Profile / CF Flow

Correct lineage:

```text
synthetic_personas / user actions
  -> recommendation_logs
  -> clickstream_events
  -> user_item_signals
  -> user_profiles
  -> item_item_cf_edges
  -> homepage/search/similar explanations
  -> React UI/debug panel
```

Current modules:

- `src/behavior/event_logger.py`
- `src/behavior/signal_builder.py`
- `src/behavior/profile_builder.py`
- `src/behavior/synthetic_generator.py`
- `src/recommendation/item_item_cf.py`
- `src/recommendation/homepage_feed.py`
- `src/recommendation/search_personalizer.py`
- `src/recommendation/similar_products.py`
- `src/recommendation/candidate_sources.py`
- `src/recommendation/scoring.py`
- `src/recommendation/explanations.py`

CF meaning remains strict:

- True CF = `item_item_cf_edges` from `user_item_signals` across many users.
- Semantic neighbors / HyPE profile / vector similarity = semantic/content-based, not CF.

### Evaluation Flow

Current evaluation modules:

- `src/evaluation/personalization_eval.py`
- `scripts/run_personalization_evaluation.py`
- `tests/test_personalization_evaluation.py`

Current behavior:

- `--dry-run` avoids MongoDB `evaluation_runs` writes.
- `--dry-run` skips local artifacts by default.
- `--write-artifacts` explicitly writes local `.runtime/evaluation/...` artifacts.
- `--write-evaluation-run` explicitly persists compact evaluation summary.
- Output includes baselines, versions, synthetic caveat, CF support, coverage and cold-start exposure.

### Debug / Reset Safety

Current Phase 13 assets:

- `scripts/reset_demo_behavior_data.py`
- `scripts/clear_demo_data.py` quarantined.
- `src/api/routes_debug.py`
- `frontend/src/pages/DebugPage.tsx`
- reset tests:
  - `tests/test_reset_demo_behavior_data.py`
  - `tests/test_demo_reset.py`

Future admin/write endpoints must follow the same pattern:

- dry-run first,
- explicit `write` flag,
- confirmation string for destructive writes,
- never target `items` / `retrieval_units` unless a reviewed seller/indexing batch explicitly allows safe additive writes.

### Plan-Code Consistency Snapshot

This table records the current repo names that future implementation prompts must preserve. Items marked **proposed** do not exist yet and must not be described as implemented until their batch is coded and tested.

| Concept | Plan name | Actual code name | Status | Fix needed? |
| ------- | --------- | ---------------- | ------ | ----------- |
| MongoDB database | `coldstart_killer` | `.env.example` / `src.config.get_settings().mongodb_db_name` default `coldstart_killer` | Existing | No |
| Catalog collection | `items` | `src.mongodb.get_items_collection()` | Existing | No |
| Retrieval collection | `retrieval_units` | `src.mongodb.get_retrieval_units_collection()` | Existing | No |
| Users | `users` | `src.mongodb.get_users_collection()` | Existing | No |
| Sessions | `sessions` | `src.mongodb.get_sessions_collection()` | Existing | No |
| Recommendation logs | `recommendation_logs` | `src.mongodb.get_recommendation_logs_collection()` | Existing | No |
| Clickstream events | `clickstream_events` | `src.mongodb.get_clickstream_events_collection()` | Existing | No |
| User item signals | `user_item_signals` | `src.mongodb.get_user_item_signals_collection()` | Existing | No |
| User profiles | `user_profiles` | `src.mongodb.get_user_profiles_collection()` | Existing | No |
| Item HyPE profiles | `item_hype_profiles` | `src.mongodb.get_item_hype_profiles_collection()` | Existing | No |
| Item semantic neighbors | `item_semantic_neighbors` | `src.mongodb.get_item_semantic_neighbors_collection()` | Existing | No |
| Item-item CF edges | `item_item_cf_edges` | `src.mongodb.get_item_item_cf_edges_collection()` | Existing | No |
| Item stats | `item_stats` | `src.mongodb.get_item_stats_collection()` | Existing | No |
| Query embedding cache | `query_embedding_cache` | `src.mongodb.get_query_embedding_cache_collection()`, `QueryEmbeddingCacheDocument` | Collection/schema/index exist; runtime cache wrapper proposed | No |
| Evaluation runs | `evaluation_runs` | `src.mongodb.get_evaluation_runs_collection()`, `EvaluationRunDocument`, `--write-evaluation-run` | Collection/schema/script flag exist; dashboard and confirmation hardening proposed | No |
| Vector index | `vector_index` | `src.search_pipeline.VECTOR_INDEX_NAME`, `VECTOR_INDEX_NAME` env | Existing | No |
| Text index | `text_index` | `src.search_pipeline.TEXT_INDEX_NAME`, `TEXT_INDEX_NAME` env | Existing | No |
| Algorithm version | `ALGORITHM_VERSION` | `src.config.Settings.algorithm_version` | Existing | No |
| Ranking version | `RANKING_VERSION` | `src.config.Settings.ranking_version` | Existing | No |
| Reset script | `scripts/reset_demo_behavior_data.py` | `--soft`, `--full`, `--dry-run`, `--write`, `--confirm` | Existing | No |
| Evaluation script | `scripts/run_personalization_evaluation.py` | `--dry-run`, `--no-artifacts`, `--write-artifacts`, `--write-evaluation-run` | Existing | No |
| Users API | `/api/users/demo`, `/api/users` | `src/api/routes_users.py` | Existing | No |
| Feed API | `/api/feed/home` | `src/api/routes_feed.py` | Existing | No |
| Search API | `/api/search` | `src/api/routes_search.py` | Existing | No |
| Item detail/similar API | `/api/items/{item_id}`, `/api/items/{item_id}/similar` | `src/api/routes_items.py` | Existing | No |
| Debug/demo API | `/api/debug/user/{user_id}`, `/api/demo/status`, `/api/demo/reset`, `/api/demo/seed`, rebuild endpoints | `src/api/routes_debug.py` | Existing | No |
| Frontend pages | Login/home/search/detail/debug | `frontend/src/pages/ShopperLoginPage.tsx`, `HomePage.tsx`, `SearchPage.tsx`, `ItemDetailPage.tsx`, `DebugPage.tsx` | Existing | No |
| Generated artifacts ignore | `frontend/node_modules/`, `frontend/dist/`, `*.tsbuildinfo`, generated Vite JS/DTS | `.gitignore` | Existing | No |
| Seller drafts | `seller_product_drafts` | no getter/module yet | Proposed | Implement only in Batch 14.5 |
| Web enrichment requests | `web_enrichment_requests` | no getter/module yet | Proposed | Implement only in Batch 14.6 |
| Job runs | `job_runs` | no getter/module yet | Proposed | Implement only in Batch 14.7 |
| Auth mode | `AUTH_MODE` | no current setting | Proposed | Implement only in Batch 14.9 |
| Redis/cache backend | `CACHE_BACKEND`, `REDIS_URL` | no current setting/dependency | Proposed optional | Implement only in Batch 14.8 |

Important naming nuance:

- `process_query(raw_query)` currently returns a fixture field named `original_query`, not `raw_query`. Future cache code may store a document field called `raw_query` for canonical/user-facing input, but adapters must preserve the existing fixture shape expected by `run_search()`.
- Current code has native `$rankFusion` support through `PipelineMode = Literal["auto", "rankFusion", "unionWith"]`. There is no implemented `$scoreFusion` branch yet; `$scoreFusion` is proposed comparison work only.

## 2. Global Guardrails

These guardrails apply to every Phase 14 future batch.

### Architecture Guardrails

- Do not rewrite `src/search_pipeline.py`.
- Do not rewrite `src/query_processor.py`.
- Do not rewrite `src/indexing.py`.
- Do not modify existing `items` / `retrieval_units` schema contracts in-place.
- Do not create `src/storage/mongo.py` or any duplicate MongoDB connector if it only duplicates `src/mongodb.py`.
- Do not create a parallel `MongoClient`.
- Keep API route handlers thin.
- Keep business logic in service modules with unit tests.
- Keep React using real API responses.

### MongoDB Safety Guardrails

- All live writes need explicit command/action.
- Scripts that can write must default to dry-run or require explicit `--write`.
- Destructive operations need confirmation string.
- No drop collection/index by default.
- No reset path can touch `items` / `retrieval_units`.
- Catalog writes are only allowed in the Seller Add Product batch, and only additive/staged with explicit confirmation.
- Atlas index creation must be dry-run-first and human-reviewed.
- Do not print URI, credentials, tokens, API keys or `.env` contents.

### Recommendation Guardrails

- Search stays query-first.
- Personalized search only reranks within relevant candidate set.
- Semantic similarity is not CF.
- CF remains behavior-derived from `user_item_signals`.
- Do not seed direct perfect `user_profiles`.
- Do not seed direct `item_item_cf_edges`.
- Do not hardcode fake recommendations, fake CF evidence or fake metrics.

### Feature Flag / Config Guardrails

Every new feature must be disabled or no-op safe by default unless it is purely UI/docs:

- Add typed settings in `src/config.py` only when needed.
- Update `.env.example`, not `.env`.
- Document flags in `RUNBOOK.md` / `TESTING.md`.
- Safe fallback when optional dependency is missing.

Recommended naming style:

```text
ENABLE_ONBOARDING
ENABLE_QUERY_EMBEDDING_CACHE
ENABLE_EVALUATION_RUNS_API
ENABLE_SELLER_TOOLS
ENABLE_WEB_ENRICHMENT
ENABLE_JOB_RUNS
CACHE_BACKEND
AUTH_MODE
ENABLE_FUSION_COMPARISON
ENABLE_AGG_CF_PROOF
```

These names are **proposed Phase 14 additions** unless already present in `src/config.py` / `.env.example`. Future batches must add typed settings with safe defaults and update `.env.example`; do not edit the real `.env`.

### Test / Docs / Rollback Guardrails

Each batch must include:

- unit tests,
- API tests when endpoints change,
- frontend route/component tests when UI changes,
- dry-run/no-write tests when scripts write,
- docs update,
- rollback path,
- report of changed files.

## 3. Batch Implementation Order

| Order | Batch | Why this order | Risk | Dependencies |
| ----- | ----- | -------------- | ---- | ------------ |
| 1 | 14.1 Onboarding Polish | Improves first-use UX without touching search core; uses existing `users.onboarding` and `profile_builder` onboarding weights | Medium | Stable users API, event logging, profile builder |
| 2 | 14.2 Query Embedding Cache | Latency/reliability improvement around query processing; existing collection/schema/getter already present | Medium | Stable `process_query()`, `query_embedding_cache` indexes |
| 3 | 14.3 Evaluation Runs Persistence | Current script already supports explicit persistence; harden with API/read UI later | Low/Medium | Evaluation dry-run green, `evaluation_runs` indexes |
| 4 | 14.4 Evaluation Dashboard UI | Read-only UI on top of persisted evaluation runs; safe if empty state exists | Low/Medium | Batch 14.3 or empty-state API |
| 5 | Cross-cutting Aggregation Pipeline CF Proof | Adds MongoDB story value without replacing Python CF | Medium | `user_item_signals`, current CF tests |
| 6 | 14.10 Fusion Comparison | Compares native-fusion experiments only: implemented `$rankFusion` path first, proposed `$scoreFusion` branch only if supported; default unchanged | Medium/High | Atlas tier support, current search pipeline tests |
| 7 | 14.5 Seller Add Product Flow | Product expansion, but touches catalog/indexing boundary; do after low-risk observability | High | Auth/admin guard preferred, indexing preview |
| 8 | 14.6 Tavily / Web Enrichment | External API/provenance; should attach to seller drafts after staging exists | High | Seller draft staging, API key, provenance schema |
| 9 | 14.7 Async / Batch Workers | Operational hardening around existing scripts; avoid external worker first | Medium/High | Reset/rebuild scripts stable, job_runs schema |
| 10 | 14.8 Redis / Cache Layer | Optional infra only after in-process cache semantics are clear | High | Cache abstraction, deployment plan |
| 11 | 14.9 Production Auth / Privacy | Important before public deployment; may affect many endpoints | High | Role model, admin/seller flows, privacy policy |

## 4. Batch 14.1 — Onboarding Polish

### Goal

Add a real shopper onboarding experience that captures category, price and intent preferences for cold users, while keeping the current profile-backed demo user selector intact.

### Why it matters

- Improves cold-user story beyond seeded demo personas.
- Gives judges a visible way to influence recommendations.
- Uses existing `users.onboarding`, `privacy`, `clickstream_events(surface="onboarding")`, and `profile_builder` onboarding weighting.

### Current repo state

- `src/behavior/schemas.py` already has:
  - `OnboardingState`
  - `ExplicitPrefs`
  - event surface `"onboarding"`
- `src/api/routes_users.py` returns onboarding fields and supports `POST /api/users`.
- `src/behavior/profile_builder.py` already weights onboarding surface.
- `frontend/src/pages/ShopperLoginPage.tsx` provides persona/profile-backed selection and user creation, but not a full preference wizard.

### Proposed design

Implement onboarding as event-derived preference capture, not direct profile seeding:

```text
User selects preferences
  -> users.onboarding updated after explicit completion
  -> clickstream_events with surface="onboarding"
  -> user_item_signals builder
  -> user_profiles builder
  -> homepage/search rerank
```

Onboarding should create **weak initial signals**, not perfect profiles. Seed item choices can be logged as onboarding `click` or `wishlist` style events with clear `metadata.source="onboarding"`.

### MongoDB collections/schema

Use existing first:

- `users`
  - `onboarding.completed`
  - `onboarding.completed_at`
  - `onboarding.selected_categories`
  - `onboarding.selected_price_buckets`
  - `onboarding.selected_seed_item_ids`
- `clickstream_events`
  - `surface="onboarding"`
  - `event_type="click"` or `"wishlist"` for selected seed items
  - `metadata.onboarding_intents`
  - `metadata.selected_categories`
  - `metadata.selected_price_buckets`
- `user_item_signals`
- `user_profiles`

Optional later collection only if needed:

- `onboarding_sessions`
  - `session_id`
  - `user_id_hash`
  - `step`
  - `draft_preferences`
  - `created_at`
  - `updated_at`
  - `completed_at`

Avoid creating `onboarding_sessions` in first implementation unless the UI needs recoverable drafts.

### Backend changes

Possible files:

- `src/config.py`
  - add `enable_onboarding: bool`
  - env: `ENABLE_ONBOARDING=true`
- `src/api/app.py`
  - include new router if created.
- `src/api/routes_onboarding.py` (new)
  - `GET /api/onboarding/options`
  - `POST /api/onboarding/preview`
  - `POST /api/onboarding/complete`
- `src/behavior/onboarding.py` (new)
  - validates selected categories/price buckets/intents.
  - selects seed item candidates from existing catalog/item profiles.
  - logs onboarding events through `event_logger.log_clickstream_event`.
  - updates `users.onboarding` only when user confirms.

Do not modify `src/search_pipeline.py`.

### Frontend changes

Possible files:

- `frontend/src/pages/ShopperLoginPage.tsx`
  - add optional "Set preferences" flow after demo user creation/selection.
- `frontend/src/pages/OnboardingPage.tsx` (new if route is cleaner)
- `frontend/src/components/OnboardingWizard.tsx` (new)
- `frontend/src/components/PreferenceChips.tsx` (new)
- `frontend/src/lib/api.ts`
  - add typed onboarding API methods.
- `frontend/src/App.tsx`
  - route `/onboarding` if separate page.
- `frontend/src/test/app.routes.test.tsx`
  - add route/component tests.

Keep existing profile-backed user selector unchanged and always available.

### API changes

Recommended contracts:

```text
GET /api/onboarding/options
```

Returns:

- available categories from catalog snapshot,
- price bucket options,
- intent chips from existing item/profile top aspects,
- optional seed item candidates.

```text
POST /api/onboarding/preview
```

Input:

- `user_id_hash`
- selected categories
- selected price buckets
- free-text intent chips
- optional seed item ids

Returns:

- preview candidate cards,
- explanation of how preferences will be used,
- no database write.

```text
POST /api/onboarding/complete
```

Input:

- same preferences,
- `session_id`,
- explicit user action.

Writes:

- `users.onboarding`,
- onboarding events in `clickstream_events`.

Does not write:

- direct `user_profiles`,
- direct `item_item_cf_edges`.

### Config/env changes

Update `src/config.py` and `.env.example` in this batch only:

```text
ENABLE_ONBOARDING=true
ONBOARDING_MAX_SEED_ITEMS=8
ONBOARDING_PREVIEW_LIMIT=12
```

Fallback:

- If disabled, UI hides onboarding wizard and keeps current user selector.

### Tests to add/update

Backend:

- `tests/test_onboarding.py` (new)
  - validates options response shape.
  - preview does not write.
  - complete writes `users.onboarding` and onboarding events only.
  - does not write direct `user_profiles`.
  - does not write direct `item_item_cf_edges`.
- `tests/test_api_smoke.py`
  - route smoke for `/api/onboarding/options` and preview.

Frontend:

- `frontend/src/test/app.routes.test.tsx`
  - onboarding UI renders.
  - user can skip onboarding.
  - user can complete onboarding via mocked API.
  - homepage still works after skip.

### Docs to update

- `README.md`
- `RUNBOOK.md`
- `TESTING.md`
- `.env.example`
- `bao_cao_phan_tich.md` or future audit report after implementation.

### Commands to verify

```bash
python -m pytest tests/test_onboarding.py -q -p no:cacheprovider
python -m pytest tests/test_api_smoke.py -q -p no:cacheprovider
python -m pytest tests/test_pipeline.py -q -p no:cacheprovider
cd frontend
npm run build
npm run test:ui -- --run
```

Manual QA:

- create/select cold user,
- skip onboarding,
- complete onboarding,
- verify homepage fallback,
- process events/profile builder only through existing safe flows.

### Acceptance criteria

- Current demo user selector still works.
- Onboarding can be skipped.
- Onboarding preview is read-only.
- Completion only writes `users.onboarding` and onboarding events.
- No direct profile/CF seeding.
- Profile builder can later derive preferences from onboarding events.
- Tests pass.
- Docs explain that onboarding is preference capture, not perfect profile insertion.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Direct perfect profile insertion | Explicit tests assert no `user_profiles` write in onboarding completion |
| UI creates fake recommendations | Preview uses API/catalog candidates only |
| Cold user flow breaks profile-backed demo | Keep current selector as default path |
| Onboarding writes too much live data | User action only; no batch seed; metadata clearly marks onboarding |

### Rollback plan

- Set `ENABLE_ONBOARDING=false`.
- Remove/hide `/onboarding` route.
- Revert new router/service/frontend files.
- Existing users/profile-backed demo remains intact.

### AI coding prompt for implementation

```text
Implement Phase 14.1 Onboarding Polish only.
Read ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md, IMPLEMENTATION_PHASE_ROADMAP.md, and PHASE_14_FUTURE_IMPLEMENTATION_PLAN.md first.

Allowed files:
- src/config.py
- src/api/app.py
- src/api/routes_onboarding.py
- src/behavior/onboarding.py
- frontend/src/App.tsx
- frontend/src/lib/api.ts
- frontend/src/pages/ShopperLoginPage.tsx
- optional frontend/src/pages/OnboardingPage.tsx
- optional frontend/src/components/OnboardingWizard.tsx
- tests/test_onboarding.py
- tests/test_api_smoke.py
- frontend/src/test/app.routes.test.tsx
- README.md, RUNBOOK.md, TESTING.md, .env.example

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- items/retrieval_units schema contracts

Requirements:
- Onboarding preview must be read-only.
- Complete onboarding may write only users.onboarding and clickstream onboarding events.
- Do not seed user_profiles or item_item_cf_edges directly.
- Keep existing demo user selector.
- Add tests and docs.
- Report changed files, validation commands, and rollback path.
```

## 5. Batch 14.2 — Query Embedding Cache

### Goal

Cache expensive query processing/embedding results for repeated hot queries without changing `run_search()`.

### Why it matters

- Improves latency for repeated demo/search queries.
- Reduces repeated BGE-M3 embedding work.
- Uses existing `query_embedding_cache` collection/getter/schema/index specs.

### Current repo state

- `src/mongodb.py` has `get_query_embedding_cache_collection()`.
- `src/recommendation/schemas.py` has `QueryEmbeddingCacheDocument`.
- `scripts/create_behavior_indexes.py` includes indexes for `query_embedding_cache`.
- Search currently calls `process_query()` from `src/query_processor.py`, then `run_search()`.
- No runtime query embedding cache wrapper is verified yet.

### Proposed design

Introduce a wrapper around `process_query()`, not inside `run_search()`:

```text
raw query + relevant config
  -> normalize/cache key
  -> cache hit: return cached processed fixture
  -> cache miss: call process_query()
  -> optional write cache
  -> personalized_search passes fixture to run_search()
```

Do not cache personalized ranking results. Cache only processed query fixture/embedding.

### Cache key strategy

Hash these fields:

- normalized raw query,
- detected/declared locale if present,
- `EMBEDDING_MODEL`,
- `VECTOR_INDEX_NAME`,
- `TEXT_INDEX_NAME`,
- query processor version string,
- optional hard filter canonical JSON.

Example:

```text
query_hash = sha256(
  "v1|BAAI/bge-m3|vector_index|text_index|raw_query_normalized|filters_json"
)
```

Cache document:

- `query_hash`
- `raw_query`
- `english_query`
- `hype_search_query_en`
- `bm25_search_query_en`
- `hard_filters`
- `embedding`
- `embedding_model`
- `query_processor_version`
- `created_at`
- `last_used_at`
- `usage_count`
- `algorithm_version`
- `ranking_version`

Existing schema has fewer fields; either extend it backward-compatibly or store extra fields in a nested `processed_query` dict after updating schema/tests.

Compatibility note:

- The existing `process_query()` fixture uses `original_query`, `language_detected`, `english_query`, `hype_search_query_en`, `bm25_search_query_en`, `hard_filters`, and `query_embedding`.
- Cache reads must reconstruct that exact fixture shape before passing it to `run_search()`.
- The cache document can still store `raw_query` as the persisted user-facing input, but the runtime adapter must map it back to `original_query`.

### MongoDB collections/schema

Use existing:

- `query_embedding_cache`

Indexes:

- existing/planned unique `{ query_hash: 1 }`
- `last_used_at`
- optional TTL index only if demo/human approves; do not add TTL by default.

### Backend changes

Possible files:

- `src/config.py`
  - `enable_query_embedding_cache`
  - `query_cache_write_enabled`
  - `query_cache_ttl_days`
  - `query_cache_version`
- `src/recommendation/query_cache.py` (new)
  - `build_query_cache_key(raw_query, filters, settings)`
  - `get_cached_query_fixture(...)`
  - `put_cached_query_fixture(...)`
  - `process_query_with_cache(raw_query, process_query_fn=process_query, write_cache=False)`
- `src/recommendation/search_personalizer.py`
  - inject cached wrapper as optional dependency.
- `src/api/routes_search.py`
  - optional query param `use_cache=true`, or rely on config.
- `src/recommendation/schemas.py`
  - backward-compatible optional fields in `QueryEmbeddingCacheDocument`.

Do not modify `src/query_processor.py` or `src/search_pipeline.py`.

### Frontend changes

Likely none for batch 1.

Optional later:

- Debug page can show query cache status if API exposes it.

### API changes

Optional:

```text
GET /api/debug/query-cache/status
```

Only if needed for observability. Prefer not to add in first pass unless tests require it.

### Config/env changes

```text
ENABLE_QUERY_EMBEDDING_CACHE=false
QUERY_CACHE_WRITE_ENABLED=false
QUERY_CACHE_VERSION=query_cache_v1
QUERY_CACHE_TTL_DAYS=0
```

Safe default recommendation:

- cache read can be enabled after collection/index verification,
- cache write disabled unless explicitly enabled.

### Tests to add/update

- `tests/test_query_embedding_cache.py` (new)
  - cache key stable.
  - cache miss calls `process_query_fn`.
  - cache hit does not call `process_query_fn`.
  - invalid/old model cache is ignored.
  - write disabled means no upsert.
  - write enabled upserts once and increments usage.
- `tests/test_search_personalizer.py`
  - personalized search still calls `run_search_fn` with fixture.
  - cache wrapper does not override query intent.
- `tests/test_behavior_indexes.py`
  - verify query cache indexes if needed.

### Docs to update

- `.env.example`
- `RUNBOOK.md`
- `TESTING.md`

### Commands to verify

```bash
python -m pytest tests/test_query_embedding_cache.py -q -p no:cacheprovider
python -m pytest tests/test_search_personalizer.py -q -p no:cacheprovider
python -m pytest tests/test_pipeline.py -q -p no:cacheprovider
python -m pytest tests/test_api_smoke.py -q -p no:cacheprovider
```

### Acceptance criteria

- `run_search()` unchanged.
- `process_query()` unchanged.
- Cache key includes embedding model/version enough to avoid stale mismatches.
- Cache miss fallback works.
- Cache error fallback works.
- Cache writes disabled by default.
- No hardcoded query fixtures.
- Tests pass.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Stale embedding after model/index change | Include model/index/cache version in key |
| Cache masks query processor bugs | Cache can be disabled; tests exercise miss path |
| Live writes happen unexpectedly | `QUERY_CACHE_WRITE_ENABLED=false` default |
| Cache changes search relevance | Wrapper only returns same fixture shape; no ranking logic |

### Rollback plan

- Set `ENABLE_QUERY_EMBEDDING_CACHE=false`.
- Set `QUERY_CACHE_WRITE_ENABLED=false`.
- Revert `query_cache.py` and integration call.
- Existing search path remains `process_query()` -> `run_search()`.

### AI coding prompt for implementation

```text
Implement Phase 14.2 Query Embedding Cache only.
Read the future plan first.

Allowed files:
- src/config.py
- src/recommendation/query_cache.py
- src/recommendation/search_personalizer.py only for wrapper injection
- src/api/routes_search.py only if a tiny integration flag is needed
- src/recommendation/schemas.py only for backward-compatible optional cache fields
- tests/test_query_embedding_cache.py
- tests/test_search_personalizer.py
- .env.example
- RUNBOOK.md, TESTING.md

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env

Requirements:
- Do not change run_search().
- Do not change process_query().
- Cache write disabled by default.
- On cache error/miss, fall back to process_query().
- Add tests for hit, miss, disabled write, stale version, and fallback.
- Report changed files and validation.
```

## 6. Batch 14.3 — Evaluation Runs Persistence

### Goal

Persist compact evaluation run summaries in `evaluation_runs` safely and intentionally, while keeping dry-run/no-artifacts behavior as default.

### Why it matters

- Gives demo/judging a durable record of evaluation metrics.
- Enables dashboard UI in Batch 14.4.
- Avoids relying only on terminal output.

### Current repo state

- `src/mongodb.py` has `get_evaluation_runs_collection()`.
- `src/recommendation/schemas.py` has `EvaluationRunDocument`.
- `src/evaluation/personalization_eval.py` includes persistence helper.
- `scripts/run_personalization_evaluation.py` supports `--write-evaluation-run`.
- `scripts/create_behavior_indexes.py` has `evaluation_runs` indexes.
- Current `evaluation_runs` may be empty; this is acceptable.
- Current `--write-evaluation-run` is explicit but does not currently require a confirmation string; this batch proposes adding confirmation before encouraging live persistence.

### Proposed design

Formalize evaluation persistence as explicit write flow:

```text
run evaluation
  -> always print summary
  -> optionally write local artifacts with --write-artifacts
  -> optionally persist compact evaluation_runs with --write-evaluation-run --confirm EVAL_RUN_WRITE
```

If current script has `--write-evaluation-run` without confirmation, add a confirmation requirement before future live use.

### MongoDB collections/schema

Use:

- `evaluation_runs`

Proposed schema extension:

- `run_id`
- `algorithm_version`
- `ranking_version`
- `data_label`
- `synthetic_data`
- `metrics`
- `baseline_summaries`
- `comparisons`
- `live_state_counts`
- `artifacts`
- `caveat`
- `created_at`

Indexes:

- unique `run_id`
- compound `{ algorithm_version, ranking_version, created_at }`
- optional `{ data_label, created_at }`

### Backend changes

Possible files:

- `scripts/run_personalization_evaluation.py`
  - add `--confirm EVAL_RUN_WRITE` when `--write-evaluation-run`.
  - print target DB before write, without URI.
  - keep `--dry-run` incompatible with write.
- `src/evaluation/personalization_eval.py`
  - ensure persisted document includes caveat and compact summaries.
- `src/recommendation/schemas.py`
  - extend `EvaluationRunDocument` backward-compatibly.

Do not write evaluation run during tests unless using fake collection.

### Frontend changes

None in this batch.

### API changes

None in this batch. API read endpoint belongs to Batch 14.4.

### Config/env changes

Optional:

```text
ENABLE_EVALUATION_RUN_PERSISTENCE=false
EVALUATION_RUN_CONFIRMATION=EVAL_RUN_WRITE
```

If avoiding config churn, keep CLI confirmation only.

### Tests to add/update

- `tests/test_personalization_evaluation.py`
  - write requires confirmation.
  - dry-run cannot combine with write.
  - persisted doc shape includes caveat/version/baselines.
  - no local artifacts by default.
  - fake collection insert only in test.

### Docs to update

- `RUNBOOK.md`
- `TESTING.md`
- `.env.example` only if config flags added.

### Commands to verify

```bash
python -m pytest tests/test_personalization_evaluation.py -q -p no:cacheprovider
python scripts/run_personalization_evaluation.py --dry-run --no-artifacts
python scripts/run_personalization_evaluation.py --dry-run --write-artifacts
```

Do not run:

```bash
python scripts/run_personalization_evaluation.py --write-evaluation-run
```

unless human explicitly confirms.

### Acceptance criteria

- Default evaluation remains read-only/no-artifacts under `--dry-run`.
- MongoDB persistence requires explicit flag and confirmation.
- Persisted summary is compact, caveated and versioned.
- No fake metrics.
- Tests pass.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Evaluation writes live unexpectedly | Confirmation required; dry-run incompatible |
| Overclaiming synthetic metrics | Store and print caveat |
| Large artifacts in MongoDB | Persist compact summary only |
| Duplicate run ids | unique index and test |

### Rollback plan

- Do not use `--write-evaluation-run`.
- Disable API/dashboard consuming `evaluation_runs`.
- Revert script/schema changes.

### AI coding prompt for implementation

```text
Implement Phase 14.3 Evaluation Runs Persistence only.

Allowed files:
- scripts/run_personalization_evaluation.py
- src/evaluation/personalization_eval.py
- src/recommendation/schemas.py only for backward-compatible EvaluationRunDocument fields
- tests/test_personalization_evaluation.py
- RUNBOOK.md, TESTING.md, .env.example if config is added

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- ranking/scoring services

Requirements:
- Dry-run remains no-write.
- MongoDB evaluation_runs persistence requires explicit flag and confirmation.
- Persist caveat, algorithm_version, ranking_version, baselines, comparisons, live counts.
- Do not fabricate metrics.
- Add tests and docs.
```

## 7. Batch 14.4 — Evaluation Dashboard UI

### Goal

Add a read-only dashboard surface for latest evaluation runs, metrics, versions and caveats.

### Why it matters

- Judges can see profile-only vs profile+CF evidence without reading terminal logs.
- Keeps observability inside the React website.
- Makes synthetic caveat visible and honest.

### Current repo state

- `frontend/src/pages/DebugPage.tsx` already shows technical/debug data.
- `scripts/run_personalization_evaluation.py` can optionally persist `evaluation_runs`.
- `evaluation_runs` may be empty; UI must handle empty state.

### Proposed design

Add read-only API endpoints and UI section under Debug/Admin:

```text
Debug page
  -> Evaluation Runs card
  -> latest run
  -> baseline comparison table
  -> algorithm/ranking version
  -> synthetic caveat
  -> raw JSON collapsible
```

Do not run evaluation from browser in first version. Read only.

### MongoDB collections/schema

Use:

- `evaluation_runs`

No new collection.

### Backend changes

Possible files:

- `src/api/routes_debug.py` or new `src/api/routes_evaluation.py`
  - `GET /api/evaluation/runs/latest`
  - `GET /api/evaluation/runs?limit=10`
  - `GET /api/evaluation/runs/{run_id}`
- `src/api/app.py`
  - include router if new file.

Routes must be read-only.

### Frontend changes

Possible files:

- `frontend/src/lib/api.ts`
  - evaluation run types and fetchers.
- `frontend/src/pages/DebugPage.tsx`
  - add Evaluation section/tab/card.
- `frontend/src/components/EvaluationSummaryCard.tsx` (new)
- `frontend/src/components/MetricCard.tsx` (if not existing)
- `frontend/src/test/app.routes.test.tsx`

### API changes

Response shape:

```json
{
  "ok": true,
  "latest": {
    "run_id": "...",
    "algorithm_version": "...",
    "ranking_version": "...",
    "data_label": "synthetic_demo",
    "caveat": "...",
    "baseline_summaries": [],
    "comparisons": [],
    "created_at": "..."
  },
  "empty": false
}
```

Empty state:

```json
{
  "ok": true,
  "latest": null,
  "empty": true,
  "message": "No persisted evaluation runs yet. Use scripts/run_personalization_evaluation.py --write-evaluation-run after human approval."
}
```

### Config/env changes

```text
ENABLE_EVALUATION_RUNS_API=true
```

If disabled:

- endpoint returns 404 or `enabled=false`,
- UI hides card or shows disabled state.

### Tests to add/update

Backend:

- `tests/test_api_evaluation_runs.py` (new)
  - latest empty state.
  - latest run shape.
  - list limit capped.
  - no writes.

Frontend:

- `frontend/src/test/app.routes.test.tsx`
  - Debug page renders evaluation empty state.
  - Debug page renders baseline table when mocked run exists.
  - Caveat visible.

### Docs to update

- `RUNBOOK.md`
- `TESTING.md`

### Commands to verify

```bash
python -m pytest tests/test_api_evaluation_runs.py tests/test_api_smoke.py -q -p no:cacheprovider
cd frontend
npm run build
npm run test:ui -- --run
```

### Acceptance criteria

- Dashboard is read-only.
- Empty state works.
- Synthetic/demo caveat visible.
- Baselines and versions visible.
- Raw JSON collapsible.
- No backend evaluation job is triggered from UI.
- Tests pass.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| UI implies metrics are live truth | Prominent synthetic/demo caveat |
| API writes or runs evaluation | Read-only endpoints only |
| Empty `evaluation_runs` breaks UI | Test empty state |
| Debug page becomes cluttered | Collapsible details and concise metric cards |

### Rollback plan

- Hide Evaluation section.
- Disable `ENABLE_EVALUATION_RUNS_API`.
- Revert route/UI files.

### AI coding prompt for implementation

```text
Implement Phase 14.4 Evaluation Dashboard UI only.

Allowed files:
- src/api/app.py
- src/api/routes_evaluation.py or src/api/routes_debug.py read-only additions
- frontend/src/lib/api.ts
- frontend/src/pages/DebugPage.tsx
- optional frontend/src/components/EvaluationSummaryCard.tsx
- tests/test_api_evaluation_runs.py
- tests/test_api_smoke.py
- frontend/src/test/app.routes.test.tsx
- RUNBOOK.md, TESTING.md

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- evaluation ranking logic

Requirements:
- Read-only endpoints only.
- Empty state if no evaluation_runs.
- Show caveat, versions, baselines, comparisons.
- Raw JSON collapsible.
- Add backend and frontend tests.
```

## 8. Batch 14.5 — Seller Add Product Flow

### Goal

Add a safe seller product draft flow that can preview validation, HyPE/proposition generation and indexing impact before any catalog write.

### Why it matters

- Extends cold-start story from buyer recommendation to seller onboarding.
- Demonstrates how new products enter the system.
- High demo value, but high risk because it touches catalog/indexing boundary.

### Current repo state

- `src/schemas.py` has item/retrieval-unit related models and seller-enriched fields such as `seller_confirmed`.
- `src/indexing.py` handles existing indexing flow.
- `items` and `retrieval_units` are protected core collections.
- No production seller UI/API is implemented.

### Proposed design

Use staged drafts first:

```text
seller submits draft
  -> seller_product_drafts
  -> validate
  -> dry-run indexing preview
  -> human/admin explicit confirmation
  -> additive insert into items + retrieval_units
  -> optional item_hype_profile rebuild for new item
```

No draft can overwrite existing MVP/Amazon items.

### MongoDB collections/schema

New collection:

- `seller_product_drafts`

Draft schema:

```json
{
  "_id": "draft_...",
  "draft_id": "draft_...",
  "seller_id": "seller_demo_001",
  "status": "draft|validated|previewed|approved|indexed|failed|rejected",
  "title": "...",
  "description": "...",
  "brand": "...",
  "category_id": "...",
  "price": 1999,
  "price_bucket": "mid",
  "image_url": "...",
  "attributes": {},
  "validation_errors": [],
  "validation_warnings": [],
  "proposed_item_id": "seller_demo_001_slug_hash",
  "indexing_preview": {
    "hype_units": [],
    "proposition_units": [],
    "embedding_model": "BAAI/bge-m3",
    "estimated_retrieval_units": 0
  },
  "source": {
    "type": "seller",
    "web_enrichment_ids": [],
    "seller_confirmed": false
  },
  "created_at": "...",
  "updated_at": "...",
  "approved_at": null,
  "indexed_at": null
}
```

Indexes:

- unique `{ draft_id: 1 }`
- `{ seller_id: 1, created_at: -1 }`
- `{ status: 1, updated_at: -1 }`
- optional unique `{ proposed_item_id: 1 }` partial when proposed item exists.

### Backend changes

Possible files:

- `src/config.py`
  - `enable_seller_tools`
  - `seller_index_confirm_string`
- `src/mongodb.py`
  - `get_seller_product_drafts_collection()`
- `src/seller/schemas.py` (new)
- `src/seller/drafts.py` (new)
  - validation,
  - draft persistence,
  - item_id generation,
  - indexing preview.
- `src/seller/indexing_preview.py` (new)
  - calls existing text generation/embedding/indexing helpers in dry-run mode.
- `src/api/routes_seller.py` (new)
- `src/api/app.py`
  - include router.
- `scripts/create_behavior_indexes.py` or new index script
  - add dry-run index specs for `seller_product_drafts`.

Only the approved-index step may write to `items` / `retrieval_units`, and only after explicit confirmation.

### Frontend changes

Possible files:

- `frontend/src/pages/SellerDraftPage.tsx` (new)
- `frontend/src/components/SellerDraftForm.tsx` (new)
- `frontend/src/components/IndexingPreview.tsx` (new)
- `frontend/src/lib/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/test/app.routes.test.tsx`

UI must clearly label:

- draft,
- preview,
- not indexed yet,
- explicit admin/seller confirmation required.

### API changes

Recommended endpoints:

```text
POST /api/seller/drafts
GET /api/seller/drafts
GET /api/seller/drafts/{draft_id}
POST /api/seller/drafts/{draft_id}/validate
POST /api/seller/drafts/{draft_id}/index-preview
POST /api/seller/drafts/{draft_id}/approve-index
```

`approve-index` requires:

- `write=true`,
- `confirm=INDEX_SELLER_DRAFT`,
- draft status `previewed`,
- no existing item with proposed `item_id`,
- validated retrieval unit preview.

### Config/env changes

```text
ENABLE_SELLER_TOOLS=false
SELLER_INDEX_CONFIRMATION=INDEX_SELLER_DRAFT
SELLER_DRAFT_MAX_PREVIEW_UNITS=20
```

No secrets.

### Tests to add/update

Backend:

- `tests/test_seller_drafts.py`
  - create draft validates fields.
  - validation catches missing title/description/category.
  - item_id strategy avoids overwrite.
  - preview is dry-run and writes no catalog docs.
  - approve-index refuses without confirmation.
  - approve-index refuses existing item_id.
  - no overwrite of existing `items`.
- `tests/test_api_seller.py`
  - endpoint smoke with fake collections.

Frontend:

- `frontend/src/test/app.routes.test.tsx`
  - seller draft page renders behind flag.
  - preview warning visible.
  - confirmation UI disabled by default.

### Docs to update

- `README.md`
- `RUNBOOK.md`
- `TESTING.md`
- `.env.example`

### Commands to verify

```bash
python -m pytest tests/test_seller_drafts.py tests/test_api_seller.py -q -p no:cacheprovider
python -m pytest tests/test_indexing.py tests/test_pipeline.py -q -p no:cacheprovider
cd frontend
npm run build
npm run test:ui -- --run
```

Dry-run preview command if script exists:

```bash
python scripts/preview_seller_product_indexing.py --draft-id <draft_id> --dry-run
```

### Acceptance criteria

- Draft staging works.
- Validation catches bad input.
- Indexing preview is dry-run by default.
- No default writes to `items` / `retrieval_units`.
- Approved write is additive only and requires explicit confirmation.
- Existing MVP/Amazon items cannot be overwritten.
- Indexing failure keeps draft recoverable with `status=failed`.
- Tests and docs pass.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Corrupt catalog | Stage drafts, additive insert only, no overwrite |
| Retrieval unit schema mismatch | Reuse existing schemas/indexing helpers and tests |
| LLM/Ollama unavailable | Preview can fail gracefully; no partial catalog write |
| Seller flow becomes production auth problem | Gate behind `ENABLE_SELLER_TOOLS`; pair with auth batch later |

### Rollback plan

- Set `ENABLE_SELLER_TOOLS=false`.
- Hide frontend seller route.
- Keep `seller_product_drafts` staged docs; no catalog rollback needed if no approved writes.
- If approved test data was added, remove only documented seller-prefixed item IDs after human confirmation.

### AI coding prompt for implementation

```text
Implement Phase 14.5 Seller Add Product Flow only.

Allowed files:
- src/config.py
- src/mongodb.py
- src/seller/schemas.py
- src/seller/drafts.py
- src/seller/indexing_preview.py
- src/api/app.py
- src/api/routes_seller.py
- scripts/create_behavior_indexes.py or a seller index dry-run script
- frontend/src/App.tsx
- frontend/src/lib/api.ts
- frontend/src/pages/SellerDraftPage.tsx
- frontend/src/components/SellerDraftForm.tsx
- frontend/src/components/IndexingPreview.tsx
- tests/test_seller_drafts.py
- tests/test_api_seller.py
- frontend/src/test/app.routes.test.tsx
- README.md, RUNBOOK.md, TESTING.md, .env.example

Forbidden files unless explicitly approved:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py rewrites
- .env

Requirements:
- Stage drafts in seller_product_drafts.
- Preview is dry-run.
- Approved catalog write requires write=true and confirm=INDEX_SELLER_DRAFT.
- Never overwrite existing items/retrieval_units.
- No fake product recommendations.
- Add tests, docs, rollback notes.
```

## 9. Batch 14.6 — Tavily / Web Enrichment

### Goal

Optionally enrich seller drafts with external web context while preserving provenance, confidence and seller confirmation.

### Why it matters

- Improves seller product descriptions and retrieval text.
- Demonstrates extensible enrichment pipeline.
- Must be optional due external API credentials and provenance risk.

### Current repo state

- No Tavily/web enrichment provider is implemented.
- Canonical plan classifies Tavily/web enrichment as Advanced/Future.
- Seller flow is not production-ready; enrichment should attach to staged drafts, not catalog directly.

### Proposed design

Provider abstraction:

```text
seller draft
  -> optional enrichment request
  -> provider returns candidates with source URLs
  -> store enrichment suggestions with provenance
  -> seller/admin reviews and confirms selected fields
  -> no automatic overwrite
```

External calls disabled by default. Tests use fake provider only.

### MongoDB collections/schema

New collection:

- `web_enrichment_requests`

Schema:

```json
{
  "request_id": "enrich_...",
  "draft_id": "draft_...",
  "provider": "tavily",
  "status": "dry_run|requested|completed|failed|reviewed",
  "query": "...",
  "results": [
    {
      "title": "...",
      "url": "...",
      "snippet": "...",
      "confidence": 0.72,
      "field_suggestions": {
        "description": "...",
        "attributes": {}
      }
    }
  ],
  "selected_result_ids": [],
  "seller_confirmed_fields": {},
  "created_at": "...",
  "updated_at": "..."
}
```

Indexes:

- unique `{ request_id: 1 }`
- `{ draft_id: 1, created_at: -1 }`
- `{ provider: 1, status: 1 }`

### Backend changes

Possible files:

- `src/config.py`
  - `enable_web_enrichment`
  - `tavily_api_key_present` should not expose key
  - `web_enrichment_provider`
- `src/mongodb.py`
  - `get_web_enrichment_requests_collection()`
- `src/enrichment/providers.py` (new)
  - interface/protocol.
- `src/enrichment/tavily_provider.py` (new)
  - lazy import/http client; no call if key missing.
- `src/enrichment/service.py` (new)
  - dry-run and write modes.
- `src/api/routes_enrichment.py` (new)
- `src/api/app.py`

No catalog writes in this batch.

### Frontend changes

Possible files:

- `frontend/src/pages/SellerDraftPage.tsx`
- `frontend/src/components/WebEnrichmentPanel.tsx` (new)
- `frontend/src/lib/api.ts`

UI:

- Show provider disabled state if no API key.
- Show provenance/source URL.
- Show confidence.
- Require seller/admin confirmation to apply suggestion to draft.

### API changes

```text
POST /api/enrichment/drafts/{draft_id}/preview
POST /api/enrichment/drafts/{draft_id}/request
POST /api/enrichment/drafts/{draft_id}/apply
```

`request` requires:

- feature enabled,
- API key configured,
- explicit user action.

`apply` updates draft fields only, not catalog.

### Config/env changes

```text
ENABLE_WEB_ENRICHMENT=false
WEB_ENRICHMENT_PROVIDER=tavily
TAVILY_API_KEY=
WEB_ENRICHMENT_TIMEOUT_SECONDS=10
```

Do not commit real API key.

### Tests to add/update

- `tests/test_web_enrichment.py`
  - disabled without key.
  - fake provider returns suggestions.
  - provenance required.
  - apply writes draft only.
  - no live API call in tests.
- `tests/test_api_enrichment.py`
  - endpoints disabled/enabled.

Frontend:

- test disabled state and provenance display.

### Docs to update

- `.env.example`
- `RUNBOOK.md`
- `TESTING.md`
- seller docs after seller flow exists.

### Commands to verify

```bash
python -m pytest tests/test_web_enrichment.py tests/test_api_enrichment.py -q -p no:cacheprovider
cd frontend
npm run build
npm run test:ui -- --run
```

No real Tavily call in default tests.

### Acceptance criteria

- Disabled by default.
- Missing API key does not crash app.
- Fake provider tests cover enrichment flow.
- Provenance/source URLs stored.
- Suggestions do not auto-overwrite seller fields.
- No catalog writes.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| External API secret leak | Never print key; `.env.example` placeholder only |
| Hallucinated enrichment | Require source URL/confidence; seller confirmation |
| Test flakiness from live API | Fake provider in tests |
| Catalog contamination | Apply only to draft; seller index batch handles catalog |

### Rollback plan

- Set `ENABLE_WEB_ENRICHMENT=false`.
- Hide enrichment panel.
- Keep staged enrichment docs or ignore them.
- No catalog rollback needed.

### AI coding prompt for implementation

```text
Implement Phase 14.6 Tavily/Web Enrichment only.

Allowed files:
- src/config.py
- src/mongodb.py
- src/enrichment/*
- src/api/app.py
- src/api/routes_enrichment.py
- frontend/src/lib/api.ts
- frontend/src/components/WebEnrichmentPanel.tsx
- seller page files if already present
- tests/test_web_enrichment.py
- tests/test_api_enrichment.py
- frontend tests
- .env.example, RUNBOOK.md, TESTING.md

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- items/retrieval_units writes

Requirements:
- Feature disabled by default.
- No live external API in tests.
- No API key printed.
- Store provenance/source URLs/confidence.
- Do not auto-overwrite seller fields or catalog.
```

## 10. Batch 14.7 — Async / Batch Workers

### Goal

Standardize long-running rebuild/evaluation/indexing jobs with a job registry and `job_runs` tracking, without requiring Celery/Redis initially.

### Why it matters

- Current scripts work but are manual.
- Debug/admin UI can display job status and next rebuild steps.
- Gives safer production path for builders.

### Current repo state

Existing scripts:

- `scripts/build_item_hype_profiles.py`
- `scripts/seed_synthetic_clickstream.py`
- `scripts/build_user_item_signals.py`
- `scripts/build_user_profiles.py`
- `scripts/build_item_item_cf.py`
- `scripts/build_item_semantic_neighbors.py`
- `scripts/run_personalization_evaluation.py`
- `scripts/reset_demo_behavior_data.py`

Existing debug endpoints can process/rebuild some data. There is no general job registry.

### Proposed design

Start with synchronous/in-process job registry:

```text
job definition
  -> dry-run plan
  -> optional write run with confirmation
  -> job_runs document
  -> status and summary visible in debug UI
```

Do not add Celery/Redis in first implementation.

### MongoDB collections/schema

New collection:

- `job_runs`

Schema:

```json
{
  "job_run_id": "job_...",
  "job_name": "build_user_profiles",
  "mode": "dry_run|write",
  "status": "queued|running|succeeded|failed|cancelled",
  "requested_by": "admin|script",
  "confirmation": "redacted_or_boolean",
  "params": {},
  "summary": {},
  "error": null,
  "started_at": "...",
  "finished_at": null,
  "created_at": "...",
  "updated_at": "..."
}
```

Indexes:

- unique `{ job_run_id: 1 }`
- `{ job_name: 1, created_at: -1 }`
- `{ status: 1, updated_at: -1 }`

### Backend changes

Possible files:

- `src/config.py`
  - `enable_job_runs`
- `src/mongodb.py`
  - `get_job_runs_collection()`
- `src/jobs/registry.py` (new)
  - job definitions and allowed params.
- `src/jobs/runner.py` (new)
  - dry-run/write execution wrapper.
- `src/jobs/schemas.py` (new)
- `src/api/routes_jobs.py` (new)
- `src/api/app.py`

Jobs should call existing builder functions, not duplicate logic.

### Frontend changes

Possible files:

- `frontend/src/pages/DebugPage.tsx`
- `frontend/src/components/JobRunsPanel.tsx` (new)
- `frontend/src/lib/api.ts`

UI:

- list recent job runs,
- dry-run buttons,
- write buttons hidden/disabled unless confirmation typed,
- protected collection warning.

### API changes

```text
GET /api/admin/jobs
GET /api/admin/jobs/runs?limit=20
POST /api/admin/jobs/{job_name}/dry-run
POST /api/admin/jobs/{job_name}/run
```

Write run requires:

- `write=true`,
- job-specific confirmation,
- admin role in later auth batch.

### Config/env changes

```text
ENABLE_JOB_RUNS=false
JOB_RUNS_WRITE_CONFIRMATION=RUN_JOB_WRITE
JOB_RUNS_MAX_LIMIT=5000
```

### Tests to add/update

- `tests/test_job_registry.py`
  - allowed jobs list.
  - dry-run does not write target collections.
  - write refuses without confirmation.
  - unknown job refused.
  - job summary persisted only when enabled/fake collection.
- `tests/test_api_jobs.py`
  - endpoint smoke.

Frontend tests:

- debug page job panel empty state.
- write confirmation UI.

### Docs to update

- `RUNBOOK.md`
- `TESTING.md`
- `.env.example`

### Commands to verify

```bash
python -m pytest tests/test_job_registry.py tests/test_api_jobs.py -q -p no:cacheprovider
python -m pytest tests/test_reset_demo_behavior_data.py tests/test_demo_reset.py -q -p no:cacheprovider
cd frontend
npm run build
npm run test:ui -- --run
```

### Acceptance criteria

- No Celery/Redis required.
- Dry-run job path works.
- Write path refuses without confirmation.
- Existing scripts/builders remain usable.
- Job status is visible.
- No duplicate builder logic.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Admin job writes by accident | Disabled default, confirmation, tests |
| Logic duplicated from scripts | Registry wraps existing service functions |
| Long-running request timeout | First version is operational UI only; later move to worker |
| Job state lies | Store explicit status transitions and errors |

### Rollback plan

- Set `ENABLE_JOB_RUNS=false`.
- Hide UI panel.
- Continue using existing scripts.
- Ignore `job_runs` collection.

### AI coding prompt for implementation

```text
Implement Phase 14.7 Async/Batch Workers foundation only.

Allowed files:
- src/config.py
- src/mongodb.py
- src/jobs/*
- src/api/app.py
- src/api/routes_jobs.py
- frontend/src/pages/DebugPage.tsx
- frontend/src/components/JobRunsPanel.tsx
- frontend/src/lib/api.ts
- tests/test_job_registry.py
- tests/test_api_jobs.py
- frontend tests
- .env.example, RUNBOOK.md, TESTING.md

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- external worker infra unless explicitly approved

Requirements:
- No Celery/Redis in first pass.
- Dry-run default.
- Write requires confirmation.
- Wrap existing builders; do not duplicate logic.
- Add tests/docs/rollback.
```

## 11. Batch 14.8 — Redis / Cache Layer

### Goal

Introduce an optional cache abstraction with `none`, `memory`, and later `redis` backends, without making Redis required for local demo.

### Why it matters

- Production latency and repeated read optimization.
- Can support query cache, catalog snapshot cache, evaluation summary cache, session cache.
- Must not destabilize local demo.

### Current repo state

- `src/recommendation/candidate_sources.py` has an in-process catalog snapshot cache.
- Query embedding cache is planned separately.
- No Redis dependency is required.

### Proposed design

Cache interface:

```text
CacheBackend
  get(key)
  set(key, value, ttl_seconds)
  delete(key)
  namespace/version prefix
```

Backends:

- `none`: always miss.
- `memory`: local process dict with TTL.
- `redis`: optional import, only if configured.

Default:

- `CACHE_BACKEND=none`.

### MongoDB collections/schema

No new MongoDB collection required.

This batch should not replace `query_embedding_cache`; it provides generic application cache for ephemeral values.

### Backend changes

Possible files:

- `src/config.py`
  - `cache_backend`
  - `redis_url`
  - `cache_version`
  - TTL settings.
- `src/cache/backends.py` (new)
- `src/cache/keys.py` (new)
- `src/cache/__init__.py`
- Integration points only after tests:
  - `src/recommendation/candidate_sources.py` for catalog snapshot, if safe.
  - Query cache batch can later use it for memory/redis acceleration but Mongo remains durable cache.

Do not add Redis dependency unless the `redis` backend is implemented and optional. If added, document it as optional.

### Frontend changes

None.

### API changes

Optional debug:

```text
GET /api/debug/cache/status
POST /api/debug/cache/clear
```

`clear` must be admin-only later; for first pass prefer no API write/clear endpoint.

### Config/env changes

```text
CACHE_BACKEND=none
CACHE_VERSION=cache_v1
REDIS_URL=
CACHE_DEFAULT_TTL_SECONDS=300
```

### Tests to add/update

- `tests/test_cache_backend.py`
  - none backend always misses.
  - memory backend set/get/delete/TTL.
  - redis backend skipped if dependency/config absent.
  - versioned keys.
  - app works with missing Redis package.
- integration tests only for one safe call path.

### Docs to update

- `.env.example`
- `RUNBOOK.md`
- `TESTING.md`

### Commands to verify

```bash
python -m pytest tests/test_cache_backend.py -q -p no:cacheprovider
python -m pytest tests/test_api_smoke.py tests/test_pipeline.py -q -p no:cacheprovider
```

### Acceptance criteria

- App runs with `CACHE_BACKEND=none`.
- Memory backend works in tests.
- Redis optional and not required.
- Missing Redis does not break imports.
- Cache keys are versioned.
- Safe invalidation documented.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Redis dependency breaks teammate machines | optional lazy import; default none |
| Stale cache after ranking/version change | versioned keys include `CACHE_VERSION` and algorithm/ranking when relevant |
| Cache hides live DB issue | disable flag and tests for none backend |
| Overbroad clear endpoint | defer API clear until auth batch |

### Rollback plan

- Set `CACHE_BACKEND=none`.
- Revert cache integrations.
- Existing in-process candidate cache can remain independent.

### AI coding prompt for implementation

```text
Implement Phase 14.8 Redis/Cache Layer foundation only.

Allowed files:
- src/config.py
- src/cache/*
- tests/test_cache_backend.py
- optional safe integration file only after tests
- .env.example, RUNBOOK.md, TESTING.md

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- required Redis dependency without fallback

Requirements:
- CACHE_BACKEND defaults to none.
- Memory backend tested.
- Redis backend optional/lazy.
- App imports without Redis installed.
- Versioned cache keys and invalidation docs.
```

## 12. Batch 14.9 — Production Auth / Privacy

### Goal

Add role-based guards and privacy masking for production-like usage while preserving local demo mode.

### Why it matters

- Debug/write endpoints expose sensitive user behavior/profile data.
- Seller/admin flows require role separation.
- Production demos should not expose raw user lineage to every user.

### Current repo state

- `users` schema includes privacy flags.
- API currently behaves as local/demo system.
- Debug/admin endpoints exist and can trigger writes when flags/confirmations are provided.
- No production auth is implemented.

### Proposed design

Auth modes:

```text
AUTH_MODE=disabled|demo|production
```

Roles:

- `demo_user`
- `admin`
- `seller`

First pass:

- Demo mode header/token guard for admin endpoints.
- No hardcoded secret.
- Production mode rejects missing/invalid role credentials.
- Privacy masking for debug user data.

### MongoDB collections/schema

Use existing:

- `users.privacy`

Optional new collection later:

- `api_keys` or `auth_sessions`

Do not implement full user auth database in first pass unless necessary.

### Backend changes

Possible files:

- `src/config.py`
  - `auth_mode`
  - `demo_admin_enabled`
  - `admin_token_hash`
  - `seller_tools_auth_required`
- `src/api/auth.py` (new)
  - dependency helpers:
    - `require_admin`
    - `require_seller`
    - `current_demo_user`
  - token hash check.
- `src/api/routes_debug.py`
  - protect write/debug endpoints.
- `src/api/routes_seller.py`
  - seller role guard if seller batch exists.
- `src/api/routes_users.py`
  - respect privacy flags.

Never hardcode token in source.

### Frontend changes

Possible files:

- `frontend/src/lib/api.ts`
  - optional auth header support from local config/session.
- `frontend/src/pages/DebugPage.tsx`
  - show admin locked state when not authorized.
- `frontend/src/components/AdminGuardNotice.tsx` (new)

No real credential UI required for first pass; local demo can use disabled/demo mode.

### API changes

Protect:

- `/api/debug/*`
- `/api/demo/reset`
- `/api/demo/seed`
- `/api/debug/process-events`
- `/api/debug/rebuild-profiles`
- `/api/debug/rebuild-cf`
- future seller approve-index.

### Config/env changes

```text
AUTH_MODE=disabled
DEMO_ADMIN_ENABLED=true
ADMIN_TOKEN_HASH=
SELLER_TOOLS_AUTH_REQUIRED=true
PRIVACY_MASK_DEBUG_DATA=true
```

### Tests to add/update

- `tests/test_api_auth.py`
  - disabled mode allows existing demo tests.
  - production mode rejects debug write without token.
  - admin token hash passes.
  - no raw token printed.
  - privacy masking hides raw event/profile details when requested.
- update API smoke to account for default disabled mode.

Frontend:

- debug page locked state test.

### Docs to update

- `.env.example`
- `RUNBOOK.md`
- `TESTING.md`
- security/privacy notes.

### Commands to verify

```bash
python -m pytest tests/test_api_auth.py tests/test_api_smoke.py -q -p no:cacheprovider
python -m pytest tests/test_demo_reset.py tests/test_reset_demo_behavior_data.py -q -p no:cacheprovider
cd frontend
npm run build
npm run test:ui -- --run
```

### Acceptance criteria

- Default local demo still works.
- Production mode protects debug/write endpoints.
- No hardcoded tokens/secrets.
- Privacy masking works.
- Tests pass.
- Docs explain modes clearly.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Auth breaks local demo | default `AUTH_MODE=disabled`; tests for demo mode |
| Secret leaks | only token hash env; never print token |
| Debug UI unusable | clear locked state and docs |
| Incomplete production security | label as guard, not full enterprise auth |

### Rollback plan

- Set `AUTH_MODE=disabled`.
- Revert auth dependency additions.
- Existing demo route behavior restored.

### AI coding prompt for implementation

```text
Implement Phase 14.9 Production Auth/Privacy guard only.

Allowed files:
- src/config.py
- src/api/auth.py
- src/api/routes_debug.py
- src/api/routes_users.py if privacy masking needed
- seller route files if already implemented
- frontend/src/lib/api.ts
- frontend/src/pages/DebugPage.tsx
- tests/test_api_auth.py
- tests/test_api_smoke.py
- frontend tests
- .env.example, RUNBOOK.md, TESTING.md

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- hardcoded tokens

Requirements:
- AUTH_MODE disabled/demo/production.
- Default local demo still works.
- Protect debug/write endpoints in production mode.
- No secret printed.
- Privacy masking for debug data.
- Add tests/docs.
```

## 13. Batch 14.10 — Fusion Comparison

### Goal

Compare native `$rankFusion` / `$scoreFusion` against the current `$unionWith` + manual RRF path without changing the default search behavior.

### Why it matters

- Demonstrates awareness of newer Atlas Search features.
- Provides evidence for why current manual fusion is stable.
- Helps future optimization decisions.

### Current repo state

- `src/search_pipeline.py` includes optional `PipelineMode = "auto" | "rankFusion" | "unionWith"`.
- Default runtime path should remain current stable manual `$unionWith` / RRF.
- `scripts/run_search.py` supports mode selection.
- Canonical plan says `$rankFusion` / `$scoreFusion` is future comparison only.
- Current repo has an implemented `$rankFusion` pipeline builder. It does **not** have an implemented `$scoreFusion` branch.

### Proposed design

Add comparison script/report:

```text
for each query
  -> run unionWith mode
  -> run rankFusion mode if supported by current code/Atlas tier
  -> optionally add a proposed scoreFusion branch only in this comparison batch, never as default
  -> compare latency, top-k overlap, score distribution, explanation completeness
  -> write local report only if --write-artifacts
  -> no MongoDB writes
```

If Atlas tier does not support native fusion:

- skip gracefully,
- mark unsupported,
- do not fail entire script unless `--strict`.

### MongoDB collections/schema

No new collection required initially.

Optional later:

- `fusion_comparison_runs`

Do not create it in first batch.

### Backend/script changes

Possible files:

- `scripts/compare_fusion_strategies.py` (new)
- `src/evaluation/fusion_comparison.py` (new)
- `tests/test_fusion_comparison.py` (new)
- optional docs only.

Do not change `run_search()` default.

### Frontend changes

None in first batch.

Optional later:

- Debug page link to latest local report, not needed now.

### API changes

None.

### Config/env changes

```text
ENABLE_FUSION_COMPARISON=false
FUSION_COMPARISON_STRICT=false
```

Can be CLI-only instead of env.

### Tests to add/update

- `tests/test_fusion_comparison.py`
  - overlap metrics function.
  - unsupported native fusion skip classification.
  - no write by default.
  - default mode remains unionWith/manual path.
- `tests/test_pipeline.py`
  - ensure existing search pipeline tests still pass.

### Docs to update

- `RUNBOOK.md`
- `TESTING.md`

### Commands to verify

```bash
python -m pytest tests/test_fusion_comparison.py tests/test_pipeline.py -q -p no:cacheprovider
python scripts/compare_fusion_strategies.py --dry-run --limit 5
```

### Acceptance criteria

- Default search unchanged.
- Unsupported native fusion skips gracefully.
- Report includes latency, overlap, score distribution and explanation completeness.
- No MongoDB writes.
- Tests pass.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Native fusion unsupported on current tier | graceful skip |
| Accidentally changes default retrieval | tests assert default remains current path |
| Overclaiming comparison | report caveats and sample size |
| Search core modified | forbidden; comparison script calls existing public functions |

### Rollback plan

- Stop using comparison script.
- Revert new evaluation files.
- Default search unaffected.

### AI coding prompt for implementation

```text
Implement Phase 14.10 Fusion Comparison only.

Allowed files:
- scripts/compare_fusion_strategies.py
- src/evaluation/fusion_comparison.py
- tests/test_fusion_comparison.py
- tests/test_pipeline.py if adding guard test only
- RUNBOOK.md, TESTING.md

Forbidden files:
- src/search_pipeline.py changes
- src/query_processor.py
- src/indexing.py
- .env

Requirements:
- Comparison only.
- Default search unchanged.
- Skip gracefully if Atlas tier does not support native fusion.
- No MongoDB writes.
- Add tests/docs.
```

## 14. Cross-cutting — Aggregation Pipeline CF Proof

### Goal

Add a proof path for item-item collaborative filtering built with MongoDB Aggregation Pipeline, without removing or replacing the current Python-side CF builder.

### Why it matters

- Current true CF is implemented in `src/recommendation/item_item_cf.py` from `user_item_signals`.
- If judges expect “Aggregation Pipeline for CF,” this batch creates a clear MongoDB-native proof.
- It should be comparison/proof first, not default production replacement.

### Current state

Current CF:

- module: `src/recommendation/item_item_cf.py`
- script: `scripts/build_item_item_cf.py`
- input: `user_item_signals`
- output: `item_item_cf_edges`
- behavior: Python-side pair generation, support threshold, symmetric edges, evidence fields.
- tests: `tests/test_item_item_cf.py`

### Proposed aggregation pipeline

Input:

- `user_item_signals`

Filters:

- positive signals only:
  - `preference=true`, or
  - `positive_score > negative_score`, or
  - click/cart/purchase counts above threshold.

Conceptual stages:

```text
1. $match positive user_item_signals
2. $project user_id_hash, item_id, positive_score, event_counts, confidence, last_interaction_at
3. $sort by user_id_hash and positive_score/recency
4. $group by user_id_hash -> positive_items array
5. $project capped positive_items to max items per user
6. Generate item pairs per user
7. $unwind pairs
8. $group by pair key -> support, co_click_count, co_cart_count, co_purchase_count, common_user sample
9. $match support >= min_support
10. $lookup item_stats/items for popularity normalization if needed
11. $addFields cf_score, confidence
12. $project directional edge docs or undirected preview docs
13. Optional write to preview collection only with explicit flag
```

Implementation note:

- Pair generation in pure aggregation can be complex. It may use `$range`, `$map`, `$arrayElemAt`, `$reduce`, `$concatArrays`, or a controlled `$function` only if Atlas tier permits and tests document it.
- Prefer pipeline clarity and proof over maximum performance.

### MongoDB collections/schema

Do not write to `item_item_cf_edges` in first proof batch.

Option A, safest:

- no DB output; script prints dry-run summary/sample pipeline results.

Option B, explicit write only:

- `item_item_cf_edges_agg_preview`

Schema:

```json
{
  "pair_id": "itemA::itemB",
  "item_id": "itemA",
  "neighbor_item_id": "itemB",
  "cf_score": 0.123,
  "support": 4,
  "co_click_count": 3,
  "co_cart_count": 1,
  "co_purchase_count": 0,
  "source": "mongodb_aggregation_preview",
  "updated_at": "..."
}
```

Indexes:

- unique `{ item_id: 1, neighbor_item_id: 1 }`
- `{ support: -1, cf_score: -1 }`

Only add preview collection indexes through dry-run reviewed script.

### Backend/script changes

Possible files:

- `src/recommendation/item_item_cf_aggregation.py` (new)
  - builds aggregation pipeline.
  - normalizes preview docs.
  - compares output with Python builder.
- `scripts/build_item_item_cf_aggregation_preview.py` (new)
  - `--dry-run` default.
  - `--write-preview` explicit.
  - `--confirm AGG_CF_PREVIEW_WRITE` if writing preview collection.
- `tests/test_item_item_cf_aggregation.py` (new)
- optional `scripts/create_behavior_indexes.py`
  - add preview index specs only after review.

Do not modify existing `src/recommendation/item_item_cf.py` except maybe shared constants import if necessary and safe.

### Frontend changes

Optional later:

- Debug page can show “Aggregation CF proof available” status.

Not required in first proof batch.

### API changes

None in first proof batch.

Optional later:

```text
GET /api/debug/cf/aggregation-proof
```

read-only summary only.

### Config/env changes

```text
ENABLE_AGG_CF_PROOF=false
AGG_CF_MIN_SUPPORT=2
AGG_CF_MAX_ITEMS_PER_USER=40
```

CLI args can override.

### Tests to add/update

- `tests/test_item_item_cf_aggregation.py`
  - pipeline contains only read stages for dry-run.
  - no `$out`, `$merge`, `$delete`, `$function` unless explicitly allowed and tested.
  - support threshold applied.
  - semantic embeddings are not used.
  - output fields include support/co counts/cf_score.
  - comparison helper computes overlap with Python builder output.
- `tests/test_item_item_cf.py`
  - existing Python builder remains green.

### Docs to update

- `README.md`
- `RUNBOOK.md`
- `TESTING.md`
- `bao_cao_phan_tich.md` or audit note after implementation.

### Commands to verify

```bash
python -m pytest tests/test_item_item_cf.py tests/test_item_item_cf_aggregation.py -q -p no:cacheprovider
python scripts/build_item_item_cf_aggregation_preview.py --dry-run --limit-users 20
```

Do not run:

```bash
python scripts/build_item_item_cf_aggregation_preview.py --write-preview
```

without human confirmation.

### Acceptance criteria

- Current Python-side CF remains default.
- Aggregation proof reads from `user_item_signals`, not embeddings.
- Dry-run default.
- No `$out` / `$merge` by default.
- No writes unless explicit preview write + confirmation.
- Comparison summary includes overlap/support differences.
- Tests prove semantic similarity is not used as CF.

### Risk and mitigation

| Risk | Mitigation |
|---|---|
| Pipeline too heavy on live Atlas | limit users/items, dry-run first, explain limits |
| Accidentally replaces production CF | separate module/script/preview collection |
| Uses semantic similarity by mistake | tests inspect fields/stages and input collection |
| Write stage slips into dry-run | tests reject `$out`/`$merge` in dry-run pipeline |

### Rollback plan

- Stop using proof script.
- Delete/ignore preview collection only after human confirmation if ever created.
- Existing `item_item_cf_edges` and Python builder stay unchanged.

### AI coding prompt for implementation

```text
Implement Cross-cutting Aggregation Pipeline CF Proof only.

Allowed files:
- src/recommendation/item_item_cf_aggregation.py
- scripts/build_item_item_cf_aggregation_preview.py
- tests/test_item_item_cf_aggregation.py
- tests/test_item_item_cf.py only for guard additions
- optional docs README.md/RUNBOOK.md/TESTING.md

Forbidden files:
- src/search_pipeline.py
- src/query_processor.py
- src/indexing.py
- .env
- replacing src/recommendation/item_item_cf.py default behavior

Requirements:
- Read user_item_signals only.
- Do not use embeddings for CF.
- Dry-run default.
- No $out/$merge by default.
- Preview collection write requires --write-preview and confirm AGG_CF_PREVIEW_WRITE.
- Python-side CF remains default.
- Add tests and docs.
```

## 15. Cross-batch Testing Strategy

### Unit tests

Every batch must add focused unit tests for pure functions:

- cache key generation,
- onboarding validation,
- seller draft validation,
- auth guard decisions,
- CF aggregation pipeline construction,
- fusion comparison metrics,
- job registry validation.

### Integration/API tests

Add or update FastAPI tests for every route:

- route exists,
- response shape,
- empty state,
- disabled feature state,
- no-write default,
- write refusal without confirmation.

Use fake collections or monkeypatches when possible. Do not require live Atlas for unit/API tests.

### Frontend tests

For UI batches:

```bash
cd frontend
npm run build
npm run test:ui -- --run
```

Tests should cover:

- route renders,
- empty/error/loading state,
- feature disabled state,
- no fake recommendation arrays,
- caveats/labels visible,
- confirmation UI disabled until explicit input.

### Dry-run/no-write tests

For scripts:

- `--dry-run` default behavior,
- `--write` refuses without confirm,
- target collections allowlist,
- protected collections omitted,
- no `$out`/`$merge` in dry-run pipelines.

### Live read-only verification

Only when human wants live confidence:

```bash
python scripts/smoke_test_connection.py --counts
```

Optional read-only checks:

- count relevant collections,
- list indexes,
- list Atlas Search indexes if driver supports it.

No live writes in automated verification unless a batch explicitly requires and human confirms.

### Manual QA checklist

For each UI batch:

- backend starts,
- frontend starts,
- feature flag on/off states,
- main demo still works,
- debug/admin labels honest,
- no 500 errors in network tab,
- no duplicate event spam,
- rollback flag works.

## 16. Cross-batch Documentation Strategy

Update docs with every batch.

### README.md

Add:

- feature summary,
- demo path,
- which Phase 14 features are enabled/disabled,
- high-level safety notes.

### RUNBOOK.md

Add:

- exact commands,
- dry-run/write distinctions,
- confirmation strings,
- Atlas UI checks,
- troubleshooting.

### TESTING.md

Add:

- new test commands,
- expected outputs,
- optional dependency caveats,
- no-write/live-read-only guidance.

### `.env.example`

Add only non-secret placeholders:

- feature flags,
- optional provider key placeholder,
- auth mode placeholders,
- cache config placeholders.

Never update `.env` automatically.

### API docs

If no generated OpenAPI docs are committed, document endpoints in `RUNBOOK.md` or a future `docs/API.md`.

### Demo scripts docs

Document:

- how to run safely,
- what writes,
- what does not write,
- rollback path.

## 17. Rollback Strategy

### Config disable

Every batch must be disable-able:

- `ENABLE_ONBOARDING=false`
- `ENABLE_QUERY_EMBEDDING_CACHE=false`
- `ENABLE_EVALUATION_RUNS_API=false`
- `ENABLE_SELLER_TOOLS=false`
- `ENABLE_WEB_ENRICHMENT=false`
- `ENABLE_JOB_RUNS=false`
- `CACHE_BACKEND=none`
- `AUTH_MODE=disabled`
- `ENABLE_FUSION_COMPARISON=false`
- `ENABLE_AGG_CF_PROOF=false`

### Collection staging

High-risk features use staging/preview collections:

- `seller_product_drafts`
- `web_enrichment_requests`
- `job_runs`
- optional `item_item_cf_edges_agg_preview`

Do not mutate core catalog until explicit confirmation.

### No destructive migration

No Phase 14 batch should require:

- dropping collections,
- dropping indexes,
- rewriting `items`,
- rewriting `retrieval_units`,
- global schema migration.

### Default old path

Default path remains:

- existing user selector,
- existing search pipeline,
- existing homepage/search/similar ranking,
- existing Python-side CF builder,
- existing reset scripts.

### Git rollback

Rollback batch by reverting batch-specific files and docs. Keep commits scoped per batch.

### DB rollback/dry-run

If a batch creates staged docs:

- prefer disabling feature and ignoring staged docs.
- delete staged docs only with human confirmation and scoped filter.
- never use broad drop/delete.

## 18. AI Vibe Coding Workflow

Use this workflow for each batch:

1. **READ ONLY analysis**
   - read canonical plan, roadmap, this future plan, current code.
   - run `git status --short`.
   - identify existing files/contracts.

2. **Plan files to edit**
   - list allowed files.
   - list forbidden files.
   - define tests and acceptance criteria.

3. **Implement minimal batch**
   - keep scope narrow.
   - do not mix batches.
   - avoid unrelated refactors.

4. **Run targeted tests**
   - backend unit/API tests.
   - script dry-run tests.
   - frontend tests if UI changed.

5. **Run build**
   - frontend build if frontend changed.
   - avoid full heavy test suite if optional dependency blocks; document it.

6. **Update docs**
   - README/RUNBOOK/TESTING/.env.example as needed.
   - document feature flag and rollback.

7. **Report result**
   - changed files,
   - tests run,
   - writes performed (should be none unless approved),
   - remaining risks.

8. **Human review**
   - review diff,
   - review feature flags,
   - approve any live write/index apply separately.

9. **Commit**
   - one batch per commit when practical.
   - never commit `.env`, generated artifacts, secrets.

## 19. Definition of Done for Phase 14

Phase 14 Future Improvements can be called 100% complete when:

- Each selected batch has mini-plan, tests, docs and rollback path.
- All implemented features are behind safe flags or no-op safe defaults.
- No implemented batch rewrites search/query/indexing core.
- `items` / `retrieval_units` contracts remain backward-compatible.
- MongoDB connector remains single-source via `src/mongodb.py`.
- No fake recommendations, fake CF evidence or fabricated metrics.
- Onboarding derives profiles through events/signals/profile builder.
- Query cache is versioned and can be disabled.
- Evaluation persistence is explicit and caveated.
- Evaluation dashboard reads real persisted data or shows empty state.
- Seller product flow stages drafts and requires explicit confirmation for additive catalog writes.
- Web enrichment is disabled without API key and stores provenance.
- Job registry dry-run/write semantics are tested.
- Redis/cache layer is optional and app works without Redis.
- Auth/privacy guards protect debug/write endpoints in production mode.
- Fusion comparison does not change default `$unionWith`/RRF behavior.
- Aggregation Pipeline CF proof reads from `user_item_signals` and does not replace Python-side CF by default.
- Backend targeted tests pass.
- Frontend build/tests pass for UI batches.
- Docs and `.env.example` are current.
- Manual QA for affected surfaces is recorded.
- No live MongoDB write/index/reset was run without explicit human approval.

Deferred items can remain deferred only if they are explicitly documented as outside the selected Phase 14 completion scope.

## 20. Final Recommended Roadmap

### Sprint 1 — Low Risk UX / Read-only Improvements

1. Batch 14.1 Onboarding Polish.
2. Batch 14.2 Query Embedding Cache with write disabled by default.
3. Batch 14.3 Evaluation Runs Persistence, but do not write live until human approves.
4. Batch 14.4 Evaluation Dashboard UI with empty state.

Why:

- Highest demo/product value with controlled risk.
- Mostly additive.
- Does not touch catalog/indexing.

### Sprint 2 — Proof / Evaluation Enhancements

1. Cross-cutting Aggregation Pipeline CF Proof.
2. Batch 14.10 Fusion Comparison.

Why:

- Strengthens MongoDB technical story.
- Keeps production defaults unchanged.
- Useful for judge Q&A and post-demo report.

### Sprint 3 — Product Expansion

1. Batch 14.5 Seller Add Product Flow.
2. Batch 14.6 Tavily / Web Enrichment.

Why:

- Strong product story but touches higher-risk catalog/enrichment boundary.
- Should happen after auth/confirmation patterns are trusted.

### Sprint 4 — Production Hardening

1. Batch 14.7 Async / Batch Workers.
2. Batch 14.8 Redis / Cache Layer.
3. Batch 14.9 Production Auth / Privacy.

Why:

- Important for production-readiness but adds operational complexity.
- Not required for current hackathon demo path.

## Appendix A — Source Files Read / Referenced for This Plan

Primary plans/reports:

- `IMPLEMENTATION_PHASE_ROADMAP.md`
- `ColdStart_Killer_Final_Recommendation_Upgrade_Plan.md`
- `ColdStart_Killer_Personalized_Recommendation_Implementation_Plan.md`
- `PLAN_IMPROVEMENTS.md`
- `FINAL_PRE_PUSH_AUDIT_REPORT.md`
- `bao_cao_phan_tich.md`
- `bao_cao_phan_tich_repo.md`

Docs/config:

- `README.md`
- `RUNBOOK.md`
- `TESTING.md`
- `CONTEXT.md`
- `requirements.txt`
- `frontend/package.json`

Core/backend:

- `src/config.py`
- `src/mongodb.py`
- `src/query_processor.py`
- `src/search_pipeline.py`
- `src/indexing.py`
- `src/schemas.py`
- `src/api/*`
- `src/behavior/*`
- `src/recommendation/*`
- `src/evaluation/*`

Frontend:

- `frontend/src/App.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/state/experience.tsx`
- `frontend/src/pages/*`
- `frontend/src/components/*`
- `frontend/src/test/app.routes.test.tsx`

Scripts/tests:

- `scripts/*`
- `tests/*`

## Appendix B — Global No-go Conditions

Stop any Phase 14 implementation if:

- it requires editing `src/search_pipeline.py`, `src/query_processor.py`, or `src/indexing.py` without explicit human approval;
- it requires `.env` secrets;
- it requires live Atlas write/index creation before dry-run and review;
- it introduces fake recommendations, fake CF, or fake metrics;
- it makes Redis/Tavily/Ollama mandatory for app startup;
- it weakens Phase 13 reset safety;
- it creates duplicate MongoDB connector logic;
- it changes default search/recommendation behavior without tests and rollback;
- it cannot define clear acceptance criteria.
