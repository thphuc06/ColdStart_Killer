export type RecommendationSurface = "home" | "search" | "detail_similar";
export type EventSurface = RecommendationSurface | "cart" | "onboarding" | "debug";
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
    privacy: {
        allow_personalization: boolean;
        allow_clickstream_logging: boolean;
    };
    onboarding: {
        completed: boolean;
        selected_categories: string[];
        selected_price_buckets: string[];
        selected_seed_item_ids: string[];
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
    is_cold_item: boolean;
    interaction_count: number;
    score: number;
    final_score: number;
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
        english_query: string;
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
    quality_score: number;
    cold_start: {
        is_cold_item: boolean;
        interaction_count: number;
    };
    description_enriched: Record<string, unknown>;
};

export type DebugUserResponse = {
    user: Record<string, unknown> | null;
    profile: Record<string, unknown> | null;
    signals: Record<string, unknown>[];
    recent_logs: Record<string, unknown>[];
    recent_events: Record<string, unknown>[];
    cf_edges: Record<string, unknown>[];
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

type QueryValue = string | number | boolean | null | undefined;

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");


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


export function createUser(payload: { allow_personalization: boolean; allow_clickstream_logging: boolean }) {
    return fetchJson<DemoUser>("/api/users", {
        method: "POST",
        body: JSON.stringify(payload),
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


export function getDebugUser(userIdHash: string) {
    return fetchJson<DebugUserResponse>(`/api/debug/user/${encodeURIComponent(userIdHash)}`);
}


export function postEvent(payload: EventPayload) {
    return fetchJson<Record<string, unknown>>("/api/events", {
        method: "POST",
        body: JSON.stringify(payload),
    });
}


export function resetDemo(params: { write?: boolean; full?: boolean; confirm?: string }) {
    return fetchJson<Record<string, unknown>>(
        `/api/demo/reset${toQueryString({
            write: params.write ?? false,
            full: params.full ?? false,
            confirm: params.confirm,
        })}`,
        { method: "POST" },
    );
}


export function seedDemo(params: {
    users?: number;
    requestsPerUser?: number;
    itemsPerRequest?: number;
    seed?: number;
    write?: boolean;
}) {
    return fetchJson<Record<string, unknown>>(
        `/api/demo/seed${toQueryString({
            users: params.users ?? 40,
            requests_per_user: params.requestsPerUser ?? 3,
            items_per_request: params.itemsPerRequest ?? 10,
            seed: params.seed ?? 42,
            write: params.write ?? false,
        })}`,
        { method: "POST" },
    );
}


export function processEvents(params: { limit?: number; rebuildItemStats?: boolean; write?: boolean }) {
    return fetchJson<Record<string, unknown>>(
        `/api/debug/process-events${toQueryString({
            limit: params.limit ?? 500,
            rebuild_item_stats: params.rebuildItemStats ?? true,
            write: params.write ?? false,
        })}`,
        { method: "POST" },
    );
}


export function rebuildProfiles(params: { limitUsers?: number; write?: boolean }) {
    return fetchJson<Record<string, unknown>>(
        `/api/debug/rebuild-profiles${toQueryString({
            limit_users: params.limitUsers,
            write: params.write ?? false,
        })}`,
        { method: "POST" },
    );
}


export function rebuildCf(params: {
    limitUsers?: number;
    minSupport?: number;
    maxItemsPerUser?: number;
    topNeighborsPerItem?: number;
    write?: boolean;
}) {
    return fetchJson<Record<string, unknown>>(
        `/api/debug/rebuild-cf${toQueryString({
            limit_users: params.limitUsers,
            min_support: params.minSupport ?? 2,
            max_items_per_user: params.maxItemsPerUser ?? 30,
            top_neighbors_per_item: params.topNeighborsPerItem ?? 50,
            write: params.write ?? false,
        })}`,
        { method: "POST" },
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