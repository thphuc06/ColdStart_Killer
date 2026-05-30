# ColdStart Killer

ColdStart Killer is a MongoDB Hackathon project for bootstrapping retrieval for brand-new ecommerce products. The system builds a 3,000-item MVP dataset from Amazon Reviews 2023 metadata, generates HyPE queries and propositions via Qwen3:8b (Ollama), embeds with BAAI/bge-m3, and runs hybrid retrieval (vector + BM25) through MongoDB Atlas. The evaluation framework measures retrieval quality across 5 search variants and generates both technical and hackathon-facing reports.

For full clone-to-demo instructions, environment setup, feature flags, troubleshooting, and submission checks, see [PROJECT_SETUP_AND_FULL_RUN_GUIDE.md](PROJECT_SETUP_AND_FULL_RUN_GUIDE.md).

Quick operational docs:

- [DEMO_CHECKLIST.md](DEMO_CHECKLIST.md) — short demo rehearsal checklist.
- [RELEASE_NOTES.md](RELEASE_NOTES.md) — current validated release snapshot.

## Table of Contents

- [Who This Repository Is For](#who-this-repository-is-for)
- [3-Minute Quick Try](#3-minute-quick-try)
- [7-Step Live Demo Script (Short)](#7-step-live-demo-script-short)
- [Current Phase Scope](#current-phase-scope)
- [Phase 14 Demo Quickstart](#phase-14-demo-quickstart)
- [Current Evaluation Status](#current-evaluation-status)
- [Technical Notebook Audit Path](#technical-notebook-audit-path)
- [Known Limitations (Current)](#known-limitations-current)
- [Reproducibility Snapshot](#reproducibility-snapshot)
- [Project Structure](#project-structure)
- [License and Contact](#license-and-contact)

## Who This Repository Is For

- Hackathon judges who need a clear browser-first demo path with evidence-backed claims.
- Technical reviewers who want to verify retrieval quality, latency, and safety caveats from runnable commands.
- Teammates/operators who need a reliable runbook for local setup, demo rehearsal, and guarded maintenance actions.

## 3-Minute Quick Try

Quick prerequisites (assumed for this path):

- Local `.env` is already configured with valid `MONGODB_URI` and `MONGODB_DB_NAME`.
- The target MongoDB demo database already contains `items` and `retrieval_units`.
- Atlas Search indexes for the demo path are already ready.
- Python dependencies are already installed in an active virtual environment.

From repo root:

```bash
python -m uvicorn src.api.app:app --reload
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173`, pick a demo user, and run one search query.

If you need full setup and environment details, use [PROJECT_SETUP_AND_FULL_RUN_GUIDE.md](PROJECT_SETUP_AND_FULL_RUN_GUIDE.md).

## 7-Step Live Demo Script (Short)

1. Start backend and frontend.
2. Select a profile-backed demo user.
3. Open homepage and confirm personalized cards.
4. Open one product detail and inspect score breakdown.
5. Open similar products and verify semantic vs CF signal separation.
6. Run one search query and confirm query-first results with personalized reranking.
7. Open Debug/Admin, verify lineage and protected-collection warnings, and stop at dry-run for reset/rebuild actions.

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
- Optional cold-shopper onboarding for category, price, intent, and real catalog seed-item preferences. Preview is read-only; completion writes only `users.onboarding` and onboarding `clickstream_events`.
- Optional seller draft staging is disabled by default. Full index-preview stores propositions, HyPE embeddings, and lineage in private `seller_indexing_previews`; catalog indexing requires `write=true` and `confirm=INDEX_SELLER_DRAFT`, then commits that exact reviewed bundle.
- Optional web enrichment for seller drafts is disabled by default. Qwen plans up to three Tavily searches, Tavily I/O fans out in parallel, and Qwen synthesizes sourced suggestions into `web_enrichment_requests`; applying selected fields back to the draft with `confirm=APPLY_WEB_ENRICHMENT` never directly writes catalog data.
- Lightweight job registry/status tracking is available for Debug/Admin. It stores compact `job_runs` records only when explicitly tracked, keeps the trigger API disabled by default, and does not replace the existing scripts.
- Optional backend cache abstraction supports `none`, `memory`, and lazy `redis` backends. `CACHE_BACKEND=none` by default, Redis is not required, and the cache is currently limited to compact read-only evaluation/job status endpoints.
- Demo/production auth guards protect Debug/Admin and write-capable Phase 14 actions. `AUTH_MODE=demo` is the default; public search/feed/item routes stay open.
- **Retrieval evaluation** with 5 variants, 50 queries, 20 diagnostic probes, AI-assisted conservative relevance judgments (2,119 query-item pairs labeled using LLM with conservative scoring — human audit recommended before claiming as full ground truth), and IR metrics (NDCG, Recall, MRR, Precision, HitRate, cold-start exposure quality).
- **Hackathon impact reporting** with variant deltas, qualitative examples, business-impact stories, Vietnamese slice analysis, and cold-start caveats.

This phase still does not include:

- A production-hardened seller-facing UI.
- Full OAuth/SSO account management and production identity lifecycle.

## Phase 14 Demo Quickstart

Current demo path is browser-first. Use the React frontend for the hackathon demo, and keep notebooks as technical audit and exploration tools.

Start the backend:

```bash
python -m uvicorn src.api.app:app --reload
```

Check API health:

```bash
python -c "from fastapi.testclient import TestClient; from src.api.app import create_app; import os; c=TestClient(create_app()); print('/api/health', c.get('/api/health').status_code); print('/api/users/demo', c.get('/api/users/demo').status_code); t=os.getenv('ADMIN_TOKEN',''); t and print('/api/demo/status', c.get('/api/demo/status', headers={'X-Admin-Token': t}).status_code)"
```

Start the frontend:

```bash
cd frontend
npm install
npm run build
npm run test:ui -- --run
npm run dev
```

Recommended browser demo flow:

- Short flow: use [7-Step Live Demo Script (Short)](#7-step-live-demo-script-short).
- Detailed rehearsal and safety checks: [DEMO_CHECKLIST.md](DEMO_CHECKLIST.md).
- If seller tools are enabled for the demo, paste a configured seller or admin token into the seller page before create/preview/enrichment/approve-index actions.

Demo safety commands:

```bash
python scripts/reset_demo_behavior_data.py --soft --dry-run
python scripts/reset_demo_behavior_data.py --full --dry-run
```

Do not run live reset unless a human explicitly chooses `--write` and passes the required confirmation string. Reset scripts must never target `items` or `retrieval_units`.

Recommendation honesty:

- Semantic similarity, HyPE matches, and profile embeddings are content/semantic personalization.
- True Collaborative Filtering is `item_item_cf_edges` built from multi-user `user_item_signals`.
- Debug/Admin may label CF evidence as seeded/precomputed when it comes from synthetic demo behavior.
- Onboarding is not direct profile or CF seeding. It captures explicit preferences and weak seed-item events; use the existing behavior/signal/profile pipeline to derive profiles afterward.
- Seller add-product flow is staged. Preview does not write `items` / `retrieval_units`; it prepares a private vector-ready bundle. Approve-index is additive only, refuses collisions, does not rerun LLM/embedding, and upserts the new item's HyPE profile after catalog commit.
- Job orchestration is intentionally lightweight. `/api/jobs/*` is Admin-protected, job triggering is disabled unless `ENABLE_JOB_TRIGGER_API=true`, and CLI dry-runs default to `--no-track` unless a human explicitly requests compact `job_runs` tracking.
- The backend cache layer is separate from Query Embedding Cache. It does not cache write endpoints, raw event histories, secrets, admin tokens, or personalized search/feed responses in the current implementation. Rollback is `CACHE_BACKEND=none`.
- Auth/privacy guardrails keep public demo reads open while requiring admin/seller tokens for Debug/Admin controls, seller approve-index, enrichment request/apply, and job triggers. Live Debug/Admin write controls also require exact confirmation strings such as `SEED_DEMO_BEHAVIOR`, `PROCESS_EVENTS_WRITE`, `APPLY_PENDING_BEHAVIOR_WRITE`, `REBUILD_PROFILES_WRITE`, and `REBUILD_CF_WRITE`. Rollback for local-only emergency is `AUTH_MODE=disabled`.
- Debug apply-pending behavior can be scoped to the current shopper via optional `user_id_hash`, so demo operators can refresh one shopper safely instead of scanning all pending events.
- Judge clarification: CF does not need to be built with MongoDB Aggregation Pipeline. Aggregation Pipeline remains used in search/retrieval/ranking/filtering/evaluation/debug paths; a MongoDB-native CF proof is optional future research, not a current blocker.

## Current Evaluation Status

Latest verified live run:

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/notebook_run
```

Result summary:

| Item | Current value |
|---|---:|
| Retrieval queries | 50 |
| AI-assisted conservative judgments | 2,119 |
| Judged queries | 50 |
| Queries with relevance >= 2 | 43 |
| Live retrieval results | 2,428 |
| Evaluation failures | 0 |
| Report status | sufficient |
| Dataset cold percentage | 100.0% |
| Search P95 latency | 183.8ms |
| Total P95 latency | 956.2ms |

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
| `title_only` | 0.5530 | 0.3154 | 0.4992 | 0.74 | 0.3020 |
| `vector_only` | 0.7191 | 0.4005 | 0.5537 | 0.74 | 0.3727 |
| `bm25_only` | 0.6003 | 0.3257 | 0.5571 | 0.76 | 0.3342 |
| `hybrid_union` | 0.7715 | 0.4525 | 0.6817 | 0.78 | 0.3940 |
| `hybrid_no_cold_boost` | 0.7715 | 0.4525 | 0.6817 | 0.78 | 0.3940 |

Live report artifacts:

- `.runtime/evaluation/notebook_run/metrics_summary.md`
- `.runtime/evaluation/notebook_run/hackathon_impact_report.md`
- `.runtime/evaluation/notebook_run/config.json`
- `.runtime/evaluation/notebook_run/layer2_metrics_summary.json`
- `.runtime/evaluation/notebook_run/layer2_metrics_by_query.csv`
- `.runtime/evaluation/notebook_run/layer2_raw_results.json`

Interpretation caveats:

> ⚠️ Evaluation labels are AI-assisted, not fully human-audited. NDCG and recall metrics reflect AI-label quality, not human oracle quality.

- The current relevance labels are AI-assisted conservative relevance judgments (2,119 query-item pairs labeled using LLM with conservative scoring — human audit recommended before claiming as full ground truth). They are sufficient for local evaluation gates, but a human audit is recommended before publication-grade claims.
- The live dataset is cold-dominant (`warm_items = 0` in the latest run), so cold-start metrics are framed as **exposure quality**, not cold-vs-warm lift.
- `Hybrid beats title-only baseline` currently remains `needs_more_evidence` because paired Recall@10 evidence is directional-only in the latest run (`null_metric_pair_count = 7`), even though the raw metric deltas are positive.
- `Cold-start window was measured` remains `needs_more_evidence` until source data includes `indexed_at` and `first_seen_in_top_k_at`.
- Live MongoDB search latency is below the 400ms target in the latest run, but total reported latency is still above 400ms. Treat query processing and embedding/translation caching as demo hardening work.
- Python 3.14 currently runs the project, but `torch/sentence-transformers` emits a stability warning. Python 3.10-3.12 is still the safer demo runtime.

## Technical Notebook Audit Path

The React website is the primary demo. The notebooks remain useful as the technical proof and audit trail:

- `notebooks/01_build_3k_mvp_dataset_from_amazon_reviews.ipynb` audits and builds the MVP dataset.
- `notebooks/02_insert_3k_mvp_to_mongodb.ipynb` estimates and inserts documents into MongoDB in controlled increments.
- `notebooks/03_buyer_search_pipeline_test.ipynb` verifies buyer search health against live MongoDB.
- `notebooks/04_demo_buyer_search.ipynb` runs the end-to-end buyer search demo.
- `notebooks/05_evaluation_retrieval_quality.ipynb` runs the 3-layer evaluation: diagnostics → IR metrics → demo readiness claims.

## Known Limitations (Current)

- End-to-end total latency is not yet below 400ms in the latest verified run (`956.2ms` P95), even though MongoDB search latency is below target (`183.8ms` P95).
- Evaluation labels are AI-assisted conservative judgments and are not fully human-audited ground truth.
- The latest dataset snapshot is fully cold (`warm_items = 0`), so results should be interpreted as cold-start exposure quality rather than cold-vs-warm lift.
- Python 3.14 can run this repo but may emit torch/sentence-transformers stability warnings; Python 3.10-3.12 remains the safer runtime.

## Reproducibility Snapshot

Use this exact command for the latest verified retrieval evaluation path:

```bash
python scripts/run_evaluation.py \
  --queries evaluation/queries/retrieval_queries_seed.json \
  --judgments evaluation/judgments/retrieval_judgments_seed.json \
  --out .runtime/evaluation/notebook_run
```

Primary artifacts to verify:

- `.runtime/evaluation/notebook_run/metrics_summary.md`
- `.runtime/evaluation/notebook_run/hackathon_impact_report.md`
- `.runtime/evaluation/notebook_run/config.json`
- `.runtime/evaluation/notebook_run/layer2_metrics_summary.json`
- `.runtime/evaluation/notebook_run/layer2_metrics_by_query.csv`
- `.runtime/evaluation/notebook_run/layer2_raw_results.json`

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
- `DEMO_CHECKLIST.md` — short browser-first demo rehearsal checklist.
- `RELEASE_NOTES.md` — concise validated release snapshot and residual risks.
- `walkthrough_evaluation.md` — step-by-step evaluation walkthrough and usage guide.
- `TESTING.md` — testing guide.

## License and Contact

- License: no license file is declared in this repository at the time of writing.
- Contact: no maintainer contact is declared in this repository at the time of writing.

