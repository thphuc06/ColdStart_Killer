import { ArrowRight, Eye, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { formatVnd, type OnboardingOptionsResponse, type OnboardingPreferencesPayload, type OnboardingPreviewResponse } from "../lib/api";
import { ProductImage } from "./ProductImage";
import { PreferenceChips } from "./PreferenceChips";
import { StatusBadge } from "./StatusBadge";


type OnboardingWizardProps = {
    options: OnboardingOptionsResponse;
    preview?: OnboardingPreviewResponse | null;
    isPreviewing: boolean;
    isCompleting: boolean;
    onPreview: (payload: OnboardingPreferencesPayload) => void;
    onComplete: (payload: OnboardingPreferencesPayload) => void;
    onSkip: () => void;
};


export function OnboardingWizard({
    options,
    preview,
    isPreviewing,
    isCompleting,
    onPreview,
    onComplete,
    onSkip,
}: OnboardingWizardProps) {
    const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
    const [selectedPriceBuckets, setSelectedPriceBuckets] = useState<string[]>([]);
    const [selectedIntents, setSelectedIntents] = useState<string[]>([]);
    const [selectedSeedItemIds, setSelectedSeedItemIds] = useState<string[]>([]);

    const payload = useMemo<OnboardingPreferencesPayload>(
        () => ({
            selected_categories: selectedCategories,
            selected_price_buckets: selectedPriceBuckets,
            selected_intents: selectedIntents,
            selected_seed_item_ids: selectedSeedItemIds,
        }),
        [selectedCategories, selectedIntents, selectedPriceBuckets, selectedSeedItemIds],
    );
    const selectedSeedSet = new Set(selectedSeedItemIds);
    const hasSelection =
        selectedCategories.length + selectedPriceBuckets.length + selectedIntents.length + selectedSeedItemIds.length > 0;

    function toggleSeedItem(itemId: string) {
        if (selectedSeedSet.has(itemId)) {
            setSelectedSeedItemIds(selectedSeedItemIds.filter((value) => value !== itemId));
            return;
        }
        setSelectedSeedItemIds([...selectedSeedItemIds, itemId]);
    }

    return (
        <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr),360px]">
            <div className="panel p-6">
                <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <p className="soft-label">Preference onboarding</p>
                        <h2 className="mt-2 text-2xl font-medium text-[var(--ink-strong)]">Tune your first recommendations</h2>
                        <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">
                            Preview does not save yet. Completing onboarding stores your choices and emits weak onboarding
                            behavior signals; profiles are still derived by the existing behavior pipeline.
                        </p>
                    </div>
                    <StatusBadge tone={options.source === "catalog_snapshot" ? "mint" : "amber"}>
                        {options.source === "catalog_snapshot" ? "Catalog-backed options" : "Fallback options"}
                    </StatusBadge>
                </div>

                <div className="space-y-6">
                    <PreferenceChips
                        label="Categories"
                        options={options.categories}
                        selected={selectedCategories}
                        onChange={setSelectedCategories}
                    />
                    <PreferenceChips
                        label="Price comfort"
                        options={options.price_buckets}
                        selected={selectedPriceBuckets}
                        onChange={setSelectedPriceBuckets}
                    />
                    <PreferenceChips
                        label="Shopping intent"
                        options={options.intent_chips}
                        selected={selectedIntents}
                        onChange={setSelectedIntents}
                    />

                    <section>
                        <div className="mb-3 flex items-center justify-between gap-3">
                            <h3 className="text-sm font-medium text-[var(--ink-strong)]">Optional seed items</h3>
                            <span className="text-xs text-[var(--ink-soft)]">{selectedSeedItemIds.length} selected</span>
                        </div>
                        {options.seed_items.length ? (
                            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                                {options.seed_items.map((item) => {
                                    const isSelected = selectedSeedSet.has(item.item_id);
                                    return (
                                        <button
                                            key={item.item_id}
                                            aria-pressed={isSelected}
                                            className={`product-card text-left transition ${isSelected ? "border-[var(--sky)] ring-2 ring-[rgba(27,97,201,0.16)]" : ""}`}
                                            type="button"
                                            onClick={() => toggleSeedItem(item.item_id)}
                                        >
                                            <div className="product-card-image">
                                                <ProductImage alt={item.title} src={item.image_url} />
                                            </div>
                                            <div className="p-3">
                                                <p className="product-title text-sm">{item.title}</p>
                                                <p className="mt-2 text-xs text-[var(--ink-soft)]">
                                                    {item.brand || "Unknown brand"} / {item.category_id || "uncategorized"}
                                                </p>
                                                <div className="mt-3 flex flex-wrap items-center gap-2">
                                                    <StatusBadge tone={isSelected ? "sky" : "neutral"}>
                                                        {isSelected ? "Selected" : "Seed signal"}
                                                    </StatusBadge>
                                                    <span className="text-xs text-[var(--ink-soft)]">{formatVnd(item.price_vnd)}</span>
                                                </div>
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                        ) : (
                            <div className="rounded-lg border border-dashed border-[var(--line-soft)] p-4 text-sm text-[var(--ink-soft)]">
                                No seed items available from the current catalog snapshot. You can still save category and intent
                                preferences without creating item events.
                            </div>
                        )}
                    </section>
                </div>
            </div>

            <aside className="space-y-4">
                <div className="panel p-5">
                    <div className="flex items-start gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--sky-soft)] text-[var(--sky)]">
                            <Eye className="h-5 w-5" />
                        </div>
                        <div>
                            <p className="soft-label">Read-only preview</p>
                            <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">No profile is seeded here</h3>
                            <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                                Complete onboarding writes only `users.onboarding` plus onboarding events for selected real seed
                                items.
                            </p>
                        </div>
                    </div>

                    <button
                        className="action-button action-button-secondary mt-5 w-full"
                        disabled={isPreviewing}
                        type="button"
                        onClick={() => onPreview(payload)}
                    >
                        <Eye className="h-4 w-4" />
                        {isPreviewing ? "Previewing..." : "Preview preferences"}
                    </button>

                    {preview?.preview ? (
                        <div className="mt-4 rounded-lg bg-[var(--surface-muted)] p-4 text-sm">
                            <p className="font-medium text-[var(--ink-strong)]">{preview.preview.summary}</p>
                            <p className="mt-2 text-[var(--ink-soft)]">{preview.explanation}</p>
                        </div>
                    ) : null}
                    {options.warning ? <p className="mt-4 text-xs leading-5 text-[var(--amber)]">{options.warning}</p> : null}
                </div>

                <div className="panel p-5">
                    <div className="flex items-start gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--mint-soft)] text-[var(--mint)]">
                            <Sparkles className="h-5 w-5" />
                        </div>
                        <div>
                            <p className="soft-label">Complete onboarding</p>
                            <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">Create weak initial signals</h3>
                            <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                                After completion, run the existing behavior processing flow to turn onboarding events into
                                signals and profiles.
                            </p>
                        </div>
                    </div>

                    <button
                        className="action-button action-button-primary mt-5 w-full"
                        disabled={!hasSelection || isCompleting}
                        type="button"
                        onClick={() => onComplete(payload)}
                    >
                        <ArrowRight className="h-4 w-4" />
                        {isCompleting ? "Saving..." : "Complete onboarding"}
                    </button>
                    <button className="action-button action-button-ghost mt-3 w-full" type="button" onClick={onSkip}>
                        Skip onboarding
                    </button>
                </div>
            </aside>
        </section>
    );
}
