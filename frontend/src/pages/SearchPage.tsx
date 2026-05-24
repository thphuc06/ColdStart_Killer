import { useQuery } from "@tanstack/react-query";
import { Search as SearchIcon, Send } from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useState, useTransition, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { searchProducts, type EventType, type RecommendationCard } from "../lib/api";
import { buildOriginFromCard, trackRecommendationAction } from "../lib/tracking";
import { useImpressionLogger } from "../lib/useImpressionLogger";
import { ProductCard } from "../components/ProductCard";
import { useExperience } from "../state/experience";


const SEARCH_PLACEHOLDERS = [
    "iphone case samsung galaxy s22",
    "gift ideas for skincare lover",
    "fast charging cable under 300k",
];


export function SearchPage() {
    const navigate = useNavigate();
    const { userIdHash, sessionId } = useExperience();
    const [searchParams, setSearchParams] = useSearchParams();
    const [isPending, startTransition] = useTransition();
    const currentQuery = searchParams.get("q") ?? "";
    const [draftQuery, setDraftQuery] = useState(currentQuery);
    const [dismissedIds, setDismissedIds] = useState<string[]>([]);
    const deferredDraft = useDeferredValue(draftQuery);
    const searchPlaceholder = useMemo(() => SEARCH_PLACEHOLDERS[Math.floor(Math.random() * SEARCH_PLACEHOLDERS.length)], []);

    useEffect(() => {
        setDraftQuery(currentQuery);
    }, [currentQuery]);

    const searchQuery = useQuery({
        queryKey: ["search-page", userIdHash, sessionId, currentQuery],
        queryFn: () => searchProducts({ userIdHash: userIdHash!, sessionId, query: currentQuery }),
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

    function submitSearch(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        startTransition(() => {
            if (draftQuery.trim()) {
                setSearchParams({ q: draftQuery.trim() });
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

    return (
        <div className="space-y-5">
            <section className="panel-strong p-5">
                <form className="grid gap-3 lg:grid-cols-[1fr,160px]" onSubmit={submitSearch}>
                    <input
                        className="form-input"
                        placeholder={searchPlaceholder}
                        value={draftQuery}
                        onChange={(event) => setDraftQuery(event.target.value)}
                    />
                    <button className="action-button action-button-primary h-[54px]" type="submit">
                        <Send className="h-4 w-4" />
                        {isPending ? "Searching…" : "Search"}
                    </button>
                </form>
            </section>

            {!currentQuery.trim() ? (
                <section className="panel p-6 text-sm text-[var(--ink-soft)]">
                    <SearchIcon className="mb-2 h-8 w-8 text-[var(--ink-soft)]" />
                    Type something above to find products.
                </section>
            ) : searchQuery.isLoading ? (
                <section className="panel flex items-center gap-3 p-6 text-[var(--ink-soft)]">
                    <Send className="h-5 w-5 animate-spin-slow shrink-0" />
                    Searching for results...
                </section>
            ) : searchQuery.error ? (
                <section className="panel p-6 text-[var(--rose)]">{String(searchQuery.error)}</section>
            ) : (
                <>
                    <section className="panel p-4">
                        <div className="flex flex-wrap gap-2 text-sm text-[var(--ink-soft)]">
                            <span className="chip">{visibleItems.length} result{visibleItems.length === 1 ? '' : 's'} for "{searchQuery.data?.query.raw_query}"</span>
                        </div>
                    </section>

                    <section className="grid-cards">
                        {visibleItems.map((card) => (
                            <ProductCard key={`${card.request_id}:${card.item_id}`} card={card} onOpenDetail={handleOpenDetail} onAction={handleCardAction} />
                        ))}
                    </section>
                </>
            )}

        </div>
    );
}