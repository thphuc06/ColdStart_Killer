# ColdStart Killer - Recommendation Enhancement Plan After Audit

**Version:** v1.0  
**Date:** 2026-05-25  
**Status:** Bundles A-C complete; Bundle D freshness safety and CF evidence tooling implemented. Runtime CF remains `current_supported`; qualified-CF promotion remains open.
**Purpose:** Turn verified audit findings into a phased plan for correcting personalization, explanations, implicit feedback handling, collaborative filtering, and operational freshness.

## Status Update - 2026-05-25 Bundles A-D Safety And Evidence Tooling Implemented

Bundle A explanation/profile hygiene and Bundle B correctness changes have been implemented. After tests and the read-only CF comparison passed their safety checks, an explicitly approved controlled rebuild applied the v4 signal/profile lineage while retaining the current CF runtime policy. Bundle C made displayed reasons and badges contribution-faithful without changing ranking weights or CF runtime. Bundle D now adds safe incremental pending processing, truthful CF freshness status, and a runtime-parity offline CF gate. Qualified CF is not promoted because evidence remains insufficient.

The current code gate covers:

- Net-negative signals cannot enter positive profile learning.
- Exact hidden/disliked items are suppressed on home, similar products, and personalized search without fallback restoration.
- Broad-search CF expansion accepts only `seed_eligible` sources.
- CF runtime is unchanged; the read-only evaluator compares current CF with `profile_plus_qualified_cf` under `min_support=2`.
- Bundle C selects primary reasons and badges from material weighted contributions, records structured attribution and diversity/cold-insertion causes, and makes the UI consume backend badge truth.
- Explanation semantics are versioned as `explain_v3_contribution_faithful` with `REASON_MIN_CONTRIBUTION=0.05`; this does not require a signals/profile/CF rebuild.
- Bundle D adds `POST /api/debug/apply-pending-behavior` and `scripts/process_pending_behavior.py` to recompute complete affected signals/item stats/profiles idempotently while leaving CF for scheduled refresh.
- Full signals writes now reject every event limit and use an event watermark; debug freshness reports component state and `cf.refresh_required` rather than silently treating lagging CF as current.
- CF edge computation is shared by runtime and evaluation, with `CF_RUNTIME_INPUT_POLICY=current_supported`; `qualified_deliberate` remains dry-run/evaluation-only until approved.

Approved v4 controlled rebuild evidence:

- Shared intent hygiene now rejects UUID-like, fact-like, and generic labels during signal/profile derivation.
- Signal rebuild wrote `1157` documents as `signal_v4_boundary_hygiene`; profile rebuild wrote `43` documents as `profile_v4_negative_guard`.
- Current-policy CF rebuild retained `514` directional edges as `cf_v1_supported_edges`, each sourced from `signal_v4_boundary_hygiene`.
- Post-rebuild baseline report for `phuc_demo` / `u_api_5ea7eb5ac87d4abe` returned `freshness.state = current`, `pending_event_count = 0`, `uuid_label_count = 0`, `fact_label_count = 0`, `generic_label_count = 0`, and `profile_explanation_audit_failures = 0`.
- Post-rebuild profile state remained clean with labels `cell phones and accessories` and `sensitive skin person looking for natural soap`.
- Post-Bundle-C read-only baseline returned `primary_reason_attribution_failure_count = 0` across the sampled top `10` cards, with no profile explanation audit failures.

Reproducibility and data-state caveats:

- Stored Mongo signals/profiles/CF are now aligned to the v4 signal lineage and current CF runtime policy.
- Local output under `.runtime/evaluation/` is ignored and reproducible evidence only, not a committed or shared source of truth.
- Reproduce the CF comparison without Mongo writes using `python scripts/run_personalization_evaluation.py --dry-run --write-artifacts --out .runtime/evaluation/bundle_b_cf_gate_<timestamp> --print-json-summary`.
- Reproduce the contribution-faithfulness baseline without Mongo writes using `python scripts/report_personalization_baseline.py --user-id u_api_5ea7eb5ac87d4abe --top-k 10`.
- Preview pending incremental processing without Mongo writes using `python scripts/process_pending_behavior.py --dry-run --max-events 100`.
- Synthetic/demo evaluation results must not be presented as human-judged ground truth.

Read-only CF gate run on 2026-05-25 (`bundle_b_cf_gate_20260525_2124`):

| Variant | HitRate@10 | Recall@20 | MAP@20 | Deliberate Recall@20 | CF-supported count | Train directional edges |
|---|---:|---:|---:|---:|---:|---:|
| `profile_plus_cf` | 0.166667 | 0.086508 | 0.019393 | 0.058824 | 466 | 278 |
| `profile_plus_qualified_cf` | 0.119048 | 0.078571 | 0.010767 | 0.176471 | 0 | 0 |

Gate outcome: `needs_more_evidence`. Qualified CF generated no supported recommendation or edge under `min_support=2`; the subsequent approved rebuild retained the current CF runtime policy rather than adopting qualified CF.

Bundle D read-only parity rerun on 2026-05-25: runtime-parity `profile_plus_cf` reported `HitRate@10=0.166667`, `Recall@20=0.069841`, `MAP@20=0.023210`, `NDCG@20=0.047865` with `268` train directional edges and negative re-exposure `0`; `profile_plus_qualified_cf` still produced `0` edges. This metric shift reflects corrected evaluator parity, not a Mongo CF rebuild.

---

## 0. Executive Decision

ColdStart Killer already has a valid high-level architecture:

```text
UI interaction
  -> clickstream_events
  -> user_item_signals
  -> user_profiles
  -> recommendation candidates + scoring
  -> explanations + recommendation_logs

user_item_signals
  -> item_item_cf_edges
  -> CF candidates in feed/similar/search reranking
```

The system should not be redesigned from scratch. It should be enhanced in this order:

1. Correct explanation/profile contamination and stale derived data.
2. Stop exposure-only events from becoming semantic or CF seed behavior.
3. Make deliberate intent such as cart, purchase, meaningful dwell, and repeated action actually dominate profile personalization.
4. Make explanations describe the contribution that influenced ranking.
5. Preserve true multi-user CF semantics while calibrating coverage for demo and precision for production.
6. Replace manual, ambiguous refresh behavior with versioned and observable derivation.

The immediate outcome should be **more correct and more defensible recommendations**, not a feed manually optimized to show only one category for one demo user.

---

## 1. Audit Baseline

### 1.1 Evidence Sources

This plan is based on:

- Source inspection of the current working tree.
- Read-only MongoDB inspection on 2026-05-25.
- Focused unit test execution: `30 passed`.
- The practical account case where UI label `phuc_demo` maps to internal key `u_api_5ea7eb5ac87d4abe`.

Important context:

- The working tree already contains partial corrective edits for profile labels and category-aware interest selection.
- Stored MongoDB derived documents still reflect earlier contaminated derivation.
- Historical recommendation logs should remain historical evidence; derived profiles/signals should be versioned and rebuilt after approved fixes.

### 1.2 Verified Current Flow

| Stage | Current implementation |
|---|---|
| UI events | `frontend/src/lib/tracking.ts`, `frontend/src/lib/useImpressionLogger.ts`, recommendation pages/cards |
| Event API | `src/api/routes_events.py` -> `src/behavior/event_logger.py` |
| Signal processing | `src/behavior/signal_builder.py` via `/api/debug/process-events` |
| Profile building | `src/behavior/profile_builder.py` via `/api/debug/rebuild-profiles` |
| Candidate creation | `src/recommendation/candidate_sources.py` |
| Scoring | `src/recommendation/scoring.py` |
| Home feed | `src/recommendation/homepage_feed.py` |
| Search reranking | `src/recommendation/search_personalizer.py` |
| Similar products | `src/recommendation/similar_products.py` |
| Explanations | `src/recommendation/explanations.py`, `src/retrieval_output.py` |
| CF build | `src/recommendation/item_item_cf.py` via `/api/debug/rebuild-cf` |
| Debug/control UI | `frontend/src/pages/DebugPage.tsx`, `src/api/routes_debug.py` |

### 1.3 Verified Current Signal Rules

| Rule | Current value |
|---|---:|
| `impression` positive weight | `0` |
| `click` positive weight | `1.0` |
| `view_detail` base weight | `1.0` |
| `view_detail` dwell bonus | `min(dwell_ms / 60000, 1.0)` |
| `wishlist` positive weight | `2.0` |
| `add_to_cart` positive weight | `3.0` |
| `purchase` positive weight | `5.0` |
| `hide` negative weight | `2.0` |
| `dislike` negative weight | `3.0` |
| `positive_score` | Sum of positive event weights |
| `negative_score` | Sum of negative event weights |
| `implicit_score` | `positive_score - negative_score` |
| `preference` | `implicit_score > 0 and positive_score >= 1.0` |
| Profile-positive threshold | `max(implicit_score, 0) >= 1.0` |
| CF-positive threshold | `implicit_score > 1.0` or `preference=True` |

### 1.4 Verified Current Profile and CF Rules

| Rule | Current value |
|---|---:|
| Interest merge cosine threshold | `0.72` |
| Maximum interests per user | `8` |
| Negative brand/category promotion threshold | `2` negative item evidences |
| Profile long-term half-life in event update | `30` days |
| CF minimum multi-user support | `2` |
| CF maximum positive items per user | `30` |
| CF maximum neighbors per item | `50` |
| CF half-life | `45` days |

### 1.5 Verified `phuc_demo` Runtime Evidence

The account presented as `phuc_demo` in the UI is stored as:

```text
user_id_hash = u_api_5ea7eb5ac87d4abe
```

Read-only observations:

| Evidence | Observed value |
|---|---:|
| Clickstream events | `283` |
| Impressions | `272` |
| Clicks | `5` |
| View details | `5` |
| Add to cart | `1` |
| Purchases / negative actions | `0` |
| Stored signal documents | `121` |
| Positive signal items | `5` |
| Impression-only signal documents | `116` |
| Profile status | `warm` |
| Profile confidence | `1.0` |
| Global CF directional edges | `514` |
| CF edges from this user's five positive items | `0` |

Observed positive intent mix:

| Category | Evidence |
|---|---|
| Beauty / soap | Two positive items; one has click + detail + cart and `positive_score=5.403983` |
| Smartphones | Three positive items from click + short detail views, with scores around `2.05-2.24` |

Observed correctness failures:

- Stored profile contains a smartphone interest label copied from a product fact about an AMOLED display.
- Stored profile contains multiple UUID-like values in `intent_affinity` and `top_intents`.
- Five logged home beauty recommendations displayed the smartphone AMOLED interest as their explanation.
- The newest home data after the in-progress code correction uses a beauty/soap label for beauty cards, but contaminated profile state still exists.
- Four of the first five homepage semantic/CF seed item IDs are impression-only smartphone items.
- Forty events for this account were newer than the last materialized signal/profile build at audit time.

### 1.6 Issue Classification

| Issue | Classification | Priority |
|---|---|---:|
| Product fact / UUID contamination in stored interest labels | Correctness bug plus stale derived data | Must fix |
| Cross-category explanation using contaminated profile label | Correctness bug | Must fix |
| Impression-only items used as home semantic/CF seeds | Personalization logic bug | Must fix |
| Newest event per item underrepresents cart/dwell/repeat intent in profile vector | Modeling bug | Must fix |
| Explanation reflects raw evidence rather than weighted rank contribution | Explainability bug | Must fix |
| One click or short detail view becomes preference/CF-positive | Calibration trade-off for demo; production risk | Should fix before production |
| CF has no edges for `phuc_demo` positive items due to support `< 2` | Correct behavior, not a bug | Preserve semantics |
| Manual/partial rebuild may serve stale or incomplete derived state | Operational correctness bug | Must fix before production |

---

## 2. Product and Engineering Principles

### 2.1 Principles

1. An impression is exposure evidence, not preference evidence.
2. A quick click is weaker than deliberate behavior such as cart or purchase.
3. A profile may correctly contain multiple categories; it must not confuse their explanations.
4. Reasons shown to users must describe actual ranking contribution, not merely an available raw match.
5. Collaborative filtering must remain multi-user collaborative evidence.
6. Derived collections must advertise freshness and derivation version.
7. Demo tuning must not quietly redefine production semantics.

### 2.2 Non-Goals

The following are explicitly not goals of this enhancement program:

- Removing smartphone recommendations merely because the demo user originally expressed beauty intent.
- Lowering CF support to `1` while continuing to call the result collaborative filtering.
- Optimizing only for `phuc_demo` at the cost of general behavior quality.
- Replacing the existing HyPE/BM25 retrieval core without evidence that retrieval itself is defective.
- Generating persuasive explanations for sources that did not materially affect ranking.

---

## 3. Target State

### 3.1 Target Behavior Pipeline

```text
clickstream_events
  -> versioned signal aggregation
       exposure signals: impressions
       exploratory signals: weak click / short detail
       engaged signals: meaningful dwell / wishlist / repeated behavior
       conversion signals: cart / purchase
       negative signals: hide / dislike
  -> versioned user_profiles
       deliberate positive seed items only
       clean category-aware interests
       recency-aware weighted embeddings
       explicit negative suppression state
  -> candidate generation
       profile candidates
       semantic neighbors from deliberate seeds
       true CF neighbors from supported seeds
       quality/exploration candidates
  -> scoring with per-channel contribution
  -> contribution-faithful explanation and badges
  -> recommendation_logs with derivation/ranking versions
```

### 3.2 Target Data Guarantees

| Guarantee | Required behavior |
|---|---|
| Clean interest labels | Labels cannot be raw product facts, retrieval-unit UUIDs, or long arbitrary query text |
| Seed integrity | Impression-only and negative-only items do not seed personalized neighbors |
| Intent strength | Cart/purchase/repeated meaningful engagement dominates isolated click exploration |
| Explanation fidelity | Displayed primary reason corresponds to a material positive score contribution |
| CF honesty | CF reason appears only when a retained multi-user edge contributes |
| Freshness visibility | UI/debug output can show signal/profile/CF derivation version and last processed watermark |

---

## 4. Phase Overview

| Phase | Name | Priority | Main outcome | Depends on |
|---|---|---:|---|---|
| 0 | Baseline and Versioning Contract | Must | Reproducible baseline and derived-data contract | None |
| 1 | Explanation and Profile Hygiene | Must | No contaminated interests or cross-category explanations | Phase 0 |
| 2 | Intent-Strength Personalization | Must | Deliberate behavior governs profile and seeds | Phase 1 |
| 3 | Contribution-Faithful Ranking and Reasons | Must | Badges/reasons explain actual rank influence | Phase 2 |
| 4 | CF and Negative Feedback Integrity | Must/Should | Honest CF, stronger suppression, calibrated support | Phase 2 |
| 5 | Freshness and Incremental Processing | Must before production | No ambiguous stale/partial derived state | Phases 1-4 |
| 6 | Evaluation, Rollout, and Production Gate | Must before production | Evidence-based release decision | All earlier phases |

Recommended delivery order:

```text
Phase 0 -> Phase 1 -> approved rebuild -> Phase 2 -> Phase 3
                                      \-> Phase 4
                         Phase 5 -> Phase 6
```

---

## 5. Phase 0 - Baseline and Versioning Contract

### 5.1 Goal

Establish a reproducible baseline and a contract for identifying which code version generated derived documents.

### 5.2 Why This Phase Exists

At audit time, current code and current MongoDB derived state did not describe the same behavior. Without versioning, it is impossible to distinguish:

- a currently executing logic bug;
- a fixed bug whose stale output is still stored;
- a recommendation log generated before or after a behavior-model change.

### 5.3 Implementation Scope

Modules to change:

| Module | Change |
|---|---|
| `src/behavior/schemas.py` | Add derived metadata fields to signal/profile contracts |
| `src/recommendation/schemas.py` | Add derivation metadata to CF edge contract if not already available |
| `src/config.py` | Add configurable `signal_model_version`, `profile_model_version`, `cf_model_version`, `explanation_version` |
| `src/behavior/signal_builder.py` | Write model version and input watermark into generated signal docs |
| `src/behavior/profile_builder.py` | Write source signal version and profile model version |
| `src/recommendation/item_item_cf.py` | Write source signal version and CF model version |
| `src/api/routes_debug.py` | Expose freshness/version metadata read-only in debug response |

Recommended fields:

```json
{
  "derivation": {
    "model_version": "signal_v2_intent_hierarchy",
    "source_collection": "clickstream_events",
    "source_event_max_timestamp": "ISO_TIMESTAMP",
    "source_event_count": 0,
    "built_at": "ISO_TIMESTAMP"
  }
}
```

Profile and CF documents should additionally store their upstream input version:

```json
{
  "derivation": {
    "model_version": "profile_v2_clean_weighted",
    "source_signal_model_version": "signal_v2_intent_hierarchy"
  }
}
```

### 5.4 Baseline Artifacts

Create repeatable read-only audit scripts or test fixtures that capture:

- Event distribution per user and category.
- Positive/negative item summary.
- Profile interest labels, categories, and evidence.
- Recommendation logs with explanation/category mismatches.
- CF coverage for positive items.
- Freshness gaps between newest event, signals, profiles, logs, and CF.

Required regression fixture:

```text
phuc_demo / u_api_5ea7eb5ac87d4abe
  beauty item with cart
  beauty semantic neighbor
  smartphone click + short detail items
  contaminated old explanation case
  no supported CF edge for personal positive items
```

### 5.5 Tests

| Test type | Required test |
|---|---|
| Unit | Derived documents serialize model/version fields correctly |
| Integration | Debug endpoint exposes model version and freshness watermark |
| Regression | Baseline fixture records legacy contamination before rebuild |
| Guardrail | Read-only audit routines cannot write collections |

### 5.6 Acceptance Gate

Phase 0 is complete when:

- Every new derived document can state which model version built it.
- A report can identify stale stored profiles without inferring from timestamps alone.
- `phuc_demo` baseline is reproducible as a test fixture or scripted read-only report.

---

## 6. Phase 1 - Explanation and Profile Hygiene

### 6.1 Goal

Prevent invalid interest labels and eliminate cross-category explanation contamination in newly derived data.

### 6.2 Verified Problem

Stored data currently includes:

- A smartphone product fact as an interest label.
- UUID-like strings as interest intentions.
- Beauty recommendation explanations referencing that smartphone fact.

The current working tree already contains partial correction:

- `matched_facts`, matched unit IDs, and fallback explanation are no longer promoted as signal intents.
- Profile intent extraction reads `matched_intents` only.
- Candidate profile matching prefers interests sharing the item category.

This phase formalizes, validates, and safely deploys that correction.

### 6.3 Required Changes

#### Signal hygiene

In `src/behavior/signal_builder.py`:

- Only behavioral intent labels derived from approved `matched_intents` may populate `reason_scores`.
- Facts, unit IDs, free-form explanations, and candidate source names must never become profile intentions.
- Add validation counters for dropped malformed intent strings.

#### Profile label hygiene

In `src/behavior/profile_builder.py`:

- Add a reusable `is_valid_interest_label()` or normalization helper.
- Reject UUID-like labels.
- Reject fact-like labels that exceed a configurable length or contain full product specification structure.
- Prefer clean matched intent; otherwise fall back to normalized category display name.
- Keep raw forensic attribution only in debug/provenance fields, never in user-facing labels.

#### Category-aware matching

In `src/recommendation/candidate_sources.py`:

- Keep category-aware interest selection for explanations and profile candidate matching.
- Define fallback behavior explicitly when an item has no matching category interest.
- Do not show a profile explanation when only an unrelated interest has weak raw cosine similarity.

#### Explanation contract

In `src/recommendation/explanations.py`:

- Profile reason text must use only sanitized labels.
- Avoid displaying an empty/generic `interest` label as a personalized claim.

### 6.4 Data Migration and Rebuild

No silent migration should rewrite historical `recommendation_logs`.

After code review approval:

1. Record counts and snapshots of affected stored profiles/logs.
2. Rebuild `user_item_signals` using the new signal model version.
3. Rebuild `user_profiles` using the new profile model version.
4. Rebuild CF only after signals have the approved model version.
5. Generate a post-rebuild audit report.

Expected behavior:

- Historical bad logs remain traceable as generated by the old version.
- Newly served recommendations and newly built profiles contain no fact/UUID contamination.

### 6.5 Tests

| Test | Assertion |
|---|---|
| Product fact rejection | AMOLED fact cannot become interest label or intent |
| Unit ID rejection | UUID-like retrieval unit ID cannot become interest label |
| Category-aware reason | Beauty item selects beauty label even when phone interest has stronger unrelated similarity |
| Fallback label | A BM25-only interacted item uses category fallback rather than product fact |
| Stored legacy fixture rebuild | Recomputed profile has no invalid label after derivation |

### 6.6 Acceptance Gate

- Zero newly generated profile labels match UUID format.
- Zero newly generated profile labels are copied product facts in the regression corpus.
- New `phuc_demo` beauty cards never display the AMOLED smartphone reason.
- Explanation failure is detectable through an automated audit counter.

---

## 7. Phase 2 - Intent-Strength Personalization

### 7.1 Goal

Separate exposure and exploratory navigation from deliberate preference, then make weighted intent drive profiles and personalized candidate seeds.

### 7.2 Verified Problems

- A single click already sets `preference=True`.
- A detail view as short as the UI minimum dwell can qualify an item for profile inclusion.
- Homepage seed IDs are taken from recent events and include impression-only items.
- Profile embedding uses the latest positive event for an item rather than its aggregate deliberate evidence.
- The beauty/cart item for `phuc_demo` has stronger aggregate intent but is underrepresented in event-vector weighting compared with several recent smartphone browsing events.

### 7.3 Target Event Semantics

Introduce a configurable event-intent layer:

| Tier | Example evidence | Purpose |
|---|---|---|
| Exposure | `impression` | Seen/CTR statistics only; never a preference seed |
| Exploratory | isolated `click`, very short `view_detail` | Weak learning signal; limited ranking influence |
| Engaged | meaningful dwell, wishlist, repeated item/category interaction | Profile learning and optional seed eligibility |
| Conversion | cart, purchase | Strong profile and seed evidence |
| Negative | hide, dislike | Suppression and negative learning |

Do not lock final numerical weights based only on one account. Implement configuration and evaluate candidate parameter sets.

### 7.4 Proposed Calibration Candidates

Use the existing behavior as control and test at least two alternatives:

| Signal | Current control | Candidate A | Candidate B |
|---|---:|---:|---:|
| Single click | `1.0` | `0.35` | `0.50` |
| Detail `< 5s` | `>=1.0` | `0.10` | `0.20` |
| Detail `5-20s` | continuous base `1.0+` | `0.50` | `0.75` |
| Detail `>=20s` | continuous base `1.0+` | `1.25` | `1.50` |
| Wishlist | `2.0` | `2.5` | `2.0` |
| Add to cart | `3.0` | `4.0` | `4.0` |
| Purchase | `5.0` | `7.0` | `8.0` |
| Repeated positive session/item | implicit repetition only | configurable bonus | configurable bonus |

These values are experiment inputs, not production defaults until evaluated.

### 7.5 Required Changes

#### Signal model

In `src/behavior/signal_builder.py`:

- Create explicit configured scoring functions for dwell tiers and repeated interaction.
- Store contribution detail by event tier, not only total score.
- Define a deliberate-intent eligibility flag distinct from generic positive score.

Candidate signal fields:

```json
{
  "positive_score": 0.0,
  "negative_score": 0.0,
  "implicit_score": 0.0,
  "preference": false,
  "seed_eligible": false,
  "intent_tier": "exposure|exploratory|engaged|conversion|negative",
  "contributions": {
    "exploratory": 0.0,
    "engaged": 0.0,
    "conversion": 0.0
  }
}
```

#### Profile vector construction

In `src/behavior/profile_builder.py`:

- Stop selecting exactly one newest positive event as the vector weight source.
- Aggregate relevant positive events or aggregate signal contribution for each item.
- Apply recency to each meaningful contribution.
- Ensure cart/purchase contribution dominates isolated click/detail exploration.
- Retain multi-interest behavior: beauty and smartphone can both remain valid interests.

#### Homepage source selection

In `src/recommendation/homepage_feed.py`:

- Replace generic `recent_item_ids` source selection with `seed_eligible` positive signals ordered by deliberate contribution and recency.
- Do not use impression-only or negative-only items as semantic/CF source IDs.
- Maintain separate exposure history for seen penalty and diversity logic.

### 7.6 Tests

| Test | Required assertion |
|---|---|
| Impression-only source | Impression does not become semantic or CF homepage seed |
| Negative source | Hidden/disliked item cannot seed neighbors |
| Short detail | Minimum dwell alone does not create a strong profile seed under candidate config |
| Cart dominance | A cart beauty item contributes more profile weight than multiple isolated phone clicks |
| Multi-interest retention | Genuine beauty and phone engaged intents remain separate interests |
| Recency behavior | A stale low-intent item does not dominate newer deliberate intent |

### 7.7 Acceptance Gate

- In regression replay, `phuc_demo` retains valid phone interest but beauty/cart is not displaced by impression-only phone seeds.
- Impressions are absent from semantic/CF seed input.
- Conversion and engaged signals measurably influence profile score more than isolated click exploration.
- Offline relevance and coverage do not regress beyond the Phase 6 thresholds.

---

## 8. Phase 3 - Contribution-Faithful Ranking and Reasons

### 8.1 Goal

Make the visible reason and badge answer: "What materially caused this item to rank here?"

### 8.2 Verified Problems

- The explanation builder emits available raw evidence in fixed order.
- A semantic explanation can be displayed first even when weighted profile contribution is larger.
- Profile badges can appear when transformed cosine contributes despite weak or negative raw similarity.
- Cold-start text may mention HyPE/vector and BM25 even when the candidate came from quality or exploration only.

### 8.3 Target Scoring Contract

Every scored candidate should expose signed, weighted contribution:

```json
{
  "scores": {
    "profile_score": 0.0,
    "semantic_neighbor_score": 0.0,
    "item_item_cf_score": 0.0,
    "metadata_score": 0.0,
    "cold_start_boost": 0.0,
    "quality_score": 0.0,
    "seen_penalty": 0.0,
    "negative_penalty": 0.0,
    "final_score": 0.0
  },
  "contributions": {
    "profile": 0.0,
    "semantic_neighbor": 0.0,
    "cf": 0.0,
    "metadata": 0.0,
    "cold_explore": 0.0,
    "quality": 0.0,
    "seen_penalty": -0.0,
    "negative_penalty": -0.0,
    "diversity_adjustment": -0.0
  }
}
```

### 8.4 Required Changes

#### Score computation

In `src/recommendation/scoring.py`:

- Return explicit weighted channel contributions.
- Introduce a calibrated minimum profile similarity threshold.
- Do not translate weak negative profile cosine into a personalized positive claim.
- Define when normalized semantic/CF scores have no eligible evidence and must remain zero.

#### Diversity visibility

In `src/recommendation/diversity.py`:

- Record diversity adjustment and forced cold-start insertion as attribution state.
- Ensure a forcibly inserted cold candidate is not described as primarily profile-driven unless profile contribution is material.

#### Explanation selection

In `src/recommendation/explanations.py`:

- Sort eligible explanation candidates by positive weighted contribution.
- Show a profile explanation only when profile contribution exceeds threshold.
- Show CF explanation only when CF contribution is positive and support is present.
- Show exploration/cold-start text corresponding to actual source/contribution.
- Keep raw matches in debug expansion, not as the primary reason by default.

#### Frontend badges

In `frontend/src/components/ProductCard.tsx`:

- Use backend-provided contribution-aware badge contract.
- Avoid reconstructing semantic truth independently from raw fields.
- Display debug/raw evidence separately from primary shopper-facing reason.

### 8.5 Suggested Explanation Policy

| Contribution state | Primary reason |
|---|---|
| Profile is largest material contributor | `Because it matches your gentle skincare interest.` |
| CF is largest material contributor | `People with similar interactions also engaged with this item.` plus support |
| Semantic source is largest | `Similar to an item you engaged with: ...` |
| Exploration/cold insertion is primary | `Included to explore a newer item outside your usual picks.` |
| Query-first search dominates | `Matched your search for ...` |
| No material personalized source | Generic non-personalized ranking reason, no profile badge |

### 8.6 Tests

| Test | Required assertion |
|---|---|
| Primary reason selection | Largest weighted positive contribution produces primary explanation |
| Weak profile similarity | No profile badge/reason below configured threshold |
| CF badge | No CF badge without positive scored CF contribution |
| Cold-start accuracy | Cold reason does not claim unavailable BM25/vector evidence |
| Diversity insertion | Forced cold exposure reason is honest and logged |
| Frontend rendering | UI displays backend badge/reason contract consistently |

### 8.7 Acceptance Gate

- Explanation faithfulness metric reaches target in Phase 6.
- Manual review of the `phuc_demo` fixture produces no contradictory category reasons.
- Badges never claim a channel with zero or below-threshold contribution.

---

## 9. Phase 4 - CF and Negative Feedback Integrity

### 9.1 Goal

Preserve truthful multi-user collaborative filtering, improve its input quality, and enforce user-level suppression consistently.

### 9.2 Verified CF Assessment

The current CF builder is structurally correct:

- It builds item-item pairs from positive signals across users.
- It retains a pair only when support reaches the configured multi-user threshold.
- It applies recency and item popularity normalization.
- It stores symmetric directional edges.

The lack of CF output for `phuc_demo` is expected:

- The user's five positive items each have positive support from that user only.
- Every pair among those five items has observed support `1`.
- Current `min_support=2` correctly excludes them.

### 9.3 Required Changes

#### CF input eligibility

In `src/recommendation/item_item_cf.py`:

- Consume only `seed_eligible` or an explicit CF-qualified positive signal once Phase 2 exists.
- Exclude items subsequently hidden/disliked by the same user from that user's co-occurrence evidence.
- Consider separate thresholds for conversion-bearing pairs versus click-only pairs.

#### Suppression paths

In `src/recommendation/candidate_sources.py`, `homepage_feed.py`, and `similar_products.py`:

- Negative items must be excluded as recommendations.
- Negative items must not act as semantic/CF sources.
- Repeated category/brand negatives may suppress related candidates with configurable severity.
- Search should preferably demote rather than hard-filter related categories unless the user gave explicit exclusion feedback.

#### Demo versus production CF policy

| Environment | Recommended policy |
|---|---|
| Demo | Keep `min_support=2`; show a clear no-CF-evidence state for unsupported personal seeds; seeded global CF may be disclosed as demo evidence |
| Production experiment | Calibrate support threshold and event-strength requirements using holdout metrics |
| Production default | Never call support-1 single-user co-occurrence "Collaborative Filtering" |

Optional alternative for demo:

- Implement a separately named `session_co_engagement` or `personal_sequence_neighbor` source.
- Never label it as CF and never combine its support reporting with multi-user CF.

### 9.4 Tests

| Test | Required assertion |
|---|---|
| Support-one exclusion | A one-user pair never creates CF edge under CF model |
| Strong supported CF | Multi-user cart/purchase pair generates stronger retained edge than click-only pair |
| Negative exclusion | A disliked item does not contribute as source or recommendation for that user |
| Environment config | Demo and production configuration labels are explicit |
| Explanation integrity | Unsupported source never renders CF reason |

### 9.5 Acceptance Gate

- No false CF claim appears for `phuc_demo` unless new multi-user support exists.
- CF coverage and precision are both reported, not traded invisibly.
- Negative feedback prevents immediate re-exposure and neighbor propagation on home/similar.

---

## 10. Phase 5 - Freshness and Incremental Processing

### 10.1 Goal

Ensure recommendations can be interpreted against current behavior without relying on a manual debug-button workflow or unsafe partial recomputation.

### 10.2 Verified Problems

- Events can be written immediately while signals/profile/CF remain stale.
- At audit time, `phuc_demo` had `40` unprocessed events after the most recent signal/profile build.
- The debug endpoint accepts limited write-mode event processing without an explicit sorted incremental contract.
- Recomputing aggregate signals from a partial event set can overwrite complete aggregate state incorrectly.

### 10.3 Required Changes

#### Safe rebuild contract

In `src/behavior/signal_builder.py` and `src/api/routes_debug.py`:

- Disallow `write=True` with arbitrary partial full-recompute input unless the operation is explicitly incremental.
- Keep dry-run limits for inspection.
- For full recomputation, read the complete event set or an explicitly versioned partition.
- Report source event watermark and count.

#### Incremental path

Add a controlled derivation strategy:

```text
new event inserted
  -> enqueue or schedule signal aggregation
  -> update affected user-item signal idempotently
  -> refresh affected user profile
  -> update affected CF contribution asynchronously or by bounded batch
```

Minimum viable production approach:

- Incrementally update signals and profiles for the affected user.
- Rebuild CF on scheduled micro-batches rather than per click.
- Store last processed event watermark and model version.

#### Cache invalidation

In `src/recommendation/candidate_sources.py`:

- Clear or version catalog/profile-dependent caches when relevant derived state changes.
- Ensure debug page identifies cached versus fresh response state where applicable.

### 10.4 Operational Status UI

Extend debug output with:

| Field | Meaning |
|---|---|
| `latest_event_at` | Newest event for selected user |
| `signal_built_at` | Newest signal materialization timestamp |
| `profile_built_at` | Profile materialization timestamp |
| `cf_built_at` | CF graph materialization timestamp |
| `pending_event_count` | Unprocessed events under current signal model |
| `model_versions` | Current stored and configured versions |
| `freshness_state` | `fresh`, `pending`, `stale_version`, or `unknown` |

### 10.5 Tests

| Test | Required assertion |
|---|---|
| Partial write guard | Limited recompute cannot overwrite aggregates in write mode accidentally |
| Idempotent event retry | Reprocessed event does not double-count |
| Freshness state | Pending event yields visible stale/pending status |
| Version mismatch | Old profile is marked stale after model version update |
| CF schedule | Profile can refresh without falsely claiming CF graph already refreshed |

### 10.6 Acceptance Gate

- No supported API path silently performs a partial aggregate overwrite.
- Debug UI can truthfully state when recommendations use stale derived behavior.
- Profile freshness meets the Phase 6 target latency; CF freshness is documented separately.

---

## 11. Phase 6 - Evaluation, Rollout, and Production Gate

### 11.1 Goal

Decide whether enhancements improve recommendations broadly, rather than merely improving the appearance of a single demonstration.

### 11.2 Offline Evaluation Design

Use temporal replay:

```text
train window: earlier events used to build signals/profiles/CF
validation window: later engagement used as target relevance
```

Compare:

| Variant | Description |
|---|---|
| `control_current` | Current weights and current candidate logic |
| `clean_profile_only` | Phase 1 hygiene and rebuilt derived state |
| `intent_hierarchy` | Phase 2 calibrated positive/negative signals |
| `faithful_explanations` | Phase 3 ranking contribution and reasons |
| `qualified_cf` | Phase 4 stronger CF input eligibility |
| `fresh_pipeline` | Phase 5 incremental/freshness behavior |

### 11.3 Required Metrics

#### Ranking metrics

| Metric | Purpose |
|---|---|
| Recall@K of subsequent engaged/conversion items | Retrieve future meaningful interests |
| NDCG@K with event-strength relevance labels | Reward correct order, especially cart/purchase |
| MRR for first deliberate positive action | Measure early useful placement |
| Category intent alignment | Detect drift from stronger category intent |
| Catalog/category diversity | Avoid collapsing feed to one narrow interest |

Suggested relevance grades for evaluation, to be calibrated:

| Future event | Relevance grade |
|---|---:|
| Impression only | `0` |
| Isolated click | `1` |
| Meaningful detail / repeat engagement | `2` |
| Wishlist | `3` |
| Add to cart | `4` |
| Purchase | `5` |
| Hide/dislike | Negative exclusion target |

#### Explanation metrics

| Metric | Purpose |
|---|---|
| Invalid label rate | Count UUID/fact/generic contaminated reasons |
| Cross-category explanation mismatch rate | Catch smartphone-on-beauty type failures |
| Contribution faithfulness rate | Primary reason agrees with largest eligible contribution |
| Unsupported CF claim rate | CF reason requires scored supported edge |

#### Operations metrics

| Metric | Purpose |
|---|---|
| Event-to-profile freshness latency | Personalization responsiveness |
| Event-to-CF freshness latency | Graph update expectation |
| Stale-version document count | Migration completeness |
| Failed/idempotent update rate | Processing stability |

### 11.4 Release Gates

Before demo sign-off:

| Gate | Requirement |
|---|---|
| Reason hygiene | No invalid or cross-category explanation in curated demo walkthrough |
| Seed integrity | No impression-only personalized semantic/CF seed |
| CF honesty | UI does not imply personal CF evidence when none exists |
| Freshness display | Debug view states whether derived state is pending/current |

Before production pilot:

| Gate | Requirement |
|---|---|
| Offline relevance | NDCG/Recall non-inferior to control and improved on deliberate action targets |
| Negative safety | Re-exposure rate after hide/dislike below agreed threshold |
| Explanation faithfulness | Target threshold defined and met on sampled cards |
| Freshness | Profile update SLO and scheduled CF refresh SLO demonstrated |
| Data contract | Versioned derivation and migration/rebuild runbook verified |

### 11.5 Online Experiment Plan

Only after offline acceptance:

| Experiment | Comparison | Primary outcome | Guardrail |
|---|---|---|---|
| Signal hierarchy | Current vs calibrated event weighting | Cart/purchase or meaningful engagement rate | Hide/dislike rate |
| Reason policy | Raw reason order vs contribution reason | Reason expansion/useful-feedback proxy | Ranking unchanged where required |
| CF qualification | Current supported CF vs strong-event-qualified CF | Engaged CTR on CF-supported cards | Coverage floor |
| Freshness | Manual batch vs incremental profile refresh | Personalization response after deliberate action | Processing error rate |

---

## 12. Module-Level Change Map

| Module | Phase | Planned responsibility |
|---|---:|---|
| `src/behavior/schemas.py` | 0, 2 | Derived metadata and new signal/profile fields |
| `src/config.py` | 0, 2, 4 | Model versions, signal calibration, CF policies |
| `src/behavior/signal_builder.py` | 0, 1, 2, 5 | Clean intent extraction, tiered contributions, safe/incremental processing |
| `src/behavior/profile_builder.py` | 0, 1, 2, 5 | Clean labels, aggregate weighted interests, provenance/freshness |
| `src/recommendation/item_item_cf.py` | 0, 4, 5 | Qualified positive inputs, CF version/freshness, scheduled rebuild |
| `src/recommendation/candidate_sources.py` | 1, 3, 4 | Category-aware match, penalties, contribution attribution |
| `src/recommendation/homepage_feed.py` | 2, 3, 4 | Deliberate seed selection, ranked reasons, suppression |
| `src/recommendation/search_personalizer.py` | 3, 4 | Contribution-aware reranking and negative behavior policy |
| `src/recommendation/similar_products.py` | 3, 4 | Qualified CF/semantic evidence and suppression |
| `src/recommendation/scoring.py` | 3 | Signed weighted contributions and thresholds |
| `src/recommendation/explanations.py` | 1, 3 | Sanitized and contribution-faithful explanations |
| `src/recommendation/diversity.py` | 3 | Visible diversity/forced-exploration attribution |
| `src/retrieval_output.py` | 3 | Accurate cold-start note policy |
| `src/api/routes_debug.py` | 0, 5 | Version/freshness reporting and safe rebuild endpoints |
| `frontend/src/components/ProductCard.tsx` | 3 | Render backend-owned reasons/badges |
| `frontend/src/pages/DebugPage.tsx` | 0, 5 | Freshness/version and evidence visibility |

---

## 13. Data Migration and Rebuild Runbook

This section defines work to perform only after explicit approval for data mutation.

### 13.1 Pre-Rebuild Snapshot

Capture:

- Collection counts.
- Current model/ranking versions.
- `phuc_demo` profile, signals, positive items, recent explanations, and CF edges.
- Count of invalid interest labels and cross-category explanation mismatches.
- Newest event versus newest signal/profile/CF timestamps.

### 13.2 Rebuild Sequence

```text
1. Deploy/activate approved clean signal and profile model versions.
2. Recompute user_item_signals from complete intended event history.
3. Recompute user_profiles from newly versioned signals.
4. Recompute item_item_cf_edges from newly versioned qualified signals.
5. Preserve historical recommendation_logs with their original ranking/model metadata.
6. Produce pre/post comparison report.
```

### 13.3 Required Post-Rebuild Assertions

| Assertion | Expected result |
|---|---|
| Invalid labels in current profiles | `0` for inspected demo users |
| Cross-category contaminated new reason | `0` |
| `phuc_demo` valid beauty and phone interests | May both exist |
| `phuc_demo` CF edges without multi-user support | Still `0`, unless support changed |
| Stored model versions | Match approved deployed versions |
| Freshness status | Current immediately after rebuild |

### 13.4 Rollback

Before write execution, define:

- Snapshot/export strategy for affected derived collections.
- Previous configured model version.
- Criteria requiring rollback: validation failure, unexpected loss of positive coverage, schema incompatibility, or severe rank regression.

Historical clickstream and recommendation logs must never be deleted solely to hide earlier explanation failure.

---

## 14. Test Plan

### 14.1 Unit Tests

| Area | Tests |
|---|---|
| Signal extraction | Impression neutrality, dwell tiers, cart/purchase dominance, negative scoring, invalid intent rejection |
| Profile building | Fact/UUID rejection, category-aware labels, aggregate event weighting, decay, multi-interest retention |
| Candidate generation | Seed eligibility, negative source exclusion, category fallback |
| Scoring | Contribution math, similarity threshold, negative/seen penalties |
| Explanations | Primary contribution selection, badge eligibility, accurate cold/CF text |
| CF | Support semantics, strong-event pair weighting, negative exclusion, edge symmetry |
| Freshness | Version fields, watermark reporting, partial-write protection |

### 14.2 Integration Tests

| Workflow | Required coverage |
|---|---|
| UI event -> signal | Logged UI actions yield intended signal tier and weights |
| Signal -> profile | Cart-bearing beauty behavior has dominant profile evidence |
| Profile -> home feed | Impression-only recent cards cannot derail neighbor seeds |
| Similar products -> CF explanation | CF reason only appears when retained edge contributes |
| Debug view | Version and staleness state are exposed consistently |
| Rebuild | Rebuilding derived collections from fixture removes contamination |

### 14.3 E2E Walkthrough Tests

Create a deterministic walkthrough for a user shaped like `phuc_demo`:

1. Search for sensitive-skin soap.
2. Open one soap item and add it to cart.
3. Browse several smartphone items briefly.
4. Return to home feed.
5. Inspect explanations and score breakdown.

Expected outcome:

- Beauty/cart interest remains prominent.
- Some smartphone recommendations may remain valid.
- Beauty reasons mention beauty/soap only.
- Smartphone reasons mention smartphone/semantic evidence only when material.
- No CF badge is shown unless multi-user edge exists.
- Debug shows whether events are incorporated into current profile.

---

## 15. Evaluation Matrix and Decision Rules

| Enhancement | Decision level | Required evidence before enablement |
|---|---:|---|
| Sanitized profile labels and category-aware explanations | Must | Deterministic tests and post-rebuild data audit |
| Deliberate seed selection | Must | Unit/integration tests plus no relevance regression |
| Weighted aggregate profile contributions | Must | Temporal offline evaluation improves deliberate target NDCG |
| Contribution-based reasons | Must | Explanation faithfulness audit and UI tests |
| Negative source suppression | Must | Negative re-exposure tests |
| Click/dwell weight calibration | Should | Parameter sweep and offline/online validation |
| Time/interest decay | Should | Temporal evaluation demonstrates drift benefit |
| Strong-event CF eligibility | Should | CF precision/coverage comparison |
| Incremental profiles | Should for production | Freshness SLO and idempotency proof |
| Support-one "CF" | Do not implement | Violates CF semantics |

---

## 16. Suggested Delivery Milestones

| Milestone | Includes | Exit condition |
|---|---|---|
| M0 - Baseline captured | Phase 0 scripts/contracts | Reproducible audit fixture and version contract |
| M1 - Demo correctness fixed | Phase 1 plus approved rebuild | No invalid reason in walkthrough |
| M2 - Personalization signal fixed | Phase 2 | Deliberate seeds and profile contribution validated |
| M3 - Honest UI reasons | Phase 3 | Reason/badge faithfulness gate passed |
| M4 - CF and suppression sound | Phase 4 | CF/suppression metrics accepted |
| M5 - Operationally safe | Phase 5 | Freshness visible and partial overwrite impossible |
| M6 - Production decision | Phase 6 | Offline and pilot gates signed off |

---

## 17. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Over-reducing click weight hurts new-user learning | Lower personalization coverage | Evaluate control versus candidates; retain exploration lane |
| Hard category constraints suppress legitimate cross-category intent | Less discovery | Category-aware explanations, not blanket category blocking |
| Rebuild changes demo outputs immediately | Demo inconsistency | Snapshot before rebuild; scripted walkthrough after rebuild |
| CF qualification lowers visible CF coverage | UI appears less feature-rich | Report honestly; separate semantic/session neighbors if needed |
| Contribution reasons become too technical | Poor shopper experience | Show short primary reason; keep numeric detail in debug drawer |
| Incremental updates increase complexity | Operational failures | Stage after correctness phases; retain full rebuild fallback |

---

## 18. Definition of Done

The enhancement program is complete for demo readiness when:

- Stored current profiles contain no UUID/fact-contaminated user-facing labels.
- Beauty items never display smartphone-fact reasons in the deterministic walkthrough.
- Impression-only items cannot act as personalized semantic/CF seeds.
- Cart-bearing intent is materially represented in profile scoring.
- Badges and `Why shown` represent actual rank contribution.
- CF claims remain multi-user and honest.
- Debug UI clearly indicates freshness/version state.

It is complete for production readiness only when, additionally:

- Offline temporal evaluation meets approved relevance and safety gates.
- Online or shadow testing confirms no harmful engagement/negative-feedback regression.
- Incremental or scheduled refresh has an observable freshness SLO.
- Migration, rollback, and derivation-version runbooks have been exercised.

---

## 19. Immediate Next Work Items

The implementation sequence to begin after this plan is approved:

1. Formalize Phase 0 derived-data version fields and baseline regression fixture.
2. Review and finalize the in-progress Phase 1 hygiene changes already present in the working tree.
3. Add missing tests for stale-data rebuild, invalid UUID labels, and no-cross-category reason.
4. Request explicit approval before any MongoDB rebuild or migration.
5. Run a clean post-rebuild `phuc_demo` walkthrough and record evidence before moving to signal calibration.

