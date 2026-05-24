import { useQuery } from "@tanstack/react-query";
import { BookmarkPlus, CreditCard, ShieldAlert, ShoppingBag, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { getItemDetail, getSimilarProducts, formatVnd, type EventType, type RecommendationCard } from "../lib/api";
import { buildOriginFromCard, trackRecommendationAction, type RecommendationOrigin } from "../lib/tracking";
import { useImpressionLogger } from "../lib/useImpressionLogger";
import { ProductCard } from "../components/ProductCard";
import { useExperience } from "../state/experience";


type ItemLocationState = {
    origin?: RecommendationOrigin;
};


export function ItemDetailPage() {
    const navigate = useNavigate();
    const location = useLocation();
    const { itemId = "" } = useParams();
    const { userIdHash, sessionId } = useExperience();
    const [detailFeedback, setDetailFeedback] = useState<string | null>(null);

    useEffect(() => {
        if (!detailFeedback) return;
        const t = window.setTimeout(() => setDetailFeedback(null), 3500);
        return () => window.clearTimeout(t);
    }, [detailFeedback]);

    const locationState = (location.state as ItemLocationState | null) ?? null;
    const origin = locationState?.origin;

    const itemQuery = useQuery({
        queryKey: ["item-detail", itemId],
        queryFn: () => getItemDetail(itemId),
        enabled: Boolean(itemId),
    });

    const similarQuery = useQuery({
        queryKey: ["item-similar", itemId, userIdHash, sessionId],
        queryFn: () => getSimilarProducts({ itemId, userIdHash: userIdHash!, sessionId }),
        enabled: Boolean(itemId && userIdHash),
    });

    useImpressionLogger({
        response: similarQuery.data,
        surface: "detail_similar",
        userIdHash,
        sessionId,
        component: "similar-products-rail",
        metadata: { source_item_id: itemId },
    });

    const originKey = useMemo(
        () => (origin ? `${origin.surface}:${origin.requestId}:${origin.rankPosition ?? "na"}:${origin.sourceItemId ?? "-"}` : null),
        [origin],
    );

    useEffect(() => {
        if (!origin || !userIdHash || !itemId) {
            return;
        }

        const startedAt = performance.now();
        return () => {
            const dwell = Math.max(500, Math.round(performance.now() - startedAt));
            void trackRecommendationAction({
                userIdHash,
                sessionId,
                itemId,
                eventType: "view_detail",
                origin,
                queryText: origin.queryText,
                dwellTimeMs: dwell,
                clientComponent: "product-detail",
            });
        };
    }, [itemId, origin, originKey, sessionId, userIdHash]);

    async function handleOriginAction(eventType: EventType) {
        if (!origin || !userIdHash || !itemId) {
            setDetailFeedback("No recommendation origin is attached to this detail view, so the event was kept local only.");
            return;
        }

        await trackRecommendationAction({
            userIdHash,
            sessionId,
            itemId,
            eventType,
            origin,
            queryText: origin.queryText,
            clientComponent: "product-detail",
        });
        setDetailFeedback(`${eventType.replace(/_/g, " ")} logged against the originating ${origin.surface} surface.`);
    }

    async function handleOpenSimilar(card: RecommendationCard) {
        if (!userIdHash) {
            return;
        }
        const nextOrigin = buildOriginFromCard(card, { sourceItemId: itemId });
        void trackRecommendationAction({
            userIdHash,
            sessionId,
            itemId: card.item_id,
            eventType: "click",
            origin: nextOrigin,
            clientComponent: "similar-products-rail",
        });
        navigate(`/items/${card.item_id}`, { state: { origin: nextOrigin } });
    }

    async function handleSimilarAction(eventType: EventType, card: RecommendationCard) {
        if (!userIdHash) {
            return;
        }
        await trackRecommendationAction({
            userIdHash,
            sessionId,
            itemId: card.item_id,
            eventType,
            origin: buildOriginFromCard(card, { sourceItemId: itemId }),
            clientComponent: "similar-products-rail",
        });
    }

    return (
        <div className="space-y-5">
            {itemQuery.isLoading ? (
                <section className="panel p-6 text-[var(--ink-soft)]">Loading item detail...</section>
            ) : itemQuery.error ? (
                <section className="panel p-6 text-[var(--rose)]">{String(itemQuery.error)}</section>
            ) : itemQuery.data ? (
                <section className="panel-strong overflow-hidden p-6">
                    <div className="grid gap-6 lg:grid-cols-[260px,1fr]">
                        <div className="overflow-hidden rounded-[28px] bg-gradient-to-br from-slate-100 via-white to-teal-50">
                            {itemQuery.data.image_url ? (
                                <img className="h-full min-h-[280px] w-full object-cover" src={itemQuery.data.image_url} alt={itemQuery.data.title} />
                            ) : (
                                <div className="flex min-h-[280px] items-center justify-center text-[var(--ink-soft)]">
                                    <Sparkles className="h-8 w-8" />
                                </div>
                            )}
                        </div>

                        <div className="space-y-5">
                            <div className="space-y-3">
                                <div className="flex flex-wrap gap-2">
                                    <span className="chip chip-primary">{itemQuery.data.category_id}</span>
                                    <span className="chip chip-warm">{itemQuery.data.price_bucket}</span>
                                    <span className="chip">quality {itemQuery.data.quality_score.toFixed(2)}</span>
                                    {itemQuery.data.cold_start.is_cold_item ? <span className="chip chip-warm">cold-start item</span> : null}
                                </div>
                                <div>
                                    <p className="soft-label">Product detail</p>
                                    <h2 className="text-3xl font-semibold text-[var(--ink-strong)]">{itemQuery.data.title}</h2>
                                    <p className="mt-2 text-[var(--ink-soft)]">
                                        {itemQuery.data.brand || "Unknown brand"} · {itemQuery.data.source_category || "Unknown source category"}
                                    </p>
                                </div>
                                <div className="flex flex-wrap items-center gap-3">
                                    <span className="text-2xl font-bold text-[var(--ink-strong)]">{formatVnd(itemQuery.data.price_vnd)}</span>
                                    <span className="chip">interactions {itemQuery.data.cold_start.interaction_count}</span>
                                </div>
                            </div>

                            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                                <button className="action-button action-button-primary" onClick={() => void handleOriginAction("add_to_cart")}>
                                    <ShoppingBag className="h-4 w-4" />
                                    Add to cart
                                </button>
                                <button className="action-button action-button-secondary" onClick={() => void handleOriginAction("wishlist")}>
                                    <BookmarkPlus className="h-4 w-4" />
                                    Wishlist
                                </button>
                                <button className="action-button action-button-secondary" onClick={() => void handleOriginAction("purchase")}>
                                    <CreditCard className="h-4 w-4" />
                                    Purchase
                                </button>
                                <button className="action-button action-button-ghost" onClick={() => void handleOriginAction("dislike")}>
                                    <ShieldAlert className="h-4 w-4" />
                                    Dislike
                                </button>
                            </div>

                            {detailFeedback ? (
                                <div className="rounded-2xl border border-[rgba(37,99,235,0.2)] bg-[rgba(37,99,235,0.08)] p-4 text-sm text-[var(--sky)]">
                                    {detailFeedback}
                                </div>
                            ) : null}

                            {origin ? (
                                <div className="rounded-[22px] border border-[var(--line-soft)] bg-white/72 p-3 text-xs text-[var(--ink-soft)]">
                                    Recommended from <strong className="text-[var(--ink-strong)]">{origin.surface}</strong>
                                </div>
                            ) : null}
                        </div>
                    </div>
                </section>
            ) : null}

            <section className="panel-strong p-6">
                <div className="mb-5 flex items-end justify-between gap-4">
                    <h3 className="text-xl font-semibold text-[var(--ink-strong)]">You might also like</h3>
                </div>

                {similarQuery.isLoading ? (
                    <p className="text-[var(--ink-soft)]">Loading similar products...</p>
                ) : similarQuery.error ? (
                    <p className="text-[var(--rose)]">{String(similarQuery.error)}</p>
                ) : !userIdHash ? (
                    <p className="text-sm text-[var(--ink-soft)]">Select a profile to see personalized similar products.</p>
                ) : !similarQuery.data?.items?.length ? (
                    <p className="text-sm text-[var(--ink-soft)]">No similar products found for this item.</p>
                ) : (
                    <div className="grid-cards">
                        {similarQuery.data.items.map((card) => (
                            <ProductCard key={`${card.request_id}:${card.item_id}`} card={card} onOpenDetail={handleOpenSimilar} onAction={handleSimilarAction} />
                        ))}
                    </div>
                )}
            </section>

        </div>
    );
}