export type RecommendationSurface = "home" | "search" | "detail_similar";
export type EventSurface = RecommendationSurface | "detail" | "cart" | "onboarding" | "debug";
export type EventType =
    | "impression"
    | "click"
    | "view_detail"
    | "add_to_cart"
    | "purchase"
    | "hide"
    | "dislike"
    | "wishlist";

export type HealthResponse = {
    ok: boolean;
    service: string;
    algorithm_version: string;
    ranking_version: string;
};

export type DemoUser = {
    user_id_hash: string;
    profile_status: string;
    created_at?: string;
    updated_at?: string;
    has_profile?: boolean;
    username?: string;
    demo_label?: string;
    demo_source?: string;
    privacy: {
        allow_personalization: boolean;
        allow_clickstream_logging: boolean;
    };
    onboarding: {
        completed: boolean;
        selected_categories: string[];
        selected_price_buckets: string[];
        selected_seed_item_ids: string[];
        selected_intents?: string[];
    };
};

export type Persona = {
    persona_id: string;
    label: string;
    preferred_categories: Record<string, number>;
    preferred_price_buckets: Record<string, number>;
    intent_keywords: string[];
    negative_keywords: string[];
    created_at?: string;
    updated_at?: string;
};

export type DemoUsersResponse = {
    users: DemoUser[];
    personas: Persona[];
};

export type RecommendationCard = {
    request_id: string;
    surface: RecommendationSurface;
    rank_position: number;
    algorithm_version: string;
    ranking_version: string;
    item_id: string;
    title: string;
    brand: string;
    category_id: string;
    price_bucket: string;
    price_vnd?: number | null;
    image_url?: string | null;
    image_fallback_url?: string | null;
    is_cold_item: boolean;
    interaction_count: number;
    score: number;
    final_score: number;
    contributions?: Record<string, number>;
    matched_intent: string;
    matched_fact: string;
    cold_start_note: string;
    scores: Record<string, number>;
    score_breakdown: Record<string, number>;
    reason_badges: string[];
    explanations: string[];
    candidate_sources: string[];
    attribution: {
        matched_unit_ids: string[];
        matched_intents: string[];
        matched_facts: string[];
        matched_channels: string[];
        candidate_sources: string[];
        matched_profile_interest_ids: string[];
        matched_interest_embedding?: number[] | null;
        matched_neighbor_embedding?: number[] | null;
        cf_evidence?: {
            source_item_id?: string;
            neighbor_item_id?: string;
            support?: number;
            co_click_count?: number;
            co_cart_count?: number;
            cf_score?: number;
        } | null;
        primary_reason_channel:
        | "query_hybrid"
        | "profile"
        | "semantic_neighbor"
        | "cf"
        | "cold_explore"
        | "generic";
        primary_reason_contribution: number;
        material_reason_channels: Array<"query_hybrid" | "profile" | "semantic_neighbor" | "cf" | "cold_explore" | "generic">;
        forced_cold_insertion: boolean;
        explanation: string;
    };
    debug: {
        matched_channels: string[];
        matched_aspects: string[];
        matched_unit_ids: string[];
        candidate_sources: string[];
        profile_interest_label: string;
        cf_evidence?: RecommendationCard["attribution"]["cf_evidence"];
    };
};

export type RecommendationResponse = {
    request_id: string;
    surface: RecommendationSurface;
    algorithm_version: string;
    ranking_version: string;
    items: RecommendationCard[];
    snapshot: Record<string, unknown>;
    user_id_hash?: string;
    personalized?: boolean;
};

export type HomepageResponse = RecommendationResponse & {
    surface: "home";
    user_state: string;
};

export type SearchResponse = RecommendationResponse & {
    surface: "search";
    query: {
        raw_query: string;
        language_detected?: string;
        english_query: string;
        hype_search_query_en?: string;
        bm25_search_query_en?: string;
        hard_filters?: Record<string, unknown>;
        query_type: string;
        query_embedding?: number[] | null;
    };
};

export type SimilarProductsResponse = RecommendationResponse & {
    surface: "detail_similar";
    source_item_id: string;
};

export type ItemDetailResponse = {
    item_id: string;
    title: string;
    brand: string;
    source_category: string;
    category_id: string;
    category_path: string[];
    price_vnd?: number | null;
    price_bucket: string;
    image_url?: string | null;
    image_fallback_url?: string | null;
    image_urls: string[];
    quality_score: number;
    cold_start: {
        is_cold_item: boolean;
        interaction_count: number;
    };
    description_enriched: Record<string, unknown>;
    source_text: {
        description_text: string;
        features_text: string;
        details_text: string;
    };
    text_stats: Record<string, unknown>;
};

export type DebugUserResponse = {
    user: Record<string, unknown> | null;
    profile: Record<string, unknown> | null;
    signals: Record<string, unknown>[];
    recent_logs: Record<string, unknown>[];
    recent_events: Record<string, unknown>[];
    cf_edges: Record<string, unknown>[];
    freshness: {
        state: "current" | "stale" | "stale_version" | "unknown";
        latest_event_at?: string | null;
        signal_built_at?: string | null;
        profile_built_at?: string | null;
        cf_built_at?: string | null;
        pending_event_count: number;
        stale_components: string[];
        components?: {
            signals: {
                state: "current" | "pending" | "stale_version" | "unknown";
                built_at?: string | null;
                source_event_max_timestamp?: string | null;
            };
            profile: {
                state: "current" | "pending" | "stale_version" | "unknown";
                built_at?: string | null;
                source_signal_built_at?: string | null;
            };
            cf: {
                state: "current" | "refresh_required" | "stale_version" | "unavailable";
                built_at?: string | null;
                source_signal_built_at?: string | null;
                input_policy: "current_supported" | "qualified_deliberate";
            };
        };
        next_actions?: string[];
        model_versions: {
            configured: {
                signal_model_version: string;
                profile_model_version: string;
                cf_model_version: string;
                explanation_version: string;
            };
            stored: {
                signal_model_version?: string | null;
                profile_model_version?: string | null;
                cf_model_version?: string | null;
                explanation_version?: string | null;
            };
            stale_version_components: string[];
        };
    };
};

export type DemoStatusResponse = {
    ok: boolean;
    protected_collections: string[];
    counts: Record<string, number>;
    model_versions: {
        signal_model_version: string;
        profile_model_version: string;
        cf_model_version: string;
        explanation_version: string;
    };
    cf_evidence_available: boolean;
    precomputed_cf_note: string;
};

export type EvaluationBaselineSummary = {
    baseline: string;
    evaluated_user_count?: number;
    hit_rate_at_10?: number;
    recall_at_20?: number;
    map_at_20?: number;
    coverage?: number;
    cold_start_exposure_at_20?: number;
    cf_supported_recommendation_count?: number;
    cf_supported_recommendation_rate?: number;
    [key: string]: unknown;
};

export type EvaluationComparison = {
    comparison: string;
    hit_rate_at_10_delta?: number;
    recall_at_20_delta?: number;
    map_at_20_delta?: number;
    cf_supported_count_delta?: number;
    [key: string]: unknown;
};

export type EvaluationRun = {
    id?: string | null;
    run_id: string;
    run_type: string;
    algorithm_version: string;
    ranking_version: string;
    data_label: string;
    synthetic_data: boolean;
    metrics: Record<string, unknown>;
    baseline_summaries: EvaluationBaselineSummary[];
    comparisons: EvaluationComparison[];
    live_state_counts: Record<string, number>;
    caveat: string;
    evaluated_user_count: number;
    artifacts: {
        written: boolean;
        path?: string | null;
    };
    created_at: string;
};

export type EvaluationLatestResponse = {
    ok: boolean;
    empty: boolean;
    latest: EvaluationRun | null;
    message?: string | null;
};

export type EvaluationRunsResponse = {
    ok: boolean;
    empty: boolean;
    runs: EvaluationRun[];
    limit: number;
    message?: string | null;
};

export type EvaluationRunDetailResponse = {
    ok: boolean;
    run: EvaluationRun;
};

export type JobDefinition = {
    job_type: string;
    label: string;
    description: string;
    category: string;
    dry_run_default: boolean;
    write_capable: boolean;
    confirmation_required?: string | null;
    triggerable_from_api: boolean;
    adapter: string;
    command?: string | null;
    current_status: string;
};

export type JobRun = {
    id?: string | null;
    job_run_id: string;
    job_type: string;
    status: string;
    dry_run: boolean;
    write_requested: boolean;
    confirm?: string | null;
    params: Record<string, unknown>;
    summary: Record<string, unknown>;
    error?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
    created_at: string;
    created_by: string;
    source: string;
    version: string;
};

export type JobRegistryResponse = {
    ok: boolean;
    enabled: boolean;
    trigger_api_enabled: boolean;
    jobs: JobDefinition[];
};

export type JobRunsResponse = {
    ok: boolean;
    enabled: boolean;
    empty: boolean;
    runs: JobRun[];
    limit: number;
};

export type JobRunDetailResponse = {
    ok: boolean;
    enabled: boolean;
    run: JobRun | null;
};

export type RunJobPayload = {
    job_type: string;
    dry_run?: boolean;
    write?: boolean;
    params?: Record<string, unknown>;
    confirm?: string | null;
};

export type RunJobResponse = {
    ok: boolean;
    run: JobRun;
};

export type EventPayload = {
    user_id_hash: string;
    session_id: string;
    item_id: string;
    event_type: EventType;
    surface: EventSurface;
    event_id?: string;
    request_id?: string;
    idempotency_key?: string;
    query_text?: string;
    rank_position?: number;
    dwell_time_ms?: number;
    is_synthetic?: boolean;
    client?: {
        component: string;
        device_type: "desktop" | "mobile" | "unknown";
    };
    metadata?: Record<string, unknown>;
};

export type OnboardingOption = {
    id: string;
    label: string;
    count?: number;
};

export type OnboardingSeedItem = {
    item_id: string;
    title: string;
    brand?: string;
    category_id?: string;
    price_bucket?: string;
    price_vnd?: number | null;
    image_url?: string | null;
};

export type OnboardingOptionsResponse = {
    ok: boolean;
    enabled: boolean;
    categories: OnboardingOption[];
    price_buckets: OnboardingOption[];
    intent_chips: OnboardingOption[];
    seed_items: OnboardingSeedItem[];
    source: string;
    message?: string;
    warning?: string;
};

export type OnboardingPreferencesPayload = {
    user_id_hash?: string;
    selected_categories: string[];
    selected_price_buckets: string[];
    selected_intents: string[];
    selected_seed_item_ids: string[];
};

export type OnboardingPreviewResponse = {
    ok: boolean;
    enabled: boolean;
    write_performed: false;
    preview: null | (OnboardingPreferencesPayload & {
        seed_items: OnboardingSeedItem[];
        summary: string;
    });
    explanation?: string;
    message?: string;
};

export type CompleteOnboardingPayload = OnboardingPreferencesPayload & {
    user_id_hash: string;
    session_id: string;
};

export type CompleteOnboardingResponse = {
    ok: boolean;
    enabled: boolean;
    write_performed: boolean;
    user_id_hash: string;
    onboarding: {
        completed: boolean;
        completed_at: string;
        selected_categories: string[];
        selected_price_buckets: string[];
        selected_intents: string[];
        selected_seed_item_ids: string[];
    };
    events_attempted: number;
    events_inserted: number;
    message: string;
};

export type SellerDraftPayload = {
    seller_id?: string;
    title: string;
    description: string;
    brand?: string;
    category_id: string;
    price_vnd?: number | null;
    price_bucket?: string;
    image_url?: string | null;
    attributes?: Record<string, unknown>;
};

export type SellerRetrievalUnitPreview = {
    _id: string;
    item_id: string;
    unit_type: "proposition" | "hype_question";
    raw_text: string;
    text_search?: string;
    source: string;
    category_id: string;
    price_bucket: string;
    seller_confirmed: boolean;
    [key: string]: unknown;
};

export type SellerIndexingPreview = {
    preview_only: boolean;
    catalog_write_performed: boolean;
    valid: boolean;
    validation_errors: string[];
    validation_warnings: string[];
    proposed_item_id: string;
    estimated_retrieval_units: number;
    retrieval_units: SellerRetrievalUnitPreview[];
    embedding_model?: string | null;
    vector_units_generated?: number;
    requires_hype_profile_rebuild?: boolean;
    message?: string;
};

export type SellerDraft = SellerDraftPayload & {
    draft_id: string;
    status: "draft" | "validated" | "previewed" | "approved" | "indexed" | "failed" | "rejected";
    validation_errors: string[];
    validation_warnings: string[];
    proposed_item_id: string;
    indexing_preview?: SellerIndexingPreview | null;
    enrichment?: {
        status?: "none" | "available" | "applied" | "failed" | string;
        latest_request_id?: string | null;
        applied_request_ids?: string[];
        applied_fields?: string[];
        source_urls?: string[];
        [key: string]: unknown;
    } | null;
    source?: Record<string, unknown>;
    created_at: string;
    updated_at: string;
    approved_at?: string | null;
    indexed_at?: string | null;
};

export type SellerDraftsResponse = {
    ok: boolean;
    enabled: boolean;
    drafts: SellerDraft[];
    message?: string;
    required_confirmation?: string;
};

export type SellerDraftResponse = {
    ok: boolean;
    enabled: boolean;
    draft: SellerDraft;
    write_scope?: string[];
    required_confirmation?: string;
};

export type SellerPreviewResponse = {
    ok: boolean;
    enabled: boolean;
    draft_id: string;
    preview: SellerIndexingPreview;
    write_scope: string[];
    catalog_write_performed: boolean;
};

export type SellerApproveIndexResponse = {
    ok: boolean;
    enabled: boolean;
    write_performed: boolean;
    catalog_write_performed: boolean;
    draft_id: string;
    item_id: string;
    inserted_items: number;
    inserted_retrieval_units: number;
    writes: string[];
    forbidden_writes_performed: string[];
    message: string;
};

export type WebEnrichmentSuggestion = {
    value: unknown;
    confidence: number;
    source_urls: string[];
    reason: string;
};

export type WebEnrichmentRequest = {
    id?: string;
    request_id: string;
    draft_id: string;
    seller_id?: string;
    provider: string;
    query: string;
    status: "completed" | "failed" | "applied" | string;
    results: Array<{
        title: string;
        url: string;
        snippet: string;
        score?: number | null;
        source: string;
    }>;
    suggested_fields: Record<string, WebEnrichmentSuggestion>;
    applied_fields: string[];
    created_at: string;
    updated_at: string;
    error?: string | null;
};

export type WebEnrichmentPreviewResponse = {
    ok: boolean;
    enabled: boolean;
    status: "ready" | "disabled" | "provider_not_configured" | string;
    draft_id?: string;
    provider: string;
    provider_configured?: boolean;
    query?: string;
    write_performed?: boolean;
    message?: string;
    required_confirmation?: string;
};

export type WebEnrichmentRequestResponse = {
    ok: boolean;
    enabled: boolean;
    status: string;
    request: WebEnrichmentRequest;
    write_scope: string[];
    catalog_write_performed: boolean;
};

export type WebEnrichmentDetailResponse = {
    ok: boolean;
    request: WebEnrichmentRequest;
};

export type ApplyWebEnrichmentResponse = {
    ok: boolean;
    enabled: boolean;
    status: string;
    request_id: string;
    draft_id: string;
    applied_fields: string[];
    source_urls: string[];
    draft: SellerDraft;
    write_scope: string[];
    catalog_write_performed: boolean;
};

type QueryValue = string | number | boolean | null | undefined;

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");


function adminHeaders(adminToken?: string): Record<string, string> {
    const token = adminToken?.trim();
    return token ? { "X-Admin-Token": token } : {};
}


function accessHeaders(authToken?: string): Record<string, string> {
    const token = authToken?.trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
}


function toQueryString(values: Record<string, QueryValue>) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(values)) {
        if (value === undefined || value === null || value === "") {
            continue;
        }
        params.set(key, String(value));
    }
    const text = params.toString();
    return text ? `?${text}` : "";
}


async function readJson(response: Response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
        return response.json();
    }
    return response.text();
}


async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${path}`, {
        headers: {
            Accept: "application/json",
            ...(init?.body ? { "Content-Type": "application/json" } : {}),
            ...(init?.headers || {}),
        },
        ...init,
    });

    if (!response.ok) {
        const payload = await readJson(response);
        const detail = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
        throw new Error(`API ${response.status}: ${detail}`);
    }

    return readJson(response) as Promise<T>;
}


export function getHealth() {
    return fetchJson<HealthResponse>("/api/health");
}


export function getDemoUsers() {
    return fetchJson<DemoUsersResponse>("/api/users/demo");
}


export function createUser(payload: { displayName: string; allow_personalization: boolean; allow_clickstream_logging: boolean }) {
    return fetchJson<DemoUser>("/api/users", {
        method: "POST",
        body: JSON.stringify({
            display_name: payload.displayName,
            allow_personalization: payload.allow_personalization,
            allow_clickstream_logging: payload.allow_clickstream_logging,
        }),
    });
}


export function getHomepageFeed(params: {
    userIdHash: string;
    sessionId: string;
    topK?: number;
    personalized?: boolean;
}) {
    return fetchJson<HomepageResponse>(
        `/api/feed/home${toQueryString({
            user_id_hash: params.userIdHash,
            session_id: params.sessionId,
            top_k: params.topK ?? 20,
            personalized: params.personalized ?? true,
        })}`,
    );
}


export function searchProducts(params: {
    userIdHash: string;
    sessionId: string;
    query: string;
    topK?: number;
    personalized?: boolean;
}) {
    return fetchJson<SearchResponse>(
        `/api/search${toQueryString({
            user_id_hash: params.userIdHash,
            session_id: params.sessionId,
            q: params.query,
            top_k: params.topK ?? 20,
            personalized: params.personalized ?? true,
        })}`,
    );
}


export function getItemDetail(itemId: string) {
    return fetchJson<ItemDetailResponse>(`/api/items/${encodeURIComponent(itemId)}`);
}


export function getSimilarProducts(params: {
    itemId: string;
    userIdHash: string;
    sessionId: string;
    topK?: number;
}) {
    return fetchJson<SimilarProductsResponse>(
        `/api/items/${encodeURIComponent(params.itemId)}/similar${toQueryString({
            user_id_hash: params.userIdHash,
            session_id: params.sessionId,
            top_k: params.topK ?? 12,
        })}`,
    );
}


export function getDebugUser(userIdHash: string, adminToken?: string) {
    return fetchJson<DebugUserResponse>(`/api/debug/user/${encodeURIComponent(userIdHash)}`, {
        headers: adminHeaders(adminToken),
    });
}

export function getDemoStatus(adminToken?: string) {
    return fetchJson<DemoStatusResponse>("/api/demo/status", {
        headers: adminHeaders(adminToken),
    });
}


export function getOnboardingOptions() {
    return fetchJson<OnboardingOptionsResponse>("/api/onboarding/options");
}


export function previewOnboardingPreferences(payload: OnboardingPreferencesPayload) {
    return fetchJson<OnboardingPreviewResponse>("/api/onboarding/preview", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}


export function completeOnboarding(payload: CompleteOnboardingPayload) {
    return fetchJson<CompleteOnboardingResponse>("/api/onboarding/complete", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}


export function getLatestEvaluationRun() {
    return fetchJson<EvaluationLatestResponse>("/api/evaluation/runs/latest");
}


export function getEvaluationRuns(limit = 10) {
    return fetchJson<EvaluationRunsResponse>(`/api/evaluation/runs${toQueryString({ limit })}`);
}


export function getEvaluationRun(runId: string) {
    return fetchJson<EvaluationRunDetailResponse>(`/api/evaluation/runs/${encodeURIComponent(runId)}`);
}


export function getJobRegistry(adminToken?: string) {
    return fetchJson<JobRegistryResponse>("/api/jobs/registry", {
        headers: adminHeaders(adminToken),
    });
}


export function getJobRuns(params: { limit?: number; adminToken?: string } = {}) {
    return fetchJson<JobRunsResponse>(`/api/jobs/runs${toQueryString({ limit: params.limit ?? 20 })}`, {
        headers: adminHeaders(params.adminToken),
    });
}


export function getJobRun(jobRunId: string, adminToken?: string) {
    return fetchJson<JobRunDetailResponse>(`/api/jobs/runs/${encodeURIComponent(jobRunId)}`, {
        headers: adminHeaders(adminToken),
    });
}


export function runJob(payload: RunJobPayload, adminToken?: string) {
    return fetchJson<RunJobResponse>("/api/jobs/run", {
        method: "POST",
        headers: adminHeaders(adminToken),
        body: JSON.stringify(payload),
    });
}


export function listSellerDrafts(params: { sellerId?: string; limit?: number; authToken?: string } = {}) {
    return fetchJson<SellerDraftsResponse>(
        `/api/seller/drafts${toQueryString({
            seller_id: params.sellerId,
            limit: params.limit ?? 20,
        })}`,
        { headers: accessHeaders(params.authToken) },
    );
}


export function createSellerDraft(payload: SellerDraftPayload, authToken?: string) {
    return fetchJson<SellerDraftResponse>("/api/seller/drafts", {
        method: "POST",
        headers: accessHeaders(authToken),
        body: JSON.stringify(payload),
    });
}


export function getSellerDraft(draftId: string, authToken?: string) {
    return fetchJson<SellerDraftResponse>(`/api/seller/drafts/${encodeURIComponent(draftId)}`, {
        headers: accessHeaders(authToken),
    });
}


export function validateSellerDraft(draftId: string, authToken?: string) {
    return fetchJson<SellerDraftResponse>(`/api/seller/drafts/${encodeURIComponent(draftId)}/validate`, {
        method: "POST",
        headers: accessHeaders(authToken),
    });
}


export function previewSellerDraftIndexing(draftId: string, authToken?: string) {
    return fetchJson<SellerPreviewResponse>(`/api/seller/drafts/${encodeURIComponent(draftId)}/index-preview`, {
        method: "POST",
        headers: accessHeaders(authToken),
    });
}


export function approveSellerDraftIndexing(params: { draftId: string; write: boolean; confirm: string; authToken?: string }) {
    return fetchJson<SellerApproveIndexResponse>(
        `/api/seller/drafts/${encodeURIComponent(params.draftId)}/approve-index${toQueryString({
            write: params.write,
            confirm: params.confirm,
        })}`,
        { method: "POST", headers: accessHeaders(params.authToken) },
    );
}


export function previewSellerDraftEnrichment(draftId: string, authToken?: string) {
    return fetchJson<WebEnrichmentPreviewResponse>(`/api/enrichment/seller-drafts/${encodeURIComponent(draftId)}/preview`, {
        method: "POST",
        headers: accessHeaders(authToken),
    });
}


export function requestSellerDraftEnrichment(draftId: string, authToken?: string) {
    return fetchJson<WebEnrichmentRequestResponse>(`/api/enrichment/seller-drafts/${encodeURIComponent(draftId)}/request`, {
        method: "POST",
        headers: accessHeaders(authToken),
    });
}


export function getEnrichmentRequest(requestId: string, authToken?: string) {
    return fetchJson<WebEnrichmentDetailResponse>(`/api/enrichment/requests/${encodeURIComponent(requestId)}`, {
        headers: accessHeaders(authToken),
    });
}


export function applyEnrichmentRequest(params: { requestId: string; fieldsToApply: string[]; confirm: string; authToken?: string }) {
    return fetchJson<ApplyWebEnrichmentResponse>(
        `/api/enrichment/requests/${encodeURIComponent(params.requestId)}/apply${toQueryString({ confirm: params.confirm })}`,
        {
            method: "POST",
            headers: accessHeaders(params.authToken),
            body: JSON.stringify({ fields_to_apply: params.fieldsToApply }),
        },
    );
}


export function postEvent(payload: EventPayload) {
    return fetchJson<Record<string, unknown>>("/api/events", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}


export function resetDemo(params: { write?: boolean; full?: boolean; confirm?: string; adminToken?: string }) {
    return fetchJson<Record<string, unknown>>(
        `/api/demo/reset${toQueryString({
            write: params.write ?? false,
            full: params.full ?? false,
            confirm: params.confirm,
        })}`,
        { method: "POST", headers: adminHeaders(params.adminToken) },
    );
}


export function seedDemo(params: {
    users?: number;
    requestsPerUser?: number;
    itemsPerRequest?: number;
    seed?: number;
    write?: boolean;
    confirm?: string;
    adminToken?: string;
}) {
    return fetchJson<Record<string, unknown>>(
        `/api/demo/seed${toQueryString({
            users: params.users ?? 40,
            requests_per_user: params.requestsPerUser ?? 3,
            items_per_request: params.itemsPerRequest ?? 10,
            seed: params.seed ?? 42,
            write: params.write ?? false,
            confirm: params.confirm,
        })}`,
        { method: "POST", headers: adminHeaders(params.adminToken) },
    );
}


export function processEvents(params: { limit?: number; rebuildItemStats?: boolean; write?: boolean; confirm?: string; adminToken?: string }) {
    return fetchJson<Record<string, unknown>>(
        `/api/debug/process-events${toQueryString({
            limit: params.limit,
            rebuild_item_stats: params.rebuildItemStats ?? true,
            write: params.write ?? false,
            confirm: params.confirm,
        })}`,
        { method: "POST", headers: adminHeaders(params.adminToken) },
    );
}


export function applyPendingBehavior(params: { maxEvents?: number; rebuildItemStats?: boolean; write?: boolean; confirm?: string; adminToken?: string }) {
    return fetchJson<Record<string, unknown>>(
        `/api/debug/apply-pending-behavior${toQueryString({
            max_events: params.maxEvents ?? 100,
            rebuild_item_stats: params.rebuildItemStats ?? true,
            write: params.write ?? false,
            confirm: params.confirm,
        })}`,
        { method: "POST", headers: adminHeaders(params.adminToken) },
    );
}


export function rebuildProfiles(params: { limitUsers?: number; write?: boolean; confirm?: string; adminToken?: string }) {
    return fetchJson<Record<string, unknown>>(
        `/api/debug/rebuild-profiles${toQueryString({
            limit_users: params.limitUsers,
            write: params.write ?? false,
            confirm: params.confirm,
        })}`,
        { method: "POST", headers: adminHeaders(params.adminToken) },
    );
}


export function rebuildCf(params: {
    limitUsers?: number;
    minSupport?: number;
    maxItemsPerUser?: number;
    topNeighborsPerItem?: number;
    inputPolicy?: "current_supported" | "qualified_deliberate";
    write?: boolean;
    confirm?: string;
    adminToken?: string;
}) {
    return fetchJson<Record<string, unknown>>(
        `/api/debug/rebuild-cf${toQueryString({
            limit_users: params.limitUsers,
            min_support: params.minSupport ?? 2,
            max_items_per_user: params.maxItemsPerUser ?? 30,
            top_neighbors_per_item: params.topNeighborsPerItem ?? 50,
            input_policy: params.inputPolicy,
            write: params.write ?? false,
            confirm: params.confirm,
        })}`,
        { method: "POST", headers: adminHeaders(params.adminToken) },
    );
}


export function formatVnd(value?: number | null) {
    if (typeof value !== "number" || Number.isNaN(value)) {
        return "No price";
    }
    return new Intl.NumberFormat("vi-VN", {
        style: "currency",
        currency: "VND",
        maximumFractionDigits: 0,
    }).format(value);
}
