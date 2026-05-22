# PLAN: Cold-Start Window Instrumentation + Live Evaluation / A-B Test

Status: Draft (implementation-ready once open questions are resolved)
Owner: TBD
Last updated: 2026-05-22
Version: v1.0

## 0) Quick Summary

This plan measures the cold-start window in live traffic and validates impact via live evaluation or A/B testing. It includes event contracts, dedup rules, QA checks, sampling, statistical analysis, guardrails, and rollback runbooks.

## 1) Goals and Success Criteria

### Goal A: Measure the cold-start window in live traffic
We need reliable timestamps to answer:
- How long from item creation to being indexed?
- How long from indexing to first appearance in top-K results?
- How long from first appearance to first click / purchase?

Success criteria:
- >= 95% of new items have indexed_at within 24h of created_at
- >= 90% of new items have first_seen_in_top_k_at within 72h of indexed_at
- Time-to-first-click and time-to-first-purchase are measurable (non-null) for >= 70% of items with impressions

### Goal B: Validate impact with live evaluation or A/B test
Success criteria (example):
- CTR@10 improves by >= +2% relative (p < 0.05)
- Conversion rate improves by >= +1% relative (p < 0.05)
- Time-to-first-relevant (TTFR) improves by >= 5% (p < 0.05)
- Guardrails: P95 latency not worse by > 10%, zero-results rate not worse by > 0.5%

## 2) Scope, Non-goals, Assumptions

### Scope
- Instrumentation in catalog/indexer, search API, client tracking
- Data pipeline to store events and compute metrics
- Live evaluation + A/B testing for cold-start exposure and search quality

### Non-goals
- No model or ranking changes
- No production ranking logic changes
- No UI/UX changes beyond logging

### Assumptions
- Server-side logging is allowed
- Data warehouse or event storage exists
- Experiment flagging is available

## 3) Definitions and Conventions

### Cold item definition
- Default: is_cold_item = true if interaction_count < N or age_days < M
- N and M are configurable (see Open Questions)

### TTFR (time-to-first-relevant)
- Default relevance proxy: click + dwell_time >= 10s or add-to-cart
- If judgments exist, TTFR uses relevance >= 2

### Identifiers
- request_id: unique per search request
- session_id: stable within a session
- user_id_hash: one-way hash (no raw ID)
- event_id: unique per event (UUID)

## 4) Instrumentation Plan and Data Contract

### 4.1 Principles
- Server-side logging is mandatory to avoid data loss
- Client logs measure impressions/clicks/conversions
- event_version + schema_version for compatibility
- Dedup by event_id + request_id + item_id

### 4.2 Item lifecycle events (catalog + indexer)

Events:
- item_created
- item_indexed
- item_updated (optional)

Minimum schema:
- event_id (string, UUID)
- event_version (int, default 1)
- emitted_at (timestamp, UTC)
- item_id (string)
- created_at (timestamp)
- indexed_at (timestamp, only for item_indexed)
- seller_id_hash (string)
- category_id (string)
- price_bucket (string)
- is_cold_item (bool)
- ingestion_source (string)

### 4.3 Search results logging (server-side)

Event: search_results
Minimum schema:
- event_id
- event_version
- emitted_at
- request_id
- session_id
- user_id_hash
- query_text (optional, may be hashed or dropped by policy)
- query_id (if mapped to evaluation queries)
- language
- top_k
- pipeline_variant (control/treatment)
- latency_ms
- empty_result (bool)
- results[]:
	- item_id
	- rank
	- score
	- is_cold_item
	- channels
	- matched_intent
	- matched_fact

### 4.4 Impression logging (client-side)

Event: search_impression
Minimum schema:
- event_id
- emitted_at
- request_id
- session_id
- user_id_hash
- item_id
- rank
- viewport_percent (0-100)

### 4.5 Click logging (client-side)

Event: search_click
Minimum schema:
- event_id
- emitted_at
- request_id
- session_id
- user_id_hash
- item_id
- rank
- dwell_time_ms (if available)

### 4.6 Conversion logging

Event: search_purchase
Minimum schema:
- event_id
- emitted_at
- request_id
- session_id
- user_id_hash
- item_id
- order_id
- revenue

## 5) Data Model and Storage

### Table: item_lifecycle
- item_id (PK)
- created_at
- indexed_at
- seller_id_hash
- category_id
- price_bucket
- is_cold_item
- ingestion_source

### Table: search_results
- request_id (PK)
- user_id_hash
- session_id
- query_text (nullable)
- query_id
- language
- timestamp
- top_k
- pipeline_variant
- latency_ms
- empty_result
- results (array)

### Tables: search_impressions, search_clicks, search_purchases
- request_id
- item_id
- user_id_hash
- session_id
- timestamp
- rank
- dwell_time_ms (click)
- order_id, revenue (purchase)

Partitioning:
- Partition by date
- Index by request_id, item_id, user_id_hash

Retention:
- Raw events: 90 days
- Aggregates: 12 months

## 6) Metric Computation

### Cold-start window (per item)
- time_to_indexed = indexed_at - created_at
- time_to_first_seen_top_k = min(search_results.timestamp) - indexed_at
- time_to_first_impression = min(search_impressions.timestamp) - first_seen_in_top_k_at
- time_to_first_click = min(search_clicks.timestamp) - first_seen_in_top_k_at
- time_to_first_purchase = min(search_purchases.timestamp) - first_seen_in_top_k_at

### Exposure and relevance proxies
- cold_exposure_rate@K = impressions_of_cold_items / total_impressions
- cold_ctr@K = clicks_on_cold_items / impressions_of_cold_items
- cold_conversion@K = purchases_of_cold_items / impressions_of_cold_items

### Live evaluation metrics
- CTR@K, Conversion@K, TTFR, zero-results rate, P50/P95 latency

## 7) Data Quality, Monitoring, Backfill

### Required checks
- completeness: % events with request_id, item_id
- freshness: ingest lag < 15 minutes
- null rate: indexed_at, first_seen_in_top_k_at
- outliers: time_to_indexed > 7 days

### Monitoring
- Daily dashboard for cold-start window
- Alerts if null rate > 10% or latency spike > 20%

### Backfill
- Missing indexed_at: backfill from indexer logs
- Missing impressions: fallback from search_results (rank <= 10)

## 8) Live Evaluation Plan

### Setup
- Use live MongoDB
- Disable cached fixtures
- Enable search_results logging

### Sampling
- 200-500 queries from real traffic
- Coverage across slices: VN, EN, price_filter, compatibility

### Acceptance checks
- Failure count = 0
- Latency sample count >= 50
- Coverage log >= 90%

## 9) A/B Test Plan

### Experiment design
- Unit: user_id_hash (or session_id if anonymous)
- Randomization: 50/50 control vs treatment
- Duration: 1-2 weeks or until required sample size

### Sample size (approx)
- n/arm ~ 2 * (Z_alpha/2 + Z_beta)^2 * p * (1-p) / delta^2
- Example baseline CTR = 0.08, delta = 0.002, alpha=0.05, power=0.8
- n/arm approx 120k sessions

### Primary KPIs
- CTR@10
- Conversion@10
- TTFR

### Secondary KPIs
- Zero-results rate
- Average rank of clicked item
- Revenue per search

### Guardrails
- P95 latency <= +10%
- Error rate <= baseline +0.2%
- Zero-results rate <= baseline +0.5%

### Analysis
- CTR/Conversion: two-proportion z-test or bootstrap
- TTFR: Mann-Whitney U or bootstrap
- Report effect size + confidence interval
- Control multiple comparisons with Benjamini-Hochberg

### Decision rules
- Ship if all primary KPIs improve and no guardrail regression
- Roll back if guardrails exceed thresholds or effect size is negative

## 10) Rollout and Runbook

### Rollout
- 10% -> 50% -> 100% (24-48h per step)
- Stop if P95 latency increases > 10% or CTR drops > 1%

### Runbook
- Missing logs: verify event pipeline, schema version, dedup rules
- CTR drop: inspect slice breakdown and cold exposure rate
- Conversion drop: check attribution window and sessionization

## 11) Risks and Mitigations

- Missing timestamps -> add server-side logging
- PII concerns -> hash user_id, restrict query_text logging
- Sparse conversions -> extend test duration or target high-traffic segments
- Data drift -> monitor by category and price bucket

## 12) Implementation Checklist

Instrumentation:
- [ ] Add item_indexed event in indexer
- [ ] Add search_results logging in API
- [ ] Add impression/click/purchase events
- [ ] Verify schema and dedup rules in data warehouse

Live evaluation:
- [ ] Run live evaluation with fresh fixtures
- [ ] Export metrics_summary + latency

A/B test:
- [ ] Set up experiment flagging
- [ ] Validate exposure split
- [ ] Run test and analyze results

## 13) Proposed Timeline

- Week 1: Server-side + client-side instrumentation
- Week 2: Data pipeline + QA checks
- Week 3: Live evaluation (200-500 queries)
- Week 4-5: A/B test + analysis

## 14) Open Questions

- What is the official cold item definition (time since creation vs interaction count)?
- What is the privacy policy for logging query_text?
- What is the purchase attribution window (24h, 7d)?
- Do we need multi-region support (timezone, locale)?
