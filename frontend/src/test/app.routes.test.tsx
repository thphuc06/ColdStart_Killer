import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { ExperienceProvider } from "../state/experience";


const STORAGE_KEY = "coldstart-killer/frontend-state/v1";
const LOGIN_SESSION_KEY = "coldstart-killer/active-login/v1";

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
    items: [baseRecommendationItem],
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
};

const demoStatusResponse = {
    ok: true,
    protected_collections: ["items", "retrieval_units"],
    counts: {
        recommendation_logs: 12,
        clickstream_events: 10,
        user_item_signals: 8,
        user_profiles: 4,
        item_item_cf_edges: 6,
    },
    cf_evidence_available: true,
    precomputed_cf_note: "Existing CF edges may come from seeded/precomputed synthetic behavior.",
};

function jsonResponse(payload: unknown) {
    return Promise.resolve(
        new Response(JSON.stringify(payload), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        }),
    );
}


function installFetchMock() {
    let createdUser: Record<string, unknown> | null = null;

    return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
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
                },
            };
            return jsonResponse(createdUser);
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
        if (url.includes("/api/debug/process-events")) {
            return jsonResponse({ ok: true, stage: "signals" });
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
        vi.restoreAllMocks();
        cleanup();
    });

    it("renders the homepage feed cards", async () => {
        renderApp("/");

        expect(await screen.findByText("Test Charger Block")).toBeInTheDocument();
        expect(screen.getByText("Recommended for you")).toBeInTheDocument();
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
        fireEvent.click(screen.getByRole("button", { name: "Create account and enter" }));

        await waitFor(() => {
            const call = vi
                .mocked(globalThis.fetch)
                .mock.calls.find(([input]) => String(input).endsWith("/api/users"));
            expect(call).toBeDefined();
            expect(String(call?.[1]?.body)).toContain('"display_name":"Phuc demo shopper"');
        });
        expect(await screen.findByText("Phuc demo shopper")).toBeInTheDocument();
        expect(screen.getByText("Personal live-learning account")).toBeInTheDocument();
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

    it("renders the item detail route with similar products", async () => {
        renderApp("/items/item_1");

        expect(await screen.findByText("Detail Product Title")).toBeInTheDocument();
        expect(await screen.findByText("Compact charging product description.")).toBeInTheDocument();
        expect(screen.getByText(/Fast charging/)).toBeInTheDocument();
        expect(await screen.findByText("Similar Product Title")).toBeInTheDocument();
    });

    it("renders the debug route with lineage payloads", async () => {
        renderApp("/debug");

        expect(await screen.findByText("Inspect lineage and operate the demo safely")).toBeInTheDocument();
        expect(await screen.findByText("Top signals")).toBeInTheDocument();
        expect(await screen.findByText("Demo Recovery")).toBeInTheDocument();
        expect(await screen.findByText("items")).toBeInTheDocument();
    });

    it("applies captured behavior through signals profiles and cf", async () => {
        renderApp("/debug");

        fireEvent.click(await screen.findByRole("button", { name: "Apply captured behavior" }));

        expect(await screen.findByText("Applied behavior response")).toBeInTheDocument();
        expect(screen.getByText(/"stage": "signals"/)).toBeInTheDocument();
        expect(screen.getByText(/"stage": "profiles"/)).toBeInTheDocument();
        expect(screen.getByText(/"stage": "cf"/)).toBeInTheDocument();
    });
});
