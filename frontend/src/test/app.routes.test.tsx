import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { ExperienceProvider } from "../state/experience";


const STORAGE_KEY = "coldstart-killer/frontend-state/v1";
const LOGIN_SESSION_KEY = "coldstart-killer/active-login/v1";
const ADMIN_TOKEN_STORAGE_KEY = "coldstart-killer/admin-token/v1";
const DEBUG_ADMIN_TOKEN = "test-admin-token";
const longHomeExplanation =
    "Boosted because it matches your sensitive skin profile and preference for natural ingredients with gentle hydration support.";
const additionalHomeExplanation = "Also supported by recent skincare browsing signals.";

const baseRecommendationItem = {
    request_id: "req_test_1",
    surface: "home",
    rank_position: 1,
    algorithm_version: "rec_v1_profile_cf_hype",
    ranking_version: "rank_v1_default_weights",
    item_id: "item_1",
    title: "Test Charger Block",
    brand: "DemoBrand",
    category_id: "all_electronics",
    price_bucket: "100k_300k",
    price_vnd: 199000,
    image_url: null,
    is_cold_item: false,
    interaction_count: 0,
    score: 0.91,
    final_score: 0.91,
    matched_intent: "fast charger",
    matched_fact: "",
    cold_start_note: "",
    scores: { final_score: 0.91 },
    score_breakdown: { final_score: 0.91 },
    reason_badges: ["HyPE semantic"],
    explanations: ["Matched HyPE intent."],
    candidate_sources: ["query_hybrid"],
    attribution: {
        matched_unit_ids: [],
        matched_intents: ["fast charger"],
        matched_facts: [],
        matched_channels: ["vector"],
        candidate_sources: ["query_hybrid"],
        matched_profile_interest_ids: [],
        matched_interest_embedding: null,
        matched_neighbor_embedding: null,
        cf_evidence: null,
        primary_reason_channel: "query_hybrid",
        primary_reason_contribution: 0.7,
        material_reason_channels: ["query_hybrid"],
        forced_cold_insertion: false,
        explanation: "Matched HyPE intent.",
    },
    debug: {
        matched_channels: ["vector"],
        matched_aspects: [],
        matched_unit_ids: [],
        candidate_sources: ["query_hybrid"],
        profile_interest_label: "",
        cf_evidence: null,
    },
};

const homeResponse = {
    request_id: "req_home_1",
    surface: "home",
    algorithm_version: "rec_v1_profile_cf_hype",
    ranking_version: "rank_v1_default_weights",
    items: [
        {
            ...baseRecommendationItem,
            request_id: "req_home_1",
            explanations: [longHomeExplanation, additionalHomeExplanation],
        },
    ],
    snapshot: { ok: true },
    user_id_hash: "u_test_user",
    personalized: true,
    user_state: "new",
};

const searchResponse = {
    request_id: "req_search_1",
    surface: "search",
    algorithm_version: "rec_v1_profile_cf_hype",
    ranking_version: "rank_v1_default_weights",
    items: [
        {
            ...baseRecommendationItem,
            request_id: "req_search_1",
            surface: "search",
            title: "Search Result Charger",
        },
    ],
    snapshot: { ok: true },
    user_id_hash: "u_test_user",
    personalized: true,
    query: {
        raw_query: "wireless charger under 300k",
        language_detected: "vi",
        english_query: "wireless charger under 300k",
        hype_search_query_en: "user looking for a wireless charger under 300k for everyday use",
        bm25_search_query_en: "wireless charger under 300k",
        hard_filters: { max_price_vnd: 300000 },
        query_type: "semantic",
        query_embedding: null,
    },
};

const detailResponse = {
    item_id: "item_1",
    title: "Detail Product Title",
    brand: "DemoBrand",
    source_category: "Electronics",
    category_id: "all_electronics",
    category_path: ["electronics"],
    price_vnd: 199000,
    price_bucket: "100k_300k",
    image_url: null,
    image_fallback_url: null,
    image_urls: [],
    quality_score: 0.88,
    cold_start: {
        is_cold_item: false,
        interaction_count: 0,
    },
    description_enriched: {},
    source_text: {
        description_text: "Compact charging product description.",
        features_text: "Fast charging\nTravel friendly",
        details_text: "Input: USB-C",
    },
    text_stats: {},
};

const similarResponse = {
    request_id: "req_similar_1",
    surface: "detail_similar",
    algorithm_version: "rec_v1_profile_cf_hype",
    ranking_version: "rank_v1_default_weights",
    items: [
        {
            ...baseRecommendationItem,
            request_id: "req_similar_1",
            surface: "detail_similar",
            title: "Similar Product Title",
        },
    ],
    snapshot: { ok: true },
    user_id_hash: "u_test_user",
    personalized: true,
    source_item_id: "item_1",
};

const debugResponse = {
    user: { user_id_hash: "u_test_user" },
    profile: { user_id_hash: "u_test_user" },
    signals: [{ signal_type: "click" }],
    recent_logs: [{ request_id: "req_home_1" }],
    recent_events: [{ event_type: "impression" }],
    cf_edges: [{ source_item_id: "item_1", neighbor_item_id: "item_2" }],
    freshness: {
        state: "stale_version",
        latest_event_at: "2026-01-01T02:00:00+00:00",
        signal_built_at: "2026-01-01T01:00:00+00:00",
        profile_built_at: "2026-01-01T01:00:00+00:00",
        cf_built_at: "2026-01-01T01:30:00+00:00",
        pending_event_count: 1,
        stale_components: ["signals", "profile", "cf"],
        components: {
            signals: { state: "pending", built_at: "2026-01-01T01:00:00+00:00" },
            profile: { state: "pending", built_at: "2026-01-01T01:00:00+00:00" },
            cf: { state: "refresh_required", built_at: "2026-01-01T01:30:00+00:00", input_policy: "current_supported" },
        },
        next_actions: ["Apply pending behavior to refresh signals and profiles.", "Schedule a full CF refresh after behavior processing."],
        model_versions: {
            configured: {
                signal_model_version: "signal_v2_reason_hygiene",
                profile_model_version: "profile_v2_clean_category_guard",
                cf_model_version: "cf_v1_supported_edges",
                explanation_version: "explain_v2_profile_threshold",
            },
            stored: {
                signal_model_version: "signal_v1_legacy",
                profile_model_version: "profile_v1_legacy",
                cf_model_version: "cf_v1_supported_edges",
                explanation_version: null,
            },
            stale_version_components: ["signal", "profile"],
        },
    },
};

const demoStatusResponse = {
    ok: true,
    protected_collections: ["items", "retrieval_units"],
    counts: {
        recommendation_logs: 12,
        clickstream_events: 10,
        user_item_signals: 8,
        user_profiles: 4,
        item_stats: 7,
        item_item_cf_edges: 6,
    },
    model_versions: {
        signal_model_version: "signal_v2_reason_hygiene",
        profile_model_version: "profile_v2_clean_category_guard",
        cf_model_version: "cf_v1_supported_edges",
        explanation_version: "explain_v2_profile_threshold",
    },
    cf_evidence_available: true,
    precomputed_cf_note: "Existing CF edges may come from seeded/precomputed synthetic behavior.",
};

const evaluationEmptyResponse = {
    ok: true,
    empty: true,
    latest: null,
    message: "No persisted evaluation runs yet. Run scripts/run_personalization_evaluation.py --write-evaluation-run --confirm EVAL_RUN_WRITE after human approval.",
};

const evaluationLatestResponse = {
    ok: true,
    empty: false,
    latest: {
        id: "eval_object_id",
        run_id: "personalization_20260525",
        run_type: "personalization_eval",
        algorithm_version: "rec_v1_profile_cf_hype",
        ranking_version: "rank_v1_default_weights",
        data_label: "synthetic/demo evaluation",
        synthetic_data: true,
        metrics: { baseline_count: 2, comparison_count: 1 },
        baseline_summaries: [
            {
                baseline: "profile_only",
                evaluated_user_count: 42,
                hit_rate_at_10: 0.04,
                recall_at_20: 0.05,
                map_at_20: 0.01,
                coverage: 0.17,
                cold_start_exposure_at_20: 1,
                cf_supported_recommendation_count: 0,
            },
            {
                baseline: "profile_plus_cf",
                evaluated_user_count: 42,
                hit_rate_at_10: 0.16,
                recall_at_20: 0.07,
                map_at_20: 0.02,
                coverage: 0.06,
                cold_start_exposure_at_20: 1,
                cf_supported_recommendation_count: 433,
            },
        ],
        comparisons: [
            {
                comparison: "profile_plus_cf_vs_profile_only",
                hit_rate_at_10_delta: 0.12,
                recall_at_20_delta: 0.02,
                map_at_20_delta: 0.01,
                cf_supported_count_delta: 433,
            },
        ],
        live_state_counts: {
            items: 3000,
            clickstream_events: 2121,
            user_profiles: 43,
        },
        caveat: "Synthetic/demo behavior data, not production traffic.",
        evaluated_user_count: 42,
        artifacts: { written: false, path: null },
        created_at: "2026-05-25T00:00:00+00:00",
    },
};

function jsonResponse(payload: unknown) {
    return Promise.resolve(
        new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        }),
    );
}


function readHeader(init: RequestInit | undefined, name: string) {
    const headers = init?.headers;
    if (!headers) {
        return null;
    }
    if (headers instanceof Headers) {
        return headers.get(name);
    }
    if (Array.isArray(headers)) {
        const match = headers.find(([key]) => key.toLowerCase() === name.toLowerCase());
        return match?.[1] ?? null;
    }
    const entries = Object.entries(headers);
    const match = entries.find(([key]) => key.toLowerCase() === name.toLowerCase());
    return typeof match?.[1] === "string" ? match[1] : null;
}


function unauthorizedAdminResponse() {
    return Promise.resolve(
        new Response(
            JSON.stringify({ detail: { error: "admin_token_required", message: "A valid X-Admin-Token header is required for debug/demo routes." } }),
            {
                status: 403,
                headers: { "Content-Type": "application/json" },
            },
        ),
    );
}


function installFetchMock() {
    let createdUser: Record<string, unknown> | null = null;
    let sellerDraft: any | null = null;

    return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
        if (
            (url.includes("/api/debug/") || url.includes("/api/demo/") || url.includes("/api/jobs/"))
            && readHeader(init, "X-Admin-Token") !== DEBUG_ADMIN_TOKEN
        ) {
            return unauthorizedAdminResponse();
        }
        if (url.includes("/api/health")) {
            return jsonResponse({
                ok: true,
                service: "coldstart-killer-api",
                algorithm_version: "rec_v1_profile_cf_hype",
                ranking_version: "rank_v1_default_weights",
            });
        }
        if (url.includes("/api/users/demo")) {
            return jsonResponse({
                users: [
                    ...(createdUser ? [createdUser] : []),
                    {
                        user_id_hash: "u_test_user",
                        demo_label: "Authenticated test shopper",
                        profile_status: "warm",
                        has_profile: true,
                        privacy: {
                            allow_personalization: true,
                            allow_clickstream_logging: true,
                        },
                        onboarding: {
                            completed: false,
                            selected_categories: [],
                            selected_price_buckets: [],
                            selected_seed_item_ids: [],
                            selected_intents: [],
                        },
                    },
                    {
                        user_id_hash: "u_syn_p_budget_skincare_01",
                        profile_status: "warm",
                        has_profile: true,
                        privacy: {
                            allow_personalization: true,
                            allow_clickstream_logging: true,
                        },
                        onboarding: {
                            completed: false,
                            selected_categories: [],
                            selected_price_buckets: [],
                            selected_seed_item_ids: [],
                            selected_intents: [],
                        },
                    },
                ],
                personas: [
                    {
                        persona_id: "p_budget_skincare",
                        label: "Budget skincare shopper",
                        preferred_categories: {},
                        preferred_price_buckets: {},
                        intent_keywords: ["cleanser"],
                        negative_keywords: [],
                    },
                ],
            });
        }
        if (url.endsWith("/api/users")) {
            createdUser = {
                user_id_hash: "u_api_personal_test",
                username: "Phuc demo shopper",
                profile_status: "new",
                demo_label: "Phuc demo shopper",
                demo_source: "user_created",
                has_profile: false,
                privacy: {
                    allow_personalization: true,
                    allow_clickstream_logging: true,
                },
                onboarding: {
                    completed: false,
                    selected_categories: [],
                    selected_price_buckets: [],
                    selected_seed_item_ids: [],
                    selected_intents: [],
                },
            };
            return jsonResponse(createdUser);
        }
        if (url.includes("/api/onboarding/options")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                categories: [
                    { id: "all_beauty", label: "All Beauty", count: 24 },
                    { id: "all_electronics", label: "All Electronics", count: 18 },
                ],
                price_buckets: [
                    { id: "unknown", label: "Open to any price" },
                    { id: "100k_300k", label: "100k to 300k" },
                ],
                intent_chips: [
                    { id: "daily_use", label: "Daily use" },
                    { id: "gift_ready", label: "Gift ready" },
                ],
                seed_items: [
                    {
                        item_id: "ITEM_A",
                        title: "Hydrating Cleanser",
                        brand: "DemoBeauty",
                        category_id: "all_beauty",
                        price_bucket: "100k_300k",
                        price_vnd: 199000,
                        image_url: null,
                    },
                ],
                source: "catalog_snapshot",
            });
        }
        if (url.includes("/api/onboarding/preview")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                write_performed: false,
                preview: {
                    selected_categories: ["all_beauty"],
                    selected_price_buckets: ["100k_300k"],
                    selected_intents: ["daily_use"],
                    selected_seed_item_ids: ["ITEM_A"],
                    seed_items: [
                        {
                            item_id: "ITEM_A",
                            title: "Hydrating Cleanser",
                            brand: "DemoBeauty",
                            category_id: "all_beauty",
                            price_bucket: "100k_300k",
                            price_vnd: 199000,
                            image_url: null,
                        },
                    ],
                    summary: "Selected 1 categories, 1 price preferences, 1 shopping intents, 1 seed items",
                },
                explanation: "Preview only. These preferences become onboarding events after explicit completion.",
            });
        }
        if (url.includes("/api/onboarding/complete")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                write_performed: true,
                user_id_hash: "u_test_user",
                onboarding: {
                    completed: true,
                    completed_at: "2026-05-26T00:00:00+00:00",
                    selected_categories: ["all_beauty"],
                    selected_price_buckets: ["100k_300k"],
                    selected_intents: ["daily_use"],
                    selected_seed_item_ids: ["ITEM_A"],
                },
                events_attempted: 1,
                events_inserted: 1,
                message: "Onboarding saved. Run behavior processing later to derive signals and profile updates.",
            });
        }
        if (url.includes("/api/enrichment/seller-drafts/draft_test_1/preview")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                status: "ready",
                draft_id: "draft_test_1",
                provider: "tavily",
                provider_configured: true,
                query: "DemoSun Seller Sunscreen all_beauty",
                write_performed: false,
                message: "Preview only. Request enrichment explicitly to call the configured provider.",
                required_confirmation: "APPLY_WEB_ENRICHMENT",
            });
        }
        if (url.includes("/api/enrichment/seller-drafts/draft_test_1/request")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                status: "completed",
                request: {
                    request_id: "enrich_test_1",
                    draft_id: "draft_test_1",
                    seller_id: "seller_demo_001",
                    provider: "fake_provider",
                    query: "DemoSun Seller Sunscreen all_beauty",
                    status: "completed",
                    results: [
                        {
                            title: "DemoSun Seller Sunscreen source",
                            url: "https://example.test/enrichment-source",
                            snippet: "External evidence snippet for seller sunscreen.",
                            score: 0.7,
                            source: "fake_provider",
                        },
                    ],
                    suggested_fields: {
                        "attributes.web_evidence_summary": {
                            value: "External evidence snippet for seller sunscreen.",
                            confidence: 0.7,
                            source_urls: ["https://example.test/enrichment-source"],
                            reason: "Stores an auditable evidence summary without changing catalog documents.",
                        },
                    },
                    applied_fields: [],
                    created_at: "2026-05-26T00:00:00+00:00",
                    updated_at: "2026-05-26T00:00:00+00:00",
                    error: null,
                },
                write_scope: ["web_enrichment_requests", "seller_product_drafts"],
                catalog_write_performed: false,
            });
        }
        if (url.includes("/api/enrichment/requests/enrich_test_1/apply")) {
            sellerDraft = {
                ...(sellerDraft || {}),
                enrichment: {
                    status: "applied",
                    latest_request_id: "enrich_test_1",
                    applied_request_ids: ["enrich_test_1"],
                    applied_fields: ["attributes.web_evidence_summary"],
                    source_urls: ["https://example.test/enrichment-source"],
                },
                attributes: {
                    ...(sellerDraft?.attributes || {}),
                    web_evidence_summary: "External evidence snippet for seller sunscreen.",
                },
            };
            return jsonResponse({
                ok: true,
                enabled: true,
                status: "applied",
                request_id: "enrich_test_1",
                draft_id: "draft_test_1",
                applied_fields: ["attributes.web_evidence_summary"],
                source_urls: ["https://example.test/enrichment-source"],
                draft: sellerDraft,
                write_scope: ["seller_product_drafts", "web_enrichment_requests"],
                catalog_write_performed: false,
            });
        }
        if (url.includes("/api/seller/drafts/draft_test_1/approve-index")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                write_performed: true,
                catalog_write_performed: true,
                draft_id: "draft_test_1",
                item_id: "seller_seller_demo_001_seller_sunscreen_abc123",
                inserted_items: 1,
                inserted_retrieval_units: 2,
                writes: ["items", "retrieval_units", "seller_product_drafts"],
                forbidden_writes_performed: [],
                message: "Seller draft indexed additively. Run separate reviewed HyPE/item profile rebuild if vector exposure is required.",
            });
        }
        if (url.includes("/api/seller/drafts/draft_test_1/index-preview")) {
            sellerDraft = {
                ...(sellerDraft || {}),
                status: "previewed",
                indexing_preview: {
                    preview_only: true,
                    catalog_write_performed: false,
                    valid: true,
                    validation_errors: [],
                    validation_warnings: [],
                    proposed_item_id: "seller_seller_demo_001_seller_sunscreen_abc123",
                    estimated_retrieval_units: 2,
                    vector_units_generated: 0,
                    requires_hype_profile_rebuild: true,
                    message: "Preview uses seller-provided text proposition units only.",
                    retrieval_units: [
                        {
                            _id: "seller_prop_1",
                            item_id: "seller_seller_demo_001_seller_sunscreen_abc123",
                            unit_type: "proposition",
                            raw_text: "Seller Sunscreen",
                            text_search: "Seller Sunscreen",
                            source: "seller_submitted",
                            category_id: "all_beauty",
                            price_bucket: "100k_300k",
                            seller_confirmed: false,
                        },
                        {
                            _id: "seller_prop_2",
                            item_id: "seller_seller_demo_001_seller_sunscreen_abc123",
                            unit_type: "proposition",
                            raw_text: "Lightweight daily sunscreen for oily skin with comfortable finish.",
                            text_search: "Lightweight daily sunscreen for oily skin with comfortable finish.",
                            source: "seller_submitted",
                            category_id: "all_beauty",
                            price_bucket: "100k_300k",
                            seller_confirmed: false,
                        },
                    ],
                },
            };
            return jsonResponse({
                ok: true,
                enabled: true,
                draft_id: "draft_test_1",
                preview: sellerDraft.indexing_preview,
                write_scope: ["seller_product_drafts"],
                catalog_write_performed: false,
            });
        }
        if (url.includes("/api/seller/drafts/draft_test_1/validate")) {
            sellerDraft = {
                ...(sellerDraft || {}),
                status: "validated",
                validation_errors: [],
                validation_warnings: [],
            };
            return jsonResponse({ ok: true, enabled: true, draft: sellerDraft, write_scope: ["seller_product_drafts"] });
        }
        if (url.endsWith("/api/seller/drafts") && init?.method === "POST") {
            sellerDraft = {
                draft_id: "draft_test_1",
                seller_id: "seller_demo_001",
                title: "Seller Sunscreen",
                description: "Lightweight daily sunscreen for oily skin with comfortable finish.",
                brand: "DemoSun",
                category_id: "all_beauty",
                price_vnd: 299000,
                price_bucket: "100k_300k",
                image_url: null,
                attributes: {},
                status: "validated",
                validation_errors: [],
                validation_warnings: [],
                proposed_item_id: "seller_seller_demo_001_seller_sunscreen_abc123",
                indexing_preview: null,
                enrichment: {
                    status: "none",
                    latest_request_id: null,
                    applied_request_ids: [],
                    applied_fields: [],
                    source_urls: [],
                },
                created_at: "2026-05-26T00:00:00+00:00",
                updated_at: "2026-05-26T00:00:00+00:00",
            };
            return jsonResponse({ ok: true, enabled: true, draft: sellerDraft, write_scope: ["seller_product_drafts"] });
        }
        if (url.includes("/api/seller/drafts")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                drafts: sellerDraft ? [sellerDraft] : [],
                required_confirmation: "INDEX_SELLER_DRAFT",
            });
        }
        if (url.includes("/api/feed/home")) {
            return jsonResponse(homeResponse);
        }
        if (url.includes("/api/search")) {
            return jsonResponse(searchResponse);
        }
        if (url.includes("/api/items/item_1/similar")) {
            return jsonResponse(similarResponse);
        }
        if (url.includes("/api/items/item_1")) {
            return jsonResponse(detailResponse);
        }
        if (url.includes("/api/debug/user/")) {
            return jsonResponse(debugResponse);
        }
        if (url.includes("/api/demo/status")) {
            return jsonResponse(demoStatusResponse);
        }
        if (url.includes("/api/evaluation/runs/latest")) {
            return jsonResponse(evaluationEmptyResponse);
        }
        if (url.includes("/api/jobs/registry")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                trigger_api_enabled: false,
                jobs: [
                    {
                        job_type: "fusion_comparison_dry_run",
                        label: "Fusion comparison dry-run",
                        description: "Compares fusion strategies without changing production search defaults.",
                        category: "evaluation",
                        dry_run_default: true,
                        write_capable: false,
                        confirmation_required: null,
                        triggerable_from_api: true,
                        adapter: "manual_command",
                        command: "python scripts/compare_fusion_strategies.py --dry-run",
                        current_status: "available",
                    },
                    {
                        job_type: "run_evaluation_write",
                        label: "Persist evaluation run",
                        description: "Manual-only write job guarded by confirmation.",
                        category: "evaluation",
                        dry_run_default: true,
                        write_capable: true,
                        confirmation_required: "EVAL_RUN_WRITE",
                        triggerable_from_api: false,
                        adapter: "manual_command",
                        command: "python scripts/run_personalization_evaluation.py --write-evaluation-run --confirm EVAL_RUN_WRITE",
                        current_status: "manual_only",
                    },
                ],
            });
        }
        if (url.includes("/api/jobs/runs")) {
            return jsonResponse({
                ok: true,
                enabled: true,
                empty: true,
                runs: [],
                limit: 10,
            });
        }
        if (url.includes("/api/demo/reset")) {
            return jsonResponse({
                ok: true,
                mode: url.includes("write=true") ? "write" : "dry-run",
                reset_type: url.includes("full=true") ? "full" : "soft",
                rebuild_order: url.includes("full=true")
                    ? ["seed", "signals", "profiles", "cf"]
                    : ["seed", "signals", "profiles", "keep_cf"],
            });
        }
        if (url.includes("/api/demo/seed")) {
            return jsonResponse({
                ok: true,
                mode: url.includes("write=true") ? "write" : "dry-run",
                summary: { users: 40, requests: 120 },
            });
        }
        if (url.includes("/api/debug/process-events")) {
            return jsonResponse({ ok: true, stage: "signals" });
        }
        if (url.includes("/api/debug/apply-pending-behavior")) {
            return jsonResponse({ ok: true, processing_mode: "incremental_pending", cf_refresh_required: true });
        }
        if (url.includes("/api/debug/rebuild-profiles")) {
            return jsonResponse({ ok: true, stage: "profiles" });
        }
        if (url.includes("/api/debug/rebuild-cf")) {
            return jsonResponse({ ok: true, stage: "cf" });
        }
        if (url.includes("/api/events")) {
            return jsonResponse({ ok: true });
        }
        throw new Error(`Unhandled fetch URL in test: ${url}`);
    });
}

function eventPayloads() {
    return vi
        .mocked(globalThis.fetch)
        .mock.calls.filter(([input]) => String(input).includes("/api/events"))
        .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}


function renderApp(route: string, authenticated = true) {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
            userIdHash: "u_test_user",
            sessionId: "sess_test_ui",
            surfaces: {
                home: { requestId: null, impressionsLogged: [] },
                search: { requestId: null, impressionsLogged: [] },
                detail_similar: { requestId: null, impressionsLogged: [] },
            },
        }),
    );
    if (authenticated) {
        window.sessionStorage.setItem(LOGIN_SESSION_KEY, "true");
    }
    window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, DEBUG_ADMIN_TOKEN);

    return render(
        <QueryClientProvider client={queryClient}>
            <ExperienceProvider>
                <MemoryRouter initialEntries={[route]}>
                    <App />
                </MemoryRouter>
            </ExperienceProvider>
        </QueryClientProvider>,
    );
}


describe("Phase 11 routes", () => {
    beforeEach(() => {
        window.localStorage.clear();
        window.sessionStorage.clear();
        installFetchMock();
    });

    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
    });

    it("renders the homepage feed cards", async () => {
        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        expect(screen.getByText("Recommended for you")).toBeInTheDocument();
        expect(screen.getByText("No profile boost in this rank")).toBeInTheDocument();
        expect(screen.getByText("0 profile matches")).toBeInTheDocument();
    });

    it("counts profile-backed cards from backend badges instead of raw contribution", async () => {
        const fetchMock = vi.mocked(globalThis.fetch);
        const currentImplementation = fetchMock.getMockImplementation();
        fetchMock.mockImplementation((input, init) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/feed/home")) {
                return jsonResponse({
                    ...homeResponse,
                    items: [{ ...homeResponse.items[0], contributions: { profile: 0.01 }, reason_badges: ["HyPE semantic"] }],
                });
            }
            return currentImplementation!(input, init);
        });

        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        expect(screen.getByText("No profile boost in this rank")).toBeInTheDocument();
        expect(screen.getByText("0 profile matches")).toBeInTheDocument();
    });

    it("uses backend CF badges instead of inferring support from raw evidence", async () => {
        const fetchMock = vi.mocked(globalThis.fetch);
        const currentImplementation = fetchMock.getMockImplementation();
        fetchMock.mockImplementation((input, init) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/feed/home")) {
                return jsonResponse({
                    ...homeResponse,
                    items: [
                        {
                            ...homeResponse.items[0],
                            reason_badges: ["Profile"],
                            score_breakdown: { final_score: 0.91, item_item_cf_score: 1.0, semantic_neighbor_score: 1.0 },
                            attribution: {
                                ...homeResponse.items[0].attribution,
                                cf_evidence: { support: 3, cf_score: 0.8 },
                            },
                        },
                    ],
                });
            }
            return currentImplementation!(input, init);
        });

        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        expect(screen.getByText("0 CF-supported items")).toBeInTheDocument();
        expect(screen.queryByText("Collaborative Filtering")).not.toBeInTheDocument();
        expect(screen.queryByText("Semantic similar")).not.toBeInTheDocument();
    });

    it("shows refresh progress while retaining the current feed", async () => {
        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        const fetchMock = vi.mocked(globalThis.fetch);
        const currentImplementation = fetchMock.getMockImplementation();
        let resolveRefresh: ((response: Response) => void) | undefined;
        fetchMock.mockImplementation((input, init) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/feed/home")) {
                return new Promise<Response>((resolve) => {
                    resolveRefresh = resolve;
                });
            }
            return currentImplementation!(input, init);
        });

        fireEvent.click(screen.getByRole("button", { name: "Refresh feed" }));

        expect(await screen.findByRole("status")).toHaveTextContent("Refreshing recommendations");
        expect(screen.getByRole("button", { name: "Refreshing..." })).toBeDisabled();
        expect(screen.getByText("Test Charger Block")).toBeInTheDocument();

        resolveRefresh?.(
            new Response(JSON.stringify(homeResponse), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );
        await waitFor(() => expect(screen.queryByText("Refreshing recommendations. Current picks stay visible until the new ranking is ready.")).not.toBeInTheDocument());
    });

    it("expands long Why shown explanations without hiding additional reasons", async () => {
        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        expect(screen.getByText(longHomeExplanation)).toHaveClass("line-clamp-2");
        expect(screen.queryByText(additionalHomeExplanation)).not.toBeInTheDocument();

        const toggle = screen.getByRole("button", { name: "Read full reason" });
        expect(toggle).toHaveAttribute("aria-expanded", "false");
        fireEvent.click(toggle);

        expect(screen.getByText(longHomeExplanation)).not.toHaveClass("line-clamp-2");
        expect(screen.getByText(additionalHomeExplanation)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Collapse reason" })).toHaveAttribute("aria-expanded", "true");
    });

    it("logs each homepage recommendation impression once per request", async () => {
        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        await waitFor(() => {
            const impressions = eventPayloads().filter((payload) => payload.event_type === "impression");
            expect(impressions).toHaveLength(1);
            expect(impressions[0]).toMatchObject({
                user_id_hash: "u_test_user",
                session_id: "sess_test_ui",
                item_id: "item_1",
                event_type: "impression",
                surface: "home",
                request_id: "req_home_1",
                rank_position: 1,
                client: { component: "homepage-grid" },
            });
        });

        fireEvent.click(screen.getByRole("button", { name: "Refresh feed" }));
        await waitFor(() => {
            const feedCalls = vi
                .mocked(globalThis.fetch)
                .mock.calls.filter(([input]) => String(input).includes("/api/feed/home"));
            expect(feedCalls).toHaveLength(2);
            expect(eventPayloads().filter((payload) => payload.event_type === "impression")).toHaveLength(1);
        });
    });

    it("logs explicit homepage card actions with recommendation attribution", async () => {
        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Cart" }));

        await waitFor(() => {
            expect(eventPayloads()).toContainEqual(
                expect.objectContaining({
                    item_id: "item_1",
                    event_type: "add_to_cart",
                    surface: "home",
                    request_id: "req_home_1",
                    rank_position: 1,
                    client: { component: "homepage-card", device_type: "desktop" },
                }),
            );
        });
    });

    it("requires shopper selection before opening the homepage", async () => {
        renderApp("/", false);

        expect(await screen.findByText("Start a personalized shopping session")).toBeInTheDocument();
        expect(screen.queryByText("Recommended for you")).not.toBeInTheDocument();
    });

    it("enters a persona-backed shopper from sign in with a new session", async () => {
        renderApp("/login", false);

        const shopperSelect = await screen.findByLabelText("Shopper account or seeded persona");
        await screen.findByRole("option", { name: /Budget skincare shopper/ });
        fireEvent.change(shopperSelect, { target: { value: "u_syn_p_budget_skincare_01" } });
        fireEvent.click(screen.getByRole("button", { name: "Enter as selected shopper" }));

        expect(await screen.findByText("Persona: Budget skincare shopper")).toBeInTheDocument();
        await waitFor(() => {
            const state = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
            expect(state.userIdHash).toBe("u_syn_p_budget_skincare_01");
            expect(state.sessionId).not.toBe("sess_test_ui");
            expect(window.sessionStorage.getItem(LOGIN_SESSION_KEY)).toBe("true");
        });
    });

    it("creates a named personal shopper account", async () => {
        renderApp("/login", false);

        fireEvent.change(await screen.findByPlaceholderText("Example: Judge live demo"), {
            target: { value: "Phuc demo shopper" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Create account and choose preferences" }));

        await waitFor(() => {
            const call = vi
                .mocked(globalThis.fetch)
                .mock.calls.find(([input]) => String(input).endsWith("/api/users"));
            expect(call).toBeDefined();
            expect(String(call?.[1]?.body)).toContain('"display_name":"Phuc demo shopper"');
        });
        expect(await screen.findByText("Choose your starter preferences")).toBeInTheDocument();
    });

    it("renders onboarding and previews preferences without saving", async () => {
        renderApp("/onboarding");

        expect(await screen.findByText("Choose your starter preferences")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /All Beauty/ }));
        fireEvent.click(screen.getByRole("button", { name: /100k to 300k/ }));
        fireEvent.click(screen.getByRole("button", { name: /Daily use/ }));
        fireEvent.click(screen.getByRole("button", { name: /Hydrating Cleanser/ }));
        fireEvent.click(screen.getByRole("button", { name: "Preview preferences" }));

        expect(await screen.findByText(/Selected 1 categories/)).toBeInTheDocument();
        const previewCall = vi
            .mocked(globalThis.fetch)
            .mock.calls.find(([input]) => String(input).includes("/api/onboarding/preview"));
        expect(previewCall).toBeDefined();
        expect(String(previewCall?.[1]?.body)).toContain('"selected_categories":["all_beauty"]');
    });

    it("completes onboarding and sends only selected preferences to the API", async () => {
        renderApp("/onboarding");

        expect(await screen.findByText("Choose your starter preferences")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /All Beauty/ }));
        fireEvent.click(screen.getByRole("button", { name: /100k to 300k/ }));
        fireEvent.click(screen.getByRole("button", { name: /Daily use/ }));
        fireEvent.click(screen.getByRole("button", { name: /Hydrating Cleanser/ }));
        fireEvent.click(screen.getByRole("button", { name: "Complete onboarding" }));

        await waitFor(() => {
            const completeCall = vi
                .mocked(globalThis.fetch)
                .mock.calls.find(([input]) => String(input).includes("/api/onboarding/complete"));
            expect(completeCall).toBeDefined();
            const body = JSON.parse(String(completeCall?.[1]?.body)) as Record<string, unknown>;
            expect(body).toMatchObject({
                user_id_hash: "u_test_user",
                session_id: "sess_test_ui",
                selected_categories: ["all_beauty"],
                selected_price_buckets: ["100k_300k"],
                selected_intents: ["daily_use"],
                selected_seed_item_ids: ["ITEM_A"],
            });
        });
        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
    });

    it("allows shoppers to skip onboarding", async () => {
        renderApp("/onboarding");

        fireEvent.click(await screen.findByRole("button", { name: "Skip onboarding" }));

        expect(await screen.findByText("Recommended for you")).toBeInTheDocument();
        const onboardingCalls = vi
            .mocked(globalThis.fetch)
            .mock.calls.filter(([input]) => String(input).includes("/api/onboarding/complete"));
        expect(onboardingCalls).toHaveLength(0);
    });

    it("stages seller draft, previews indexing, and requires confirmation before catalog write", async () => {
        renderApp("/seller/drafts");

        expect(await screen.findByText("Draft, preview, then explicitly index")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("Product title"), { target: { value: "Seller Sunscreen" } });
        fireEvent.change(screen.getByLabelText("Brand"), { target: { value: "DemoSun" } });
        fireEvent.change(screen.getByLabelText("Category ID"), { target: { value: "all_beauty" } });
        fireEvent.change(screen.getByLabelText("Price VND"), { target: { value: "299000" } });
        fireEvent.change(screen.getByLabelText("Description"), {
            target: { value: "Lightweight daily sunscreen for oily skin with comfortable finish." },
        });
        fireEvent.click(screen.getByRole("button", { name: "Create draft" }));

        expect(await screen.findByText("Seller Sunscreen")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Validate draft" }));
        fireEvent.click(await screen.findByRole("button", { name: "Preview indexing" }));
        expect(await screen.findByText("Preview valid")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Approve and index seller draft" })).toBeDisabled();

        fireEvent.change(screen.getByPlaceholderText("INDEX_SELLER_DRAFT"), { target: { value: "INDEX_SELLER_DRAFT" } });
        fireEvent.click(screen.getByRole("button", { name: "Approve and index seller draft" }));

        expect(await screen.findByText(/indexed additively/i)).toBeInTheDocument();
        const approveCall = vi
            .mocked(globalThis.fetch)
            .mock.calls.find(([input]) => String(input).includes("/api/seller/drafts/draft_test_1/approve-index"));
        expect(approveCall).toBeDefined();
        expect(String(approveCall?.[0])).toContain("write=true");
        expect(String(approveCall?.[0])).toContain("confirm=INDEX_SELLER_DRAFT");
    });

    it("previews and applies web enrichment only after explicit confirmation", async () => {
        renderApp("/seller/drafts");

        expect(await screen.findByText("Draft, preview, then explicitly index")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("Product title"), { target: { value: "Seller Sunscreen" } });
        fireEvent.change(screen.getByLabelText("Brand"), { target: { value: "DemoSun" } });
        fireEvent.change(screen.getByLabelText("Category ID"), { target: { value: "all_beauty" } });
        fireEvent.change(screen.getByLabelText("Description"), {
            target: { value: "Lightweight daily sunscreen for oily skin with comfortable finish." },
        });
        fireEvent.click(screen.getByRole("button", { name: "Create draft" }));

        expect(await screen.findByText("Seller Sunscreen")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Preview enrichment query" }));
        expect(await screen.findByText("DemoSun Seller Sunscreen all_beauty")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /Request enrichment/ }));

        expect(await screen.findByText("https://example.test/enrichment-source")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Apply selected suggestions/ })).toBeDisabled();
        fireEvent.click(screen.getByLabelText(/attributes.web_evidence_summary/));
        expect(screen.getByRole("button", { name: /Apply selected suggestions/ })).toBeDisabled();
        fireEvent.change(screen.getByPlaceholderText("APPLY_WEB_ENRICHMENT"), { target: { value: "APPLY_WEB_ENRICHMENT" } });
        fireEvent.click(screen.getByRole("button", { name: /Apply selected suggestions/ }));

        await waitFor(() => {
            const applyCall = vi
                .mocked(globalThis.fetch)
                .mock.calls.find(([input]) => String(input).includes("/api/enrichment/requests/enrich_test_1/apply"));
            expect(applyCall).toBeDefined();
            expect(String(applyCall?.[0])).toContain("confirm=APPLY_WEB_ENRICHMENT");
            expect(String(applyCall?.[1]?.body)).toContain("attributes.web_evidence_summary");
        });
    });

    it("renders web enrichment provider setup state without auto-applying", async () => {
        const fetchMock = vi.mocked(globalThis.fetch);
        const currentImplementation = fetchMock.getMockImplementation();
        fetchMock.mockImplementation((input, init) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/enrichment/seller-drafts/draft_test_1/preview")) {
                return jsonResponse({
                    ok: true,
                    enabled: true,
                    status: "provider_not_configured",
                    draft_id: "draft_test_1",
                    provider: "tavily",
                    provider_configured: false,
                    query: "DemoSun Seller Sunscreen all_beauty",
                    write_performed: false,
                    message: "Web enrichment is enabled but TAVILY_API_KEY is not configured.",
                    required_confirmation: "APPLY_WEB_ENRICHMENT",
                });
            }
            return currentImplementation!(input, init);
        });

        renderApp("/seller/drafts");

        expect(await screen.findByText("Draft, preview, then explicitly index")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("Product title"), { target: { value: "Seller Sunscreen" } });
        fireEvent.change(screen.getByLabelText("Category ID"), { target: { value: "all_beauty" } });
        fireEvent.change(screen.getByLabelText("Description"), {
            target: { value: "Lightweight daily sunscreen for oily skin with comfortable finish." },
        });
        fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
        expect(await screen.findByText("Seller Sunscreen")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Preview enrichment query" }));

        expect(await screen.findByText("provider_not_configured")).toBeInTheDocument();
        expect(screen.getByText("Web enrichment is enabled but TAVILY_API_KEY is not configured.")).toBeInTheDocument();
        expect(screen.queryByText("External evidence snippet for seller sunscreen.")).not.toBeInTheDocument();
    });

    it("returns to shopper selection when changing account", async () => {
        renderApp("/");

        fireEvent.click(await screen.findByRole("button", { name: "Change shopper" }));

        expect(await screen.findByText("Start a personalized shopping session")).toBeInTheDocument();
        expect(window.sessionStorage.getItem(LOGIN_SESSION_KEY)).toBeNull();
    });

    it("renders the search page results for a query route", async () => {
        renderApp("/search?q=wireless%20charger%20under%20300k");

        expect(await screen.findByText("Search Result Charger")).toBeInTheDocument();
        expect(screen.getByText("HyPE semantic expansion")).toBeInTheDocument();
        expect(screen.getByText("user looking for a wireless charger under 300k for everyday use")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Search/i })).toBeInTheDocument();
    });

    it("does not duplicate category and price hints on repeated search submits", async () => {
        renderApp("/search");

        fireEvent.change(screen.getByRole("textbox"), { target: { value: "wireless charger under 300k" } });
        fireEvent.change(screen.getByDisplayValue("Any category"), { target: { value: "phone accessories" } });
        fireEvent.change(screen.getByDisplayValue("Any price"), { target: { value: "under 300k" } });
        fireEvent.click(screen.getByRole("button", { name: /^Search$/i }));
        expect(await screen.findByText("Search Result Charger")).toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: /^Search$/i }));

        await waitFor(() => {
            const searchCalls = vi
                .mocked(globalThis.fetch)
                .mock.calls.filter(([input]) => String(input).includes("/api/search"));
            const latestUrl = String(searchCalls.at(-1)?.[0]);
            expect(latestUrl).toContain("q=wireless+charger+under+300k+phone+accessories");
            expect(latestUrl).not.toContain("under+300k+under+300k");
            expect(latestUrl).not.toContain("phone+accessories+phone+accessories");
        });
    });

    it("preserves search attribution when opening a recommendation", async () => {
        renderApp("/search?q=wireless%20charger%20under%20300k");

        expect(await screen.findByText("Search Result Charger")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "View details" }));

        await waitFor(() => {
            expect(eventPayloads()).toContainEqual(
                expect.objectContaining({
                    item_id: "item_1",
                    event_type: "click",
                    surface: "search",
                    request_id: "req_search_1",
                    query_text: "wireless charger under 300k",
                    rank_position: 1,
                    client: { component: "search-card", device_type: "desktop" },
                }),
            );
        });
    });

    it("renders the item detail route with similar products", async () => {
        renderApp("/items/item_1");

        expect(await screen.findByText("Detail Product Title")).toBeInTheDocument();
        expect(await screen.findByText("Compact charging product description.")).toBeInTheDocument();
        expect(screen.getByText(/Fast charging/)).toBeInTheDocument();
        expect(await screen.findByText("Similar Product Title")).toBeInTheDocument();
    });

    it("preserves similar-product source attribution when opening details", async () => {
        renderApp("/items/item_1");

        expect(await screen.findByText("Similar Product Title")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "View details" }));

        await waitFor(() => {
            expect(eventPayloads()).toContainEqual(
                expect.objectContaining({
                    item_id: "item_1",
                    event_type: "click",
                    surface: "detail_similar",
                    request_id: "req_similar_1",
                    rank_position: 1,
                    client: { component: "similar-products-rail", device_type: "desktop" },
                    metadata: { source_item_id: "item_1" },
                }),
            );
        });
    });

    it("logs attributed detail dwell after navigating away from a recommendation", async () => {
        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "View details" }));
        expect(await screen.findByText("Detail Product Title")).toBeInTheDocument();
        fireEvent.click(screen.getAllByRole("link", { name: "Home" })[0]);

        await waitFor(() => {
            expect(eventPayloads()).toContainEqual(
                expect.objectContaining({
                    item_id: "item_1",
                    event_type: "view_detail",
                    surface: "home",
                    request_id: "req_home_1",
                    rank_position: 1,
                    dwell_time_ms: 500,
                    client: { component: "product-detail", device_type: "desktop" },
                }),
            );
        });
    });

    it("logs direct detail actions and dwell without recommendation attribution", async () => {
        renderApp("/items/item_1");

        expect(await screen.findByText("Detail Product Title")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Add to cart" }));
        fireEvent.click(screen.getAllByRole("link", { name: "Home" })[0]);

        await waitFor(() => {
            expect(eventPayloads()).toContainEqual(
                expect.objectContaining({
                    item_id: "item_1",
                    event_type: "add_to_cart",
                    surface: "detail",
                    client: { component: "product-detail", device_type: "desktop" },
                }),
            );
            expect(eventPayloads()).toContainEqual(
                expect.objectContaining({
                    item_id: "item_1",
                    event_type: "view_detail",
                    surface: "detail",
                    dwell_time_ms: 500,
                    client: { component: "product-detail", device_type: "desktop" },
                }),
            );
        });
    });

    it("renders the debug route with lineage payloads", async () => {
        renderApp("/debug");

        expect(await screen.findByText("Inspect lineage and operate the demo safely")).toBeInTheDocument();
        expect(await screen.findByText("Evaluation dashboard")).toBeInTheDocument();
        expect(await screen.findByText("No persisted evaluation runs yet.")).toBeInTheDocument();
        expect(screen.getAllByText(/EVAL_RUN_WRITE/).length).toBeGreaterThan(0);
        expect(screen.queryByRole("button", { name: /run evaluation/i })).not.toBeInTheDocument();
        expect(await screen.findByText("Job orchestration")).toBeInTheDocument();
        expect(await screen.findByText("Trigger API disabled")).toBeInTheDocument();
        expect(await screen.findByText(/No job_runs records yet/)).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /run job/i })).not.toBeInTheDocument();
        expect(await screen.findByText("Top signals")).toBeInTheDocument();
        expect(await screen.findByText("Demo Recovery")).toBeInTheDocument();
        expect(await screen.findByText("items")).toBeInTheDocument();
        expect(await screen.findByText("Derived version mismatch")).toBeInTheDocument();
        expect(await screen.findByText("Version rebuild required: signal, profile.")).toBeInTheDocument();
    });

    it("renders latest evaluation run summary and caveat on the debug route", async () => {
        const fetchMock = vi.mocked(globalThis.fetch);
        const currentImplementation = fetchMock.getMockImplementation();
        fetchMock.mockImplementation((input, init) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/evaluation/runs/latest")) {
                return jsonResponse(evaluationLatestResponse);
            }
            return currentImplementation!(input, init);
        });

        renderApp("/debug");

        expect(await screen.findByText("Latest personalization evaluation")).toBeInTheDocument();
        expect(await screen.findByText("personalization_20260525")).toBeInTheDocument();
        expect(screen.getByText("Synthetic/demo behavior data, not production traffic.")).toBeInTheDocument();
        expect(screen.getByText("profile_plus_cf")).toBeInTheDocument();
        expect(screen.getByText("profile_plus_cf_vs_profile_only")).toBeInTheDocument();
        expect(screen.getByText("rec_v1_profile_cf_hype")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /run evaluation/i })).not.toBeInTheDocument();
    });

    it("disables authoritative profile rebuild when a user limit is present", async () => {
        renderApp("/debug");

        const profilesPanel = (await screen.findByText("Profiles")).closest("section");
        expect(profilesPanel).not.toBeNull();
        const profileScope = within(profilesPanel as HTMLElement);

        fireEvent.change(profileScope.getByPlaceholderText("limit users (optional)"), { target: { value: "5" } });
        fireEvent.click(profileScope.getAllByRole("checkbox", { name: "write mode" })[0]);

        expect(profileScope.getByText("Write mode requires a full rebuild. Clear the user limit first.")).toBeInTheDocument();
        expect(profileScope.getByRole("button", { name: "Rebuild profiles" })).toBeDisabled();
    });

    it("applies captured behavior incrementally without rebuilding cf inline", async () => {
        renderApp("/debug");

        fireEvent.click(await screen.findByRole("button", { name: "Preview pending behavior" }));

        expect(await screen.findByText("Applied behavior response")).toBeInTheDocument();
        expect(screen.getByText(/"processing_mode": "incremental_pending"/)).toBeInTheDocument();
        expect(screen.getByText(/"cf_refresh_required": true/)).toBeInTheDocument();
        const calls = vi.mocked(globalThis.fetch).mock.calls;
        expect(calls.some(([input]) => String(input).includes("/api/debug/apply-pending-behavior"))).toBe(true);
        expect(calls.some(([input]) => String(input).includes("/api/debug/rebuild-cf"))).toBe(false);
        const applyCall = calls.find(([input]) => String(input).includes("/api/debug/apply-pending-behavior"));
        expect(String(applyCall?.[0])).not.toContain("write=true");
    });

    it("submits a full reset from the debug route with confirmation", async () => {
        renderApp("/debug");

        const resetPanel = (await screen.findByText("Reset behavior data")).closest("section");
        expect(resetPanel).not.toBeNull();
        const resetScope = within(resetPanel as HTMLElement);

        fireEvent.click(resetScope.getByRole("checkbox", { name: "write mode" }));
        fireEvent.click(resetScope.getByRole("checkbox", { name: "full reset" }));
        fireEvent.change(resetScope.getByPlaceholderText("FULL_DEMO_RESET"), { target: { value: "FULL_DEMO_RESET" } });
        fireEvent.click(resetScope.getByRole("button", { name: "Run reset" }));

        expect(await screen.findByText("Reset response")).toBeInTheDocument();
        expect(screen.getByText(/"reset_type": "full"/)).toBeInTheDocument();
        expect(screen.getByText("This will clear current demo interactions.")).toBeInTheDocument();
        await waitFor(() => {
            const call = vi
                .mocked(globalThis.fetch)
                .mock.calls.find(([input]) => String(input).includes("/api/demo/reset"));
            expect(call).toBeDefined();
            expect(String(call?.[0])).toContain("write=true");
            expect(String(call?.[0])).toContain("full=true");
            expect(String(call?.[0])).toContain("confirm=FULL_DEMO_RESET");
        });
    });

    it("submits synthetic seed from the debug route", async () => {
        renderApp("/debug");

        const seedPanel = (await screen.findByText("Seed synthetic behavior")).closest("section");
        expect(seedPanel).not.toBeNull();
        const seedScope = within(seedPanel as HTMLElement);

        fireEvent.click(seedScope.getByRole("checkbox", { name: "write mode" }));
        fireEvent.change(seedScope.getByPlaceholderText("SEED_DEMO_BEHAVIOR"), { target: { value: "SEED_DEMO_BEHAVIOR" } });
        fireEvent.click(seedScope.getByRole("button", { name: "Run seed" }));

        expect(await screen.findByText("Seed response")).toBeInTheDocument();
        expect(screen.getByText(/"summary":/)).toBeInTheDocument();
        await waitFor(() => {
            const call = vi
                .mocked(globalThis.fetch)
                .mock.calls.find(([input]) => String(input).includes("/api/demo/seed"));
            expect(call).toBeDefined();
            expect(String(call?.[0])).toContain("write=true");
            expect(String(call?.[0])).toContain("confirm=SEED_DEMO_BEHAVIOR");
        });
    });
});
