import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EnrichmentPanel } from "../components/EnrichmentPanel";


function renderPanel(draftId: string | null) {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
        },
    });

    return render(
        <QueryClientProvider client={queryClient}>
            <EnrichmentPanel accessToken="seller-token" draftId={draftId} />
        </QueryClientProvider>,
    );
}


function jsonResponse(data: unknown) {
    return Promise.resolve(
        new Response(JSON.stringify(data), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        }),
    );
}


describe("EnrichmentPanel", () => {
    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
    });

    it("clears stale enrichment request state when the active draft changes", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/enrichment/seller-drafts/draft_a/request")) {
                return jsonResponse({
                    ok: true,
                    enabled: true,
                    status: "completed",
                    request: {
                        request_id: "enrich_a",
                        draft_id: "draft_a",
                        provider: "tavily",
                        query: "demo query",
                        query_plan: {
                            planner_source: "llm",
                            queries: [{ purpose: "identity", query: "Demo product identity" }],
                        },
                        synthesis: {
                            quality: "medium",
                            enriched_description: "Sourced description",
                            key_facts: [],
                            unsupported_claims: [],
                        },
                        status: "completed",
                        results: [],
                        suggested_fields: {
                            description: {
                                value: "Draft A evidence",
                                confidence: 0.72,
                                source_urls: ["https://example.test/enrichment"],
                                reason: "demo",
                            },
                        },
                        applied_fields: [],
                        created_at: "2026-05-27T00:00:00+00:00",
                        updated_at: "2026-05-27T00:00:00+00:00",
                    },
                    write_scope: ["web_enrichment_requests", "seller_product_drafts"],
                    catalog_write_performed: false,
                });
            }
            throw new Error(`Unexpected fetch: ${url}`);
        });

        const view = renderPanel("draft_a");

        fireEvent.click(screen.getByRole("button", { name: "Request enrichment" }));

        expect(await screen.findByText("Suggested fields")).toBeInTheDocument();
        expect(screen.getByText("description")).toBeInTheDocument();
        expect(screen.getByText(/Demo product identity/)).toBeInTheDocument();
        expect(screen.getByText("Sourced description")).toBeInTheDocument();

        view.rerender(
            <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
                <EnrichmentPanel accessToken="seller-token" draftId="draft_b" />
            </QueryClientProvider>,
        );

        await waitFor(() => expect(screen.queryByText("Suggested fields")).not.toBeInTheDocument());
        expect(screen.queryByDisplayValue("Draft A evidence")).not.toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Apply selected suggestions" })).not.toBeInTheDocument();
    });

    it("shows that changed enrichment content requires a new indexing preview", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/enrichment/seller-drafts/draft_a/request")) {
                return jsonResponse({
                    ok: true,
                    enabled: true,
                    status: "completed",
                    request: {
                        request_id: "enrich_a",
                        draft_id: "draft_a",
                        provider: "tavily",
                        query: "demo query",
                        status: "completed",
                        results: [],
                        suggested_fields: {
                            description: {
                                value: "Changed description",
                                confidence: 0.72,
                                source_urls: ["https://example.test/enrichment"],
                                reason: "grounded",
                            },
                        },
                        applied_fields: [],
                        created_at: "2026-05-27T00:00:00+00:00",
                        updated_at: "2026-05-27T00:00:00+00:00",
                    },
                    write_scope: [],
                    catalog_write_performed: false,
                });
            }
            if (url.includes("/api/enrichment/requests/enrich_a/apply")) {
                return jsonResponse({
                    ok: true,
                    enabled: true,
                    status: "applied",
                    request_id: "enrich_a",
                    draft_id: "draft_a",
                    applied_fields: ["description"],
                    source_urls: ["https://example.test/enrichment"],
                    requires_repreview: true,
                    draft: {},
                    write_scope: [],
                    catalog_write_performed: false,
                });
            }
            throw new Error(`Unexpected fetch: ${url}`);
        });

        renderPanel("draft_a");
        fireEvent.click(screen.getByRole("button", { name: "Request enrichment" }));
        await screen.findByText("Suggested fields");
        fireEvent.click(screen.getByRole("checkbox"));
        fireEvent.change(screen.getByPlaceholderText("APPLY_WEB_ENRICHMENT"), {
            target: { value: "APPLY_WEB_ENRICHMENT" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Apply selected suggestions" }));

        expect(await screen.findByText("Content changed; generate indexing preview again before approval.")).toBeInTheDocument();
    });
});
