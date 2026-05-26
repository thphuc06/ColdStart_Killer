import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, PackagePlus, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EnrichmentPanel } from "../components/EnrichmentPanel";
import { IndexingPreview } from "../components/IndexingPreview";
import { SellerDraftForm } from "../components/SellerDraftForm";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";
import {
    approveSellerDraftIndexing,
    createSellerDraft,
    listSellerDrafts,
    previewSellerDraftIndexing,
    validateSellerDraft,
    type SellerDraft,
    type SellerDraftPayload,
} from "../lib/api";


const CONFIRM_TEXT = "INDEX_SELLER_DRAFT";
const SELLER_ACCESS_TOKEN_STORAGE_KEY = "coldstart-killer/seller-access-token/v1";


export function SellerDraftPage() {
    const queryClient = useQueryClient();
    const [activeDraft, setActiveDraft] = useState<SellerDraft | null>(null);
    const [confirmText, setConfirmText] = useState("");
    const [authToken, setAuthToken] = useState(() => {
        if (typeof window === "undefined") {
            return "";
        }
        return window.sessionStorage.getItem(SELLER_ACCESS_TOKEN_STORAGE_KEY) || "";
    });
    const hasAccessToken = authToken.trim().length > 0;

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        const value = authToken.trim();
        if (value) {
            window.sessionStorage.setItem(SELLER_ACCESS_TOKEN_STORAGE_KEY, value);
            return;
        }
        window.sessionStorage.removeItem(SELLER_ACCESS_TOKEN_STORAGE_KEY);
    }, [authToken]);

    useEffect(() => {
        setActiveDraft(null);
        setConfirmText("");
    }, [authToken]);

    const draftsQuery = useQuery({
        queryKey: ["seller-drafts", authToken],
        queryFn: () => listSellerDrafts({ limit: 12, authToken }),
        enabled: hasAccessToken,
        retry: false,
    });

    const createMutation = useMutation({
        mutationFn: (payload: SellerDraftPayload) => createSellerDraft(payload, authToken),
        onSuccess: (response) => {
            setActiveDraft(response.draft);
            queryClient.invalidateQueries({ queryKey: ["seller-drafts"] });
        },
    });
    const validateMutation = useMutation({
        mutationFn: (draftId: string) => validateSellerDraft(draftId, authToken),
        onSuccess: (response) => {
            setActiveDraft(response.draft);
            queryClient.invalidateQueries({ queryKey: ["seller-drafts"] });
        },
    });
    const previewMutation = useMutation({
        mutationFn: (draftId: string) => previewSellerDraftIndexing(draftId, authToken),
        onSuccess: (response) => {
            setActiveDraft((draft) =>
                draft
                    ? {
                        ...draft,
                        status: "previewed",
                        indexing_preview: response.preview,
                    }
                    : draft,
            );
            queryClient.invalidateQueries({ queryKey: ["seller-drafts"] });
        },
    });
    const approveMutation = useMutation({
        mutationFn: (draft: SellerDraft) =>
            approveSellerDraftIndexing({
                draftId: draft.draft_id,
                write: true,
                confirm: confirmText,
                authToken,
            }),
        onSuccess: () => {
            setActiveDraft((draft) =>
                draft
                    ? {
                        ...draft,
                        status: "indexed",
                        indexing_preview: draft.indexing_preview
                            ? {
                                ...draft.indexing_preview,
                                preview_only: false,
                                catalog_write_performed: true,
                            }
                            : draft.indexing_preview,
                    }
                    : draft,
            );
            setConfirmText("");
            queryClient.invalidateQueries({ queryKey: ["seller-drafts"] });
        },
    });

    const displayedDraft = activeDraft || draftsQuery.data?.drafts?.[0] || null;
    const requiredConfirmation = draftsQuery.data?.required_confirmation || CONFIRM_TEXT;
    const canApprove = useMemo(
        () => Boolean(displayedDraft && confirmText === requiredConfirmation && displayedDraft.status === "previewed"),
        [confirmText, displayedDraft, requiredConfirmation],
    );

    let content: JSX.Element;
    if (!hasAccessToken) {
        content = (
            <EmptyState
                title="Seller access token required"
                message="Enter a seller or admin token above to load seller drafts and use protected seller tools."
            />
        );
    } else if (draftsQuery.isLoading) {
        content = <LoadingState title="Loading seller tools" message="Checking whether seller draft staging is enabled." />;
    } else if (draftsQuery.error instanceof Error) {
        content = <ErrorState title="Seller tools unavailable" message={draftsQuery.error.message} />;
    } else if (!draftsQuery.data?.enabled) {
        content = (
            <EmptyState
                title="Seller draft staging disabled"
                message={draftsQuery.data?.message || "Set ENABLE_SELLER_TOOLS=true only for a reviewed seller-flow test."}
            />
        );
    } else {
        content = (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr),420px]">
                <div className="space-y-5">
                    <SellerDraftForm
                        disabled={!hasAccessToken}
                        isCreating={createMutation.isPending}
                        onCreate={(payload) => createMutation.mutate(payload)}
                    />
                    {createMutation.error instanceof Error ? <ErrorState title="Draft create failed" message={createMutation.error.message} /> : null}
                    {validateMutation.error instanceof Error ? <ErrorState title="Validation failed" message={validateMutation.error.message} /> : null}
                    {previewMutation.error instanceof Error ? <ErrorState title="Preview failed" message={previewMutation.error.message} /> : null}
                    {approveMutation.error instanceof Error ? <ErrorState title="Approve-index refused" message={approveMutation.error.message} /> : null}
                    {approveMutation.isSuccess ? (
                        <div className="feed-refresh-status">
                            <CheckCircle2 className="h-4 w-4 text-[var(--mint)]" />
                            Seller draft indexed additively. No existing catalog document was overwritten.
                        </div>
                    ) : null}
                    <EnrichmentPanel
                        accessToken={authToken}
                        draftId={displayedDraft?.draft_id}
                        onApplied={(response) => {
                            setActiveDraft(response.draft);
                            queryClient.invalidateQueries({ queryKey: ["seller-drafts"] });
                        }}
                    />
                    <IndexingPreview preview={displayedDraft?.indexing_preview} />
                </div>

                <aside className="space-y-4">
                    <section className="panel p-5">
                        <div className="flex items-start gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--sky-soft)] text-[var(--sky)]">
                                <Database className="h-5 w-5" />
                            </div>
                            <div>
                                <p className="soft-label">Active draft</p>
                                <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">
                                    {displayedDraft?.title || "No draft selected"}
                                </h3>
                                {displayedDraft ? (
                                    <p className="mt-2 break-all text-xs text-[var(--ink-soft)]">{displayedDraft.proposed_item_id}</p>
                                ) : null}
                            </div>
                        </div>

                        {displayedDraft ? (
                            <div className="mt-4 space-y-3">
                                <StatusBadge tone={displayedDraft.status === "indexed" ? "mint" : "sky"}>{displayedDraft.status}</StatusBadge>
                                {displayedDraft.validation_errors?.length ? (
                                    <p className="rounded-lg bg-[var(--rose-soft)] p-3 text-sm text-[var(--rose)]">
                                        {displayedDraft.validation_errors.join("; ")}
                                    </p>
                                ) : null}
                                {displayedDraft.validation_warnings?.length ? (
                                    <p className="rounded-lg bg-[var(--amber-soft)] p-3 text-sm text-[var(--amber)]">
                                        {displayedDraft.validation_warnings.join("; ")}
                                    </p>
                                ) : null}
                                <button
                                    className="action-button action-button-secondary w-full"
                                    disabled={validateMutation.isPending || !hasAccessToken}
                                    type="button"
                                    onClick={() => validateMutation.mutate(displayedDraft.draft_id)}
                                >
                                    Validate draft
                                </button>
                                <button
                                    className="action-button action-button-secondary w-full"
                                    disabled={previewMutation.isPending || !hasAccessToken}
                                    type="button"
                                    onClick={() => previewMutation.mutate(displayedDraft.draft_id)}
                                >
                                    Preview indexing
                                </button>
                            </div>
                        ) : null}
                    </section>

                    <section className="panel p-5">
                        <div className="flex items-start gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--rose-soft)] text-[var(--rose)]">
                                <ShieldCheck className="h-5 w-5" />
                            </div>
                            <div>
                                <p className="soft-label">Approve-index</p>
                                <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">Explicit confirmation required</h3>
                                <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                                    This is the only UI action that requests catalog writes. It is disabled until the preview exists
                                    and the confirmation text matches.
                                </p>
                            </div>
                        </div>
                        <input
                            className="form-input mt-4"
                            placeholder={requiredConfirmation}
                            value={confirmText}
                            onChange={(event) => setConfirmText(event.target.value)}
                        />
                        <button
                            className="action-button action-button-primary mt-3 w-full"
                            disabled={!canApprove || approveMutation.isPending || !displayedDraft || !hasAccessToken}
                            type="button"
                            onClick={() => displayedDraft && approveMutation.mutate(displayedDraft)}
                        >
                            Approve and index seller draft
                        </button>
                    </section>
                </aside>
            </div>
        );
    }

    return (
        <section className="space-y-5">
            <header className="panel p-6">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <PackagePlus className="h-5 w-5 text-[var(--sky)]" />
                            <p className="soft-label">Seller add product</p>
                        </div>
                        <h1 className="mt-3 text-2xl font-medium text-[var(--ink-strong)]">Draft, preview, then explicitly index</h1>
                        <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--ink-soft)]">
                            Draft creation is staged. Preview does not write catalog data. Approve-index requires `write=true`
                            plus the exact confirmation string.
                        </p>
                    </div>
                    <StatusBadge tone="rose">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        catalog boundary
                    </StatusBadge>
                </div>
            </header>
            <section className="panel p-5">
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr),320px] lg:items-end">
                    <div>
                        <p className="soft-label">Protected seller access</p>
                        <h3 className="mt-2 text-lg font-medium text-[var(--ink-strong)]">Load seller or admin token</h3>
                        <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                            Seller draft list, validate, preview, enrichment, and approve-index now use Bearer auth. Enter a
                            seller token or an admin token to unlock this page when seller tools are enabled.
                        </p>
                    </div>
                    <div className="space-y-3">
                        <input
                            className="form-input"
                            type="password"
                            placeholder="Enter seller or admin token"
                            value={authToken}
                            onChange={(event) => setAuthToken(event.target.value)}
                        />
                        <StatusBadge tone={hasAccessToken ? "mint" : "amber"}>
                            {hasAccessToken ? "Access token loaded" : "Access token required when seller tools are enabled"}
                        </StatusBadge>
                    </div>
                </div>
            </section>

            {content}
        </section>
    );
}
