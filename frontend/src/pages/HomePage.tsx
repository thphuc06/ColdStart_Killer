import { useQuery } from "@tanstack/react-query";
import { RefreshCcw, ShieldCheck, Sparkles, UsersRound, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { ProductCard } from "../components/ProductCard";
import { StatusBadge } from "../components/StatusBadge";
import { getHomepageFeed, type EventType, type RecommendationCard } from "../lib/api";
import { buildOriginFromCard, trackRecommendationAction } from "../lib/tracking";
import { useImpressionLogger } from "../lib/useImpressionLogger";
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

    const cfCount = visibleItems.filter((item) => item.attribution.cf_evidence || item.score_breakdown.item_item_cf_score > 0).length;
    const profileCount = visibleItems.filter((item) => item.score_breakdown.profile_score > 0).length;
    const coldCount = visibleItems.filter((item) => item.is_cold_item).length;

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
            <EmptyState
                title="Pick a shopper profile"
                message="Choose a profile from the right panel to activate the personalized homepage feed."
            />
        );
    }

    return (
        <div className="space-y-5">
            <section className="page-hero p-6 lg:p-8">
                <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr),360px] lg:items-end">
                    <div>
                        <div className="mb-4 flex flex-wrap gap-2">
                            <StatusBadge tone="mint">
                                <ShieldCheck className="h-3.5 w-3.5" />
                                Profile-backed
                            </StatusBadge>
                            <StatusBadge tone="sky">Vector Search enabled</StatusBadge>
                            <StatusBadge tone="violet">CF enabled</StatusBadge>
                        </div>
                        <p className="soft-label">Personalized marketplace feed</p>
                        <h2 className="mt-2 text-3xl font-black tracking-tight text-[var(--ink-strong)] lg:text-4xl">
                            Recommended for you
                        </h2>
                        <p className="mt-3 max-w-3xl text-base leading-7 text-[var(--ink-soft)]">
                            A query-free shopping feed blending behavior profiles, item-item collaborative filtering,
                            HyPE semantic retrieval, and cold-start exploration.
                        </p>
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                        <div className="metric-block">
                            <p className="soft-label">Items</p>
                            <p className="metric-value">{visibleItems.length}</p>
                        </div>
                        <div className="metric-block">
                            <p className="soft-label">CF</p>
                            <p className="metric-value">{cfCount}</p>
                        </div>
                        <div className="metric-block">
                            <p className="soft-label">Cold</p>
                            <p className="metric-value">{coldCount}</p>
                        </div>
                    </div>
                </div>
            </section>

            <section className="panel p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap gap-2">
                        <StatusBadge tone="mint">
                            <UsersRound className="h-3.5 w-3.5" />
                            {profileCount} profile matches
                        </StatusBadge>
                        <StatusBadge tone="violet">{cfCount} CF-supported items</StatusBadge>
                        <StatusBadge tone="amber">{coldCount} cold-start exposures</StatusBadge>
                    </div>
                    <button className="action-button action-button-secondary" onClick={() => homepageQuery.refetch()}>
                        <RefreshCcw className="h-4 w-4" />
                        Refresh feed
                    </button>
                </div>
            </section>

            {feedback ? (
                <div className="rounded-lg border border-[rgba(15,118,110,0.18)] bg-[var(--mint-soft)] p-3 text-sm font-semibold text-[var(--mint)]">
                    {feedback}
                </div>
            ) : null}

            {homepageQuery.isLoading ? (
                <LoadingState title="Building your feed" message="Combining profile, CF, semantic and cold-start signals." />
            ) : homepageQuery.error ? (
                <ErrorState message={String(homepageQuery.error)} />
            ) : visibleItems.length ? (
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
                <EmptyState
                    title="No more recommendations in this feed"
                    message="Refresh the feed or switch profile to inspect another personalized result set."
                    action={
                        <button className="action-button action-button-primary" onClick={() => homepageQuery.refetch()}>
                            <Zap className="h-4 w-4" />
                            Refresh recommendations
                        </button>
                    }
                />
            )}
        </div>
    );
}
