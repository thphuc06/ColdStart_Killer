import { useMutation } from "@tanstack/react-query";
import { ExternalLink, Globe2, ShieldCheck, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import {
    applyEnrichmentRequest,
    previewSellerDraftEnrichment,
    requestSellerDraftEnrichment,
    type ApplyWebEnrichmentResponse,
    type WebEnrichmentRequest,
    type WebEnrichmentPreviewResponse,
} from "../lib/api";
import { ErrorState } from "./StateViews";
import { StatusBadge } from "./StatusBadge";


type EnrichmentPanelProps = {
    draftId?: string | null;
    onApplied?: (response: ApplyWebEnrichmentResponse) => void;
};


const DEFAULT_CONFIRMATION = "APPLY_WEB_ENRICHMENT";


function stringifyValue(value: unknown) {
    if (typeof value === "string") {
        return value;
    }
    return JSON.stringify(value);
}


export function EnrichmentPanel({ draftId, onApplied }: EnrichmentPanelProps) {
    const [request, setRequest] = useState<WebEnrichmentRequest | null>(null);
    const [preview, setPreview] = useState<WebEnrichmentPreviewResponse | null>(null);
    const [selectedFields, setSelectedFields] = useState<string[]>([]);
    const [confirmText, setConfirmText] = useState("");

    const previewMutation = useMutation({
        mutationFn: (id: string) => previewSellerDraftEnrichment(id),
        onSuccess: (response) => setPreview(response),
    });
    const requestMutation = useMutation({
        mutationFn: (id: string) => requestSellerDraftEnrichment(id),
        onSuccess: (response) => {
            if (response.request) {
                setRequest(response.request);
                setSelectedFields([]);
            }
        },
    });
    const applyMutation = useMutation({
        mutationFn: () =>
            applyEnrichmentRequest({
                requestId: request?.request_id || "",
                fieldsToApply: selectedFields,
                confirm: confirmText,
            }),
        onSuccess: (response) => {
            onApplied?.(response);
        },
    });

    const confirmation = preview?.required_confirmation || DEFAULT_CONFIRMATION;
    const suggestions = useMemo(() => Object.entries(request?.suggested_fields || {}), [request]);
    const canApply = Boolean(request && selectedFields.length > 0 && confirmText === confirmation);

    function toggleField(field: string) {
        setSelectedFields((current) =>
            current.includes(field) ? current.filter((item) => item !== field) : [...current, field],
        );
    }

    if (!draftId) {
        return (
            <section className="panel p-5">
                <p className="soft-label">Web enrichment</p>
                <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">Create a draft first</h3>
                <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                    Enrichment attaches only to staged seller drafts and never writes catalog documents.
                </p>
            </section>
        );
    }

    return (
        <section className="panel p-5">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                    <div className="flex items-center gap-2">
                        <Globe2 className="h-4 w-4 text-[var(--sky)]" />
                        <p className="soft-label">Web enrichment</p>
                    </div>
                    <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">Optional external evidence</h3>
                    <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                        Preview builds the query only. Requesting enrichment stores sourced suggestions on the draft side;
                        applying suggestions never indexes catalog data.
                    </p>
                </div>
                <StatusBadge tone="amber">disabled by default</StatusBadge>
            </div>

            <div className="flex flex-wrap gap-3">
                <button
                    className="action-button action-button-secondary"
                    disabled={previewMutation.isPending}
                    type="button"
                    onClick={() => previewMutation.mutate(draftId)}
                >
                    Preview enrichment query
                </button>
                <button
                    className="action-button action-button-secondary"
                    disabled={requestMutation.isPending}
                    type="button"
                    onClick={() => requestMutation.mutate(draftId)}
                >
                    <Sparkles className="h-4 w-4" />
                    Request enrichment
                </button>
            </div>

            {previewMutation.error instanceof Error ? <ErrorState title="Enrichment preview failed" message={previewMutation.error.message} /> : null}
            {requestMutation.error instanceof Error ? <ErrorState title="Enrichment request failed" message={requestMutation.error.message} /> : null}
            {applyMutation.error instanceof Error ? <ErrorState title="Apply enrichment refused" message={applyMutation.error.message} /> : null}

            {preview ? (
                <div className="mt-4 rounded-lg bg-[var(--surface-muted)] p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge tone={preview.status === "ready" ? "mint" : "amber"}>{preview.status}</StatusBadge>
                        <span className="text-[var(--ink-soft)]">Provider: {preview.provider}</span>
                    </div>
                    {preview.query ? <p className="mt-2 text-[var(--ink-strong)]">{preview.query}</p> : null}
                    {preview.message ? <p className="mt-2 text-[var(--ink-soft)]">{preview.message}</p> : null}
                </div>
            ) : null}

            {request ? (
                <div className="mt-5 space-y-4">
                    <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge tone={request.status === "completed" ? "mint" : request.status === "failed" ? "rose" : "sky"}>
                            {request.status}
                        </StatusBadge>
                        <span className="break-all text-xs text-[var(--ink-soft)]">{request.request_id}</span>
                    </div>
                    {request.error ? <p className="rounded-lg bg-[var(--rose-soft)] p-3 text-sm text-[var(--rose)]">{request.error}</p> : null}
                    <div className="space-y-2">
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

                    {suggestions.length ? (
                        <div className="space-y-3">
                            <p className="soft-label">Suggested fields</p>
                            {suggestions.map(([field, suggestion]) => (
                                <label key={field} className="block rounded-lg border border-[var(--border)] p-3 text-sm">
                                    <div className="flex items-start gap-3">
                                        <input
                                            checked={selectedFields.includes(field)}
                                            className="mt-1"
                                            type="checkbox"
                                            onChange={() => toggleField(field)}
                                        />
                                        <div className="min-w-0">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <span className="font-medium text-[var(--ink-strong)]">{field}</span>
                                                <StatusBadge tone="sky">confidence {Number(suggestion.confidence ?? 0).toFixed(2)}</StatusBadge>
                                            </div>
                                            <p className="mt-2 line-clamp-3 text-[var(--ink-soft)]">{stringifyValue(suggestion.value)}</p>
                                            <p className="mt-2 text-xs text-[var(--ink-soft)]">{suggestion.reason}</p>
                                        </div>
                                    </div>
                                </label>
                            ))}
                            <div className="rounded-lg bg-[var(--amber-soft)] p-3 text-sm text-[var(--amber)]">
                                Applying suggestions updates only this seller draft. It does not write `items`, `retrieval_units`, or index data.
                            </div>
                            <input
                                className="form-input"
                                placeholder={confirmation}
                                value={confirmText}
                                onChange={(event) => setConfirmText(event.target.value)}
                            />
                            <button
                                className="action-button action-button-primary w-full"
                                disabled={!canApply || applyMutation.isPending}
                                type="button"
                                onClick={() => applyMutation.mutate()}
                            >
                                <ShieldCheck className="h-4 w-4" />
                                Apply selected suggestions
                            </button>
                        </div>
                    ) : request.status === "completed" ? (
                        <p className="rounded-lg bg-[var(--amber-soft)] p-3 text-sm text-[var(--amber)]">
                            No suggestions with source URLs were produced.
                        </p>
                    ) : null}
                </div>
            ) : null}
        </section>
    );
}
