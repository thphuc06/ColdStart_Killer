import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import App from "../App";
import { ExperienceProvider } from "../state/experience";


const STORAGE_KEY = "coldstart-killer/frontend-state/v1";
const LOGIN_SESSION_KEY = "coldstart-killer/active-login/v1";
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
        stale_components: ["signals", "profile"],
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

    it("renders the debug route with lineage payloads", async () => {
        renderApp("/debug");

        expect(await screen.findByText("Inspect lineage and operate the demo safely")).toBeInTheDocument();
        expect(await screen.findByText("Top signals")).toBeInTheDocument();
        expect(await screen.findByText("Demo Recovery")).toBeInTheDocument();
        expect(await screen.findByText("items")).toBeInTheDocument();
        expect(await screen.findByText("Derived version mismatch")).toBeInTheDocument();
        expect(await screen.findByText("Version rebuild required: signal, profile.")).toBeInTheDocument();
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

    it("applies captured behavior through signals profiles and cf", async () => {
        renderApp("/debug");

        fireEvent.click(await screen.findByRole("button", { name: "Apply captured behavior" }));

        expect(await screen.findByText("Applied behavior response")).toBeInTheDocument();
        expect(screen.getByText(/"stage": "signals"/)).toBeInTheDocument();
        expect(screen.getByText(/"stage": "profiles"/)).toBeInTheDocument();
        expect(screen.getByText(/"stage": "cf"/)).toBeInTheDocument();
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
        fireEvent.click(seedScope.getByRole("button", { name: "Run seed" }));

        expect(await screen.findByText("Seed response")).toBeInTheDocument();
        expect(screen.getByText(/"summary":/)).toBeInTheDocument();
        await waitFor(() => {
            const call = vi
                .mocked(globalThis.fetch)
                .mock.calls.find(([input]) => String(input).includes("/api/demo/seed"));
            expect(call).toBeDefined();
            expect(String(call?.[0])).toContain("write=true");
        });
    });
});
