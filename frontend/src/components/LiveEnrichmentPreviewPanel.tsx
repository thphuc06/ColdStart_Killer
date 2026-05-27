import { useMutation } from "@tanstack/react-query";
import { ExternalLink, Globe2, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";

import { runLiveEnrichmentPreview, type SellerDraftPayload } from "../lib/api";
import { IndexingPreview } from "./IndexingPreview";
import { ErrorState } from "./StateViews";
import { StatusBadge } from "./StatusBadge";


type LiveEnrichmentPreviewPanelProps = {
    accessToken?: string;
};


function scalarText(value: unknown) {
    return typeof value === "string" ? value : JSON.stringify(value);
}


export function LiveEnrichmentPreviewPanel({ accessToken }: LiveEnrichmentPreviewPanelProps) {
    const [title, setTitle] = useState("Samsung Galaxy S25 Ultra 512GB");
    const [brand, setBrand] = useState("Samsung");
    const [categoryId, setCategoryId] = useState("cell_phones");
    const [context, setContext] = useState("");
    const [features, setFeatures] = useState("");
    const [includeIndexingPreview, setIncludeIndexingPreview] = useState(false);
    const hasAccessToken = Boolean(accessToken?.trim());

    const previewMutation = useMutation({
        mutationFn: (payload: SellerDraftPayload) => runLiveEnrichmentPreview(payload, accessToken, includeIndexingPreview),
    });
    const response = previewMutation.data;
    const request = response?.request;

    function runPreview() {
        previewMutation.mutate({
            seller_id: "seller_demo_001",
            title,
            brand,
            category_id: categoryId,
            description: context,
            features: features.split(/\r?\n/).map((feature) => feature.trim()).filter(Boolean),
            price_bucket: "unknown",
            attributes: {},
        });
    }

    return (
        <section className="panel p-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div className="flex items-center gap-2">
                        <Globe2 className="h-4 w-4 text-[var(--sky)]" />
                        <p className="soft-label">Live enrichment quality check</p>
                    </div>
                    <h2 className="mt-2 text-xl font-medium text-[var(--ink-strong)]">Test Tavily + Qwen without saving a draft</h2>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--ink-soft)]">
                        This local-only preview runs the production query planning, web search, and grounded synthesis path.
                        It cannot apply fields, index products, or persist enrichment requests.
                    </p>
                </div>
                <StatusBadge tone="mint">
                    <ShieldCheck className="h-3.5 w-3.5" />
                    zero DB writes
                </StatusBadge>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-3">
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Preview product title
                    <input className="form-input" value={title} onChange={(event) => setTitle(event.target.value)} />
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Preview brand
                    <input className="form-input" value={brand} onChange={(event) => setBrand(event.target.value)} />
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Preview category ID
                    <input className="form-input" value={categoryId} onChange={(event) => setCategoryId(event.target.value)} />
                </label>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Seller context (optional)
                    <textarea
                        className="form-input min-h-24"
                        placeholder="Example: Deep Blue, 256GB, Vietnam version"
                        value={context}
                        onChange={(event) => setContext(event.target.value)}
                    />
                </label>
                <label className="space-y-1 text-sm font-medium text-[var(--ink-strong)]">
                    Seller claims to verify (one per line)
                    <textarea
                        className="form-input min-h-24"
                        placeholder={"Example:\nDual physical SIM\n512GB storage"}
                        value={features}
                        onChange={(event) => setFeatures(event.target.value)}
                    />
                </label>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-3">
                <button
                    className="action-button action-button-primary"
                    disabled={!hasAccessToken || previewMutation.isPending || title.trim().length < 3}
                    type="button"
                    onClick={runPreview}
                >
                    <Sparkles className="h-4 w-4" />
                    {previewMutation.isPending ? "Running Tavily + Qwen..." : "Run live no-write preview"}
                </button>
                {!hasAccessToken ? (
                    <p className="text-xs text-[var(--amber)]">Enter a seller or admin token above before running live provider calls.</p>
                ) : (
                    <p className="text-xs text-[var(--ink-soft)]">Set only `ENABLE_WEB_ENRICHMENT_LIVE_PREVIEW=true` for this test path.</p>
                )}
            </div>
            <label className="mt-4 flex items-start gap-3 rounded-lg bg-[var(--surface-muted)] p-3 text-sm text-[var(--ink-soft)]">
                <input
                    aria-label="Also run propositions + HyPE + embeddings preview"
                    checked={includeIndexingPreview}
                    className="mt-1"
                    type="checkbox"
                    onChange={(event) => setIncludeIndexingPreview(event.target.checked)}
                />
                <span>
                    <span className="font-medium text-[var(--ink-strong)]">Also run propositions + HyPE + embeddings preview</span>
                    <span className="mt-1 block text-xs">
                        Uses the enriched description as the next-stage input. This is slower, but remains in memory with no database writes.
                    </span>
                </span>
            </label>

            {previewMutation.error instanceof Error ? <ErrorState title="Live preview failed" message={previewMutation.error.message} /> : null}
            {response && !response.enabled ? (
                <p className="mt-4 rounded-lg bg-[var(--amber-soft)] p-3 text-sm text-[var(--amber)]">{response.message}</p>
            ) : null}

            {request ? (
                <div className="mt-5 space-y-4">
                    <div className="rounded-lg bg-[var(--mint-soft)] p-3 text-sm text-[var(--mint)]">
                        No database writes: `write_scope` is {response?.write_scope.length ? response.write_scope.join(", ") : "empty"} and
                        `catalog_write_performed` is {String(response?.catalog_write_performed)}.
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge tone={request.status === "completed" ? "mint" : "rose"}>{request.status}</StatusBadge>
                        <span className="text-xs text-[var(--ink-soft)]">Provider: {request.provider}</span>
                    </div>
                    {request.error ? <p className="rounded-lg bg-[var(--amber-soft)] p-3 text-sm text-[var(--amber)]">{request.error}</p> : null}
                    {request.query_plan?.queries?.length ? (
                        <div className="rounded-lg bg-[var(--surface-muted)] p-3 text-sm">
                            <p className="soft-label">Qwen search plan ({request.query_plan.planner_source || "unknown"})</p>
                            {request.query_plan.queries.map((plannedQuery) => (
                                <p key={`${plannedQuery.purpose}:${plannedQuery.query}`} className="mt-2 text-[var(--ink-soft)]">
                                    <span className="font-medium text-[var(--ink-strong)]">{plannedQuery.purpose}:</span> {plannedQuery.query}
                                </p>
                            ))}
                        </div>
                    ) : null}
                    {request.synthesis ? (
                        <div className="rounded-lg border border-[var(--border)] p-3 text-sm">
                            <div className="flex flex-wrap items-center gap-2">
                                <p className="soft-label">Qwen synthesized description</p>
                                <StatusBadge tone={request.synthesis.quality === "high" ? "mint" : "amber"}>
                                    {request.synthesis.quality || "low"}
                                </StatusBadge>
                            </div>
                            {request.synthesis.enriched_description ? (
                                <p className="mt-3 leading-6 text-[var(--ink-soft)]">{request.synthesis.enriched_description}</p>
                            ) : (
                                <p className="mt-3 text-[var(--amber)]">No description was accepted; review evidence and warnings below.</p>
                            )}
                            {(request.synthesis.key_facts || []).map((fact) => (
                                <p key={`${fact.field}:${scalarText(fact.value)}`} className="mt-2 text-xs text-[var(--ink-soft)]">
                                    <span className="font-medium text-[var(--ink-strong)]">{fact.field}:</span> {scalarText(fact.value)}
                                    {" "}({Number(fact.confidence).toFixed(2)})
                                </p>
                            ))}
                            {request.synthesis.unsupported_claims?.length ? (
                                <p className="mt-3 text-xs text-[var(--amber)]">
                                    Unsupported claims: {request.synthesis.unsupported_claims.join("; ")}
                                </p>
                            ) : null}
                            {request.synthesis.warnings?.length ? (
                                <p className="mt-3 text-xs text-[var(--amber)]">
                                    Warnings: {request.synthesis.warnings.join("; ")}
                                </p>
                            ) : null}
                        </div>
                    ) : null}
                    {request.results.length ? (
                        <div className="space-y-2">
                            <p className="soft-label">Selected Tavily evidence</p>
                            {request.results.map((result) => (
                                <a
                                    key={result.url}
                                    className="block rounded-lg bg-[var(--surface-muted)] p-3 text-sm hover:bg-[var(--surface)]"
                                    href={result.url}
                                    rel="noreferrer"
                                    target="_blank"
                                >
                                    <div className="flex items-center gap-2 font-medium text-[var(--ink-strong)]">
                                        <ExternalLink className="h-3.5 w-3.5 text-[var(--sky)]" />
                                        {result.title || result.url}
                                    </div>
                                    <p className="mt-1 break-all text-xs text-[var(--sky)]">{result.url}</p>
                                    <p className="mt-1 text-xs text-[var(--ink-soft)]">{result.snippet}</p>
                                </a>
                            ))}
                        </div>
                    ) : null}
                    {response?.indexing_preview_error ? (
                        <p className="rounded-lg bg-[var(--amber-soft)] p-3 text-sm text-[var(--amber)]">
                            Full indexing preview not available: {response.indexing_preview_error}
                        </p>
                    ) : null}
                    {response?.indexing_preview ? <IndexingPreview preview={response.indexing_preview} /> : null}
                </div>
            ) : null}
        </section>
    );
}
