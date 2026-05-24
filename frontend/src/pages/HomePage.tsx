import { useQuery } from "@tanstack/react-query";
import { RefreshCcw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getHomepageFeed, type EventType, type RecommendationCard } from "../lib/api";
import { buildOriginFromCard, trackRecommendationAction } from "../lib/tracking";
import { useImpressionLogger } from "../lib/useImpressionLogger";
import { ProductCard } from "../components/ProductCard";
import { useExperience } from "../state/experience";


export function HomePage() {
    const navigate = useNavigate();
    const { userIdHash, sessionId } = useExperience();
    const [dismissedIds, setDismissedIds] = useState<string[]>([]);
    const [feedback, setFeedback] = useState<string | null>(null);

    useEffect(() => {
        if (!feedback) return;
        const t = window.setTimeout(() => setFeedback(null), 3500);
        return () => window.clearTimeout(t);
    }, [feedback]);

    const homepageQuery = useQuery({
        queryKey: ["homepage-feed", userIdHash, sessionId],
        queryFn: () => getHomepageFeed({ userIdHash: userIdHash!, sessionId }),
        enabled: Boolean(userIdHash),
    });

    useImpressionLogger({
        response: homepageQuery.data,
        surface: "home",
        userIdHash,
        sessionId,
        component: "homepage-grid",
    });

    useEffect(() => {
        setDismissedIds([]);
    }, [homepageQuery.data?.request_id]);

    const visibleItems = useMemo(
        () => homepageQuery.data?.items.filter((item) => !dismissedIds.includes(item.item_id)) ?? [],
        [homepageQuery.data?.items, dismissedIds],
    );

    async function handleOpenDetail(card: RecommendationCard) {
        if (!userIdHash) {
            return;
        }
        void trackRecommendationAction({
            userIdHash,
            sessionId,
            itemId: card.item_id,
            eventType: "click",
            origin: buildOriginFromCard(card),
            clientComponent: "homepage-card",
        });
        navigate(`/items/${card.item_id}`, {
            state: { origin: buildOriginFromCard(card) },
        });
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
            origin: buildOriginFromCard(card),
            clientComponent: "homepage-card",
        });
        if (eventType === "hide" || eventType === "dislike") {
            setDismissedIds((current) => [...current, card.item_id]);
        }
        setFeedback(`${eventType.replace(/_/g, " ")} logged for ${card.title}`);
    }

    if (!userIdHash) {
        return (
            <section className="panel-strong p-8">
                <h2 className="text-2xl font-semibold text-[var(--ink-strong)]">Pick a profile first</h2>
                <p className="mt-2 max-w-2xl text-[var(--ink-soft)]">
                    Select or create a shopper profile in the left panel to see your personalized feed.
                </p>
            </section>
        );
    }

    return (
        <div className="space-y-5">
            <section className="panel-strong overflow-hidden p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <Sparkles className="h-5 w-5 text-[var(--mint)]" />
                        <div>
                            <h2 className="text-xl font-semibold text-[var(--ink-strong)]">Picks for you</h2>
                            <p className="text-sm text-[var(--ink-soft)]">{visibleItems.length} items</p>
                        </div>
                    </div>
                    <button className="action-button action-button-primary" onClick={() => homepageQuery.refetch()}>
                        <RefreshCcw className="h-4 w-4" />
                        Refresh
                    </button>
                </div>
            </section>

            {feedback ? (
                <div className="panel border border-[rgba(15,118,110,0.24)] bg-[rgba(15,118,110,0.08)] p-4 text-sm text-[var(--mint)]">
                    {feedback}
                </div>
            ) : null}

            {homepageQuery.isLoading ? (
                <section className="panel flex items-center gap-3 p-6 text-[var(--ink-soft)]">
                    <RefreshCcw className="h-5 w-5 animate-spin-slow shrink-0" />
                    Loading your picks...
                </section>
            ) : homepageQuery.error ? (
                <section className="panel p-6 text-[var(--rose)]">{String(homepageQuery.error)}</section>
            ) : (
                <section className="grid-cards">
                    {visibleItems.map((card) => (
                        <ProductCard key={`${card.request_id}:${card.item_id}`} card={card} onOpenDetail={handleOpenDetail} onAction={handleCardAction} />
                    ))}
                    {!visibleItems.length ? (
                        <div className="panel p-6 text-[var(--ink-soft)]">
                            No more items to show. Click Refresh to load a new feed.
                        </div>
                    ) : null}
                </section>
            )}


        </div>
    );
}