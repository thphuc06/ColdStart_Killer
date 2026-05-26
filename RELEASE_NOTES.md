# Release Notes

## Current State

This repository is in a validated post-hardening state for the current Phase 14 demo path.

## Included Updates

- Seller draft flow now requires admin or seller auth for protected actions.
- Seller scope isolation is enforced for seller-owned draft and enrichment resources.
- Approve-index requires a persisted preview and rolls back partial catalog writes on failure.
- Web enrichment request/apply flow is gated by `ENABLE_WEB_ENRICHMENT` and now rolls back inconsistent second-write failures.
- Frontend seller/enrichment flows now use bearer auth and clear stale draft/enrichment UI state correctly.
- Search pipeline keeps category include/exclude filters together correctly.
- Broad/exploratory recommendation path now reuses a safe lightweight catalog snapshot cache.
- CLI job runner forwards `dry_run` correctly.

## Validation Summary

- Focused seller/auth/enrichment/recommendation/backend regression batches passed.
- Focused frontend UI tests for seller draft and enrichment flows passed.
- Runtime smoke passed for seller/enrichment flow with live provider and MongoDB.
- Guarded smoke also passed with `AUTH_MODE=demo` using configured seller token.

## Residual Risks

- Python 3.14 still emits a torch/sentence-transformers stability warning. Python 3.10-3.12 remains the safer demo runtime.
- Seller/admin write flows are protected and require valid tokens plus confirmation strings; keep fallback demo scope shopper-first if those protected flows are not needed live.

## Recommended Demo Config

- Keep `AUTH_MODE=demo`.
- Keep `CACHE_BACKEND=none` unless Redis has been explicitly verified.
- Keep seller/enrichment enabled only if those flows are part of the planned demo.
- Do not change `.env` during the demo session unless a human explicitly approves the change.