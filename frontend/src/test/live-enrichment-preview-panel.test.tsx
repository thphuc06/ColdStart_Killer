import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveEnrichmentPreviewPanel } from "../components/LiveEnrichmentPreviewPanel";


function renderPanel() {
    const queryClient = new QueryClient({
        defaultOptions: {
            mutations: { retry: false },
        },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <LiveEnrichmentPreviewPanel accessToken="seller-token" />
        </QueryClientProvider>,
    );
}


function headerValue(init: RequestInit | undefined, name: string) {
    const headers = new Headers(init?.headers);
    return headers.get(name);
}


describe("LiveEnrichmentPreviewPanel", () => {
    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
    });

    it("submits product context to the no-write endpoint and renders synthesis evidence", async () => {
        let requestBody: Record<string, unknown> | null = null;
        let authorization: string | null = null;
        let requestUrl = "";
        vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
            requestUrl = String(input);
            requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
            authorization = headerValue(init, "Authorization");
            return Promise.resolve(
                new Response(
                    JSON.stringify({
                        ok: true,
                        enabled: true,
                        status: "completed",
                        preview_only: true,
                        database_write_performed: false,
                        write_scope: [],
                        catalog_write_performed: false,
                        request: {
                            request_id: "live_preview_1",
                            draft_id: "live_preview_draft",
                            provider: "tavily",
                            query: "Samsung Galaxy S25 Ultra official specs",
                            query_plan: {
                                planner_source: "llm",
                                queries: [{ purpose: "identity", query: "Samsung Galaxy S25 Ultra official specs" }],
                            },
                            synthesis: {
                                quality: "medium",
                                enriched_description: "A sourced description suitable for seller review.",
                                key_facts: [],
                                unsupported_claims: ["Exynos 2500"],
                                warnings: [],
                            },
                            status: "completed",
                            results: [{
                                title: "Samsung official specifications",
                                url: "https://www.samsung.com/example",
                                snippet: "Official product details.",
                                source: "tavily",
                            }],
                            suggested_fields: {},
                            applied_fields: [],
                            created_at: "2026-05-27T00:00:00+00:00",
                            updated_at: "2026-05-27T00:00:00+00:00",
                        },
                        indexing_write_scope: [],
                        indexing_input_source: "enriched_description",
                        indexing_preview: {
                            preview_id: "preview_live",
                            content_hash: "hash",
                            preview_only: true,
                            catalog_write_performed: false,
                            valid: true,
                            validation_errors: [],
                            validation_warnings: [],
                            proposed_item_id: "seller_samsung",
                            estimated_retrieval_units: 7,
                            proposition_units_generated: 6,
                            hype_units_generated: 1,
                            vector_units_generated: 1,
                            embedding_model: "BAAI/bge-m3",
                            message: "In-memory full preview includes generated propositions and HyPE vectors; no preview bundle or catalog data was written.",
                            retrieval_units: [{
                                _id: "prop_1",
                                item_id: "seller_samsung",
                                unit_type: "proposition",
                                raw_text: "512GB storage capacity.",
                                source: "seller_submitted",
                                category_id: "cell_phones",
                                price_bucket: "unknown",
                                seller_confirmed: false,
                            }, ...Array.from({ length: 5 }, (_, index) => ({
                                _id: `prop_${index + 2}`,
                                item_id: "seller_samsung",
                                unit_type: "proposition",
                                raw_text: `Additional proposition ${index + 2}.`,
                                source: "seller_submitted",
                                category_id: "cell_phones",
                                price_bucket: "unknown",
                                seller_confirmed: false,
                            })), {
                                _id: "hype_1",
                                item_id: "seller_samsung",
                                unit_type: "hype_question",
                                raw_text: "Which flagship phone offers 512GB storage?",
                                source: "seller_submitted",
                                category_id: "cell_phones",
                                price_bucket: "unknown",
                                seller_confirmed: false,
                            }],
                        },
                    }),
                    { status: 200, headers: { "Content-Type": "application/json" } },
                ),
            );
        });

        renderPanel();
        fireEvent.change(screen.getByLabelText("Seller context (optional)"), {
            target: { value: "Titanium Blue, 512GB version" },
        });
        fireEvent.change(screen.getByLabelText("Seller claims to verify (one per line)"), {
            target: { value: "Exynos 2500" },
        });
        fireEvent.click(screen.getByLabelText("Also run propositions + HyPE + embeddings preview"));
        fireEvent.click(screen.getByRole("button", { name: "Run live no-write preview" }));

        expect(await screen.findByText("A sourced description suitable for seller review.")).toBeInTheDocument();
        expect(screen.getByText(/Samsung Galaxy S25 Ultra official specs/)).toBeInTheDocument();
        expect(screen.getByText("Samsung official specifications")).toBeInTheDocument();
        expect(screen.getByText(/Unsupported claims: Exynos 2500/)).toBeInTheDocument();
        expect(screen.getByText(/No database writes/)).toBeInTheDocument();
        expect(screen.getByText("512GB storage capacity.")).toBeInTheDocument();
        expect(screen.getByText("Which flagship phone offers 512GB storage?")).toBeInTheDocument();
        expect(screen.getByText("In-memory full preview includes generated propositions and HyPE vectors; no preview bundle or catalog data was written.")).toBeInTheDocument();
        await waitFor(() => expect(authorization).toBe("Bearer seller-token"));
        expect(requestUrl).toContain("include_indexing_preview=true");
        expect(requestBody).toMatchObject({
            title: "Samsung Galaxy S25 Ultra 512GB",
            description: "Titanium Blue, 512GB version",
            features: ["Exynos 2500"],
        });
    });
});
