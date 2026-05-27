import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SellerDraftPage } from "../pages/SellerDraftPage";


const SELLER_ACCESS_TOKEN_STORAGE_KEY = "coldstart-killer/seller-access-token/v1";


function jsonResponse(data: unknown) {
    return Promise.resolve(
        new Response(JSON.stringify(data), {
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


function buildDraft(status: "previewed" | "indexed") {
    return {
        draft_id: "draft_1",
        seller_id: "seller_demo_001",
        title: "Seller Sunscreen",
        description: "Lightweight daily sunscreen for oily skin with comfortable finish.",
        brand: "DemoSun",
        category_id: "all_beauty",
        price_vnd: 299000,
        price_bucket: "100k_300k",
        image_url: null,
        attributes: {},
        status,
        validation_errors: [],
        validation_warnings: [],
        proposed_item_id: "seller_seller_demo_001_seller_sunscreen_demo",
        indexing_preview: {
            preview_only: status !== "indexed",
            catalog_write_performed: status === "indexed",
            valid: true,
            validation_errors: [],
            validation_warnings: [],
            proposed_item_id: "seller_seller_demo_001_seller_sunscreen_demo",
            estimated_retrieval_units: 1,
            retrieval_units: [
                {
                    _id: "unit_1",
                    item_id: "seller_seller_demo_001_seller_sunscreen_demo",
                    unit_type: "proposition",
                    raw_text: "Lightweight daily sunscreen for oily skin with comfortable finish.",
                    source: "seller_submitted",
                    category_id: "all_beauty",
                    price_bucket: "100k_300k",
                    seller_confirmed: status === "indexed",
                },
            ],
            proposition_units_generated: 1,
            hype_units_generated: 1,
            vector_units_generated: 1,
            embedding_model: "BAAI/bge-m3",
            message: "Full preview includes generated propositions, HyPE vectors, and a commit-ready private bundle.",
        },
        enrichment: {
            status: "none",
            latest_request_id: null,
            applied_request_ids: [],
            applied_fields: [],
            source_urls: [],
        },
        source: { type: "seller", seller_confirmed: status === "indexed" },
        created_at: "2026-05-27T10:00:00+00:00",
        updated_at: "2026-05-27T10:00:00+00:00",
        approved_at: status === "indexed" ? "2026-05-27T10:01:00+00:00" : null,
        indexed_at: status === "indexed" ? "2026-05-27T10:01:00+00:00" : null,
    };
}


function renderPage() {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
        },
    });

    return render(
        <QueryClientProvider client={queryClient}>
            <SellerDraftPage />
        </QueryClientProvider>,
    );
}


describe("SellerDraftPage", () => {
    beforeEach(() => {
        window.sessionStorage.clear();
    });

    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
    });

    it("sends bearer auth for approve-index and disables repeat approve after success", async () => {
        window.sessionStorage.setItem(SELLER_ACCESS_TOKEN_STORAGE_KEY, "seller-token");
        let currentStatus: "previewed" | "indexed" = "previewed";
        let approveAuthorization: string | null = null;

        vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
            const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
            if (url.includes("/api/seller/drafts") && !url.includes("/approve-index")) {
                return jsonResponse({
                    ok: true,
                    enabled: true,
                    drafts: [buildDraft(currentStatus)],
                    required_confirmation: "INDEX_SELLER_DRAFT",
                });
            }
            if (url.includes("/approve-index")) {
                approveAuthorization = readHeader(init, "Authorization");
                currentStatus = "indexed";
                return jsonResponse({
                    ok: true,
                    enabled: true,
                    write_performed: true,
                    catalog_write_performed: true,
                    draft_id: "draft_1",
                    item_id: "seller_seller_demo_001_seller_sunscreen_demo",
                    inserted_items: 1,
                    inserted_retrieval_units: 1,
                    writes: ["items", "retrieval_units", "seller_product_drafts"],
                    forbidden_writes_performed: [],
                    message: "Indexed",
                });
            }
            return jsonResponse({ ok: true, enabled: true });
        });

        renderPage();

        expect(await screen.findByText("Seller Sunscreen")).toBeInTheDocument();

        const approveButton = screen.getByRole("button", { name: "Approve and index seller draft" });
        expect(approveButton).toBeDisabled();

        fireEvent.change(screen.getByPlaceholderText("INDEX_SELLER_DRAFT"), {
            target: { value: "INDEX_SELLER_DRAFT" },
        });

        await waitFor(() => expect(approveButton).not.toBeDisabled());

        fireEvent.click(approveButton);

        expect(await screen.findByText("Seller draft indexed additively. No existing catalog document was overwritten.")).toBeInTheDocument();
        expect(approveAuthorization).toBe("Bearer seller-token");
        await waitFor(() => expect(approveButton).toBeDisabled());
    });

    it("does not fetch seller drafts until an access token is provided", async () => {
        const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
            new Response(JSON.stringify({ ok: true, enabled: true, drafts: [], required_confirmation: "INDEX_SELLER_DRAFT" }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        );

        renderPage();

        expect(await screen.findByText("Seller access token required")).toBeInTheDocument();
        expect(fetchMock).not.toHaveBeenCalled();
    });
});
