import { useQuery } from "@tanstack/react-query";
import { Filter, Search as SearchIcon, Send } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useState, useTransition, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ProductCard } from "../components/ProductCard";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";
import { searchProducts, type EventType, type RecommendationCard } from "../lib/api";
import { buildOriginFromCard, trackRecommendationAction } from "../lib/tracking";
import { useImpressionLogger } from "../lib/useImpressionLogger";
import { useExperience } from "../state/experience";


const SEARCH_PLACEHOLDERS = [
    "wireless charger under 300k",
    "moisturizing cream for dry skin",
    "phone case samsung galaxy s22",
];

const categoryHints = [
    { label: "Any category", value: "" },
    { label: "Beauty", value: "beauty" },
    { label: "Phone accessories", value: "phone accessories" },
];

const priceHints = [
    { label: "Any price", value: "" },
    { label: "Under 300k", value: "under 300k" },
    { label: "Under 500k", value: "under 500k" },
    { label: "Budget", value: "budget" },
];


export function SearchPage() {
    const navigate = useNavigate();
    const { userIdHash, sessionId } = useExperience();
    const [searchParams, setSearchParams] = useSearchParams();
    const [isPending, startTransition] = useTransition();
    const currentQuery = searchParams.get("q") ?? "";
    const personalized = searchParams.get("personalized") !== "false";
    const [draftQuery, setDraftQuery] = useState(currentQuery);
    const [categoryHint, setCategoryHint] = useState("");
    const [priceHint, setPriceHint] = useState("");
    const [dismissedIds, setDismissedIds] = useState<string[]>([]);
    const deferredDraft = useDeferredValue(draftQuery);
    const searchPlaceholder = useMemo(() => SEARCH_PLACEHOLDERS[Math.floor(Math.random() * SEARCH_PLACEHOLDERS.length)], []);

    useEffect(() => {
        setDraftQuery(currentQuery);
    }, [currentQuery]);

    const searchQuery = useQuery({
        queryKey: ["search-page", userIdHash, sessionId, currentQuery, personalized],
        queryFn: () => searchProducts({ userIdHash: userIdHash!, sessionId, query: currentQuery, personalized }),
        enabled: Boolean(userIdHash && currentQuery.trim()),
    });

    useImpressionLogger({
        response: searchQuery.data,
        surface: "search",
        userIdHash,
        sessionId,
        queryText: searchQuery.data?.query.raw_query ?? currentQuery,
        component: "search-results-grid",
    });

    useEffect(() => {
        setDismissedIds([]);
    }, [searchQuery.data?.request_id]);

    const visibleItems = useMemo(
        () => searchQuery.data?.items.filter((item) => !dismissedIds.includes(item.item_id)) ?? [],
        [dismissedIds, searchQuery.data?.items],
    );
    const hardFilters = Object.entries(searchQuery.data?.query.hard_filters || {}).filter(
        ([, value]) => value !== null && value !== undefined && value !== "",
    );

    function submitSearch(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        startTransition(() => {
            const parts = [draftQuery.trim(), categoryHint, priceHint].filter(Boolean);
            if (parts.length) {
                setSearchParams({ q: parts.join(" "), personalized: String(personalized) });
            } else {
                setSearchParams({});
            }
        });
    }

    async function handleOpenDetail(card: RecommendationCard) {
        if (!userIdHash) {
            return;
        }
        const origin = buildOriginFromCard(card, { queryText: searchQuery.data?.query.raw_query ?? currentQuery });
        void trackRecommendationAction({
            userIdHash,
            sessionId,
            itemId: card.item_id,
            eventType: "click",
            origin,
            queryText: searchQuery.data?.query.raw_query ?? currentQuery,
            clientComponent: "search-card",
        });
        navigate(`/items/${card.item_id}`, { state: { origin } });
    }

    async function handleCardAction(eventType: EventType, card: RecommendationCard) {
        if (!userIdHash) {
            return;
        }
        await trackRecommendationAction({
            userIdHash,
            sessionId,
            itemId: card.item_id,
            eventType,
            origin: buildOriginFromCard(card, { queryText: searchQuery.data?.query.raw_query ?? currentQuery }),
            queryText: searchQuery.data?.query.raw_query ?? currentQuery,
            clientComponent: "search-card",
        });
        if (eventType === "hide" || eventType === "dislike") {
            setDismissedIds((current) => [...current, card.item_id]);
        }
    }

    function togglePersonalized() {
        const next = personalized ? "false" : "true";
        if (currentQuery.trim()) {
            setSearchParams({ q: currentQuery, personalized: next });
        }
    }

    return (
        <div className="space-y-8">
            <section className="editorial-hero">
                <div className="mb-8 flex flex-wrap items-start justify-between gap-5">
                    <div>
                        <p className="soft-label">Query-first search</p>
                        <h2 className="display-title mt-3">Find products</h2>
                        <p className="mt-4 max-w-2xl text-base leading-7 text-[var(--ink-soft)]">
                            Search runs the existing HyPE + BM25 pipeline first. Profile and CF only rerank relevant candidates.
                        </p>
                    </div>
                    <StatusBadge tone={personalized ? "mint" : "amber"}>
                        {personalized ? "Personalized reranking on" : "Query-only mode"}
                    </StatusBadge>
                </div>

                <form className="grid gap-3 xl:grid-cols-[minmax(0,1fr),180px]" onSubmit={submitSearch}>
                    <div className="relative">
                        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-[var(--ink-muted)]" />
                        <input
                            className="form-input pl-11"
                            placeholder={searchPlaceholder}
                            value={draftQuery}
                            onChange={(event) => setDraftQuery(event.target.value)}
                        />
                    </div>
                    <button className="action-button action-button-primary" type="submit">
                        <Send className="h-4 w-4" />
                        {isPending ? "Searching..." : "Search"}
                    </button>
                </form>

                <div className="mt-4 grid gap-3 md:grid-cols-[1fr,1fr,auto]">
                    <select className="form-select" value={categoryHint} onChange={(event) => setCategoryHint(event.target.value)}>
                        {categoryHints.map((hint) => (
                            <option key={hint.label} value={hint.value}>{hint.label}</option>
                        ))}
                    </select>
                    <select className="form-select" value={priceHint} onChange={(event) => setPriceHint(event.target.value)}>
                        {priceHints.map((hint) => (
                            <option key={hint.label} value={hint.value}>{hint.label}</option>
                        ))}
                    </select>
                    <button className="action-button action-button-secondary" type="button" onClick={togglePersonalized}>
                        <Filter className="h-4 w-4" />
                        {personalized ? "Turn off profile" : "Use profile"}
                    </button>
                </div>
                <p className="mt-3 text-xs leading-5 text-[var(--ink-soft)]">
                    Category and price controls are folded into the query text so backend intent extraction remains the source of truth.
                </p>
            </section>

            {!currentQuery.trim() ? (
                <EmptyState title="Start with a shopping intent" message={`Try "${deferredDraft || searchPlaceholder}" or use the query helpers above.`} />
            ) : searchQuery.isLoading ? (
                <LoadingState title="Searching products" message="Running hybrid retrieval and lightweight personalization." />
            ) : searchQuery.error ? (
                <ErrorState message={String(searchQuery.error)} />
            ) : (
                <>
                    <section className="panel p-5">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                                <p className="soft-label">Search results</p>
                                <h3 className="text-lg font-medium text-[var(--ink-strong)]">
                                    {visibleItems.length} result{visibleItems.length === 1 ? "" : "s"} for "{searchQuery.data?.query.raw_query}"
                                </h3>
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <StatusBadge tone="sky">HyPE + BM25</StatusBadge>
                                {personalized ? <StatusBadge tone="mint">Profile rerank</StatusBadge> : null}
                                <StatusBadge tone="violet">CF evidence when available</StatusBadge>
                            </div>
                        </div>
                    </section>

                    <section className="cream-callout p-5">
                        <p className="soft-label">Query processing</p>
                        <div className="mt-3 grid gap-3 lg:grid-cols-2">
                            <div className="rounded-lg bg-white p-3">
                                <p className="text-xs font-medium text-[var(--ink-muted)]">Detected / translated input</p>
                                <p className="mt-1 text-sm font-medium text-[var(--ink-strong)]">
                                    {searchQuery.data?.query.english_query || searchQuery.data?.query.raw_query}
                                </p>
                                <p className="mt-1 text-xs text-[var(--ink-soft)]">
                                    Language: {searchQuery.data?.query.language_detected || "not reported"} / Type:{" "}
                                    {searchQuery.data?.query.query_type}
                                </p>
                            </div>
                            <div className="rounded-lg bg-white p-3">
                                <p className="text-xs font-medium text-[var(--ink-muted)]">HyPE semantic expansion</p>
                                <p className="mt-1 text-sm text-[var(--ink-soft)]">
                                    {searchQuery.data?.query.hype_search_query_en || "No semantic expansion returned."}
                                </p>
                            </div>
                            <div className="rounded-lg bg-white p-3">
                                <p className="text-xs font-medium text-[var(--ink-muted)]">BM25 keyword query</p>
                                <p className="mt-1 text-sm text-[var(--ink-soft)]">
                                    {searchQuery.data?.query.bm25_search_query_en || "No keyword query returned."}
                                </p>
                            </div>
                            <div className="rounded-lg bg-white p-3">
                                <p className="text-xs font-medium text-[var(--ink-muted)]">Extracted filters</p>
                                <p className="mt-1 text-sm text-[var(--ink-soft)]">
                                    {hardFilters.length
                                        ? hardFilters.map(([key, value]) => `${key}: ${String(value)}`).join(" / ")
                                        : "No explicit filters extracted."}
                                </p>
                            </div>
                        </div>
                    </section>

                    {visibleItems.length ? (
                        <section className="grid-cards">
                            {visibleItems.map((card) => (
                                <ProductCard
                                    key={`${card.request_id}:${card.item_id}`}
                                    card={card}
                                    onOpenDetail={handleOpenDetail}
                                    onAction={handleCardAction}
                                />
                            ))}
                        </section>
                    ) : (
                        <EmptyState title="No results" message="Try a broader intent or remove the price/category hints." />
                    )}
                </>
            )}
        </div>
    );
}
