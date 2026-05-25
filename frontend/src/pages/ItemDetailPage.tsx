import { useQuery } from "@tanstack/react-query";
import { BookmarkPlus, CreditCard, ShieldAlert, ShoppingBag } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { ProductCard } from "../components/ProductCard";
import { ProductImage } from "../components/ProductImage";
import { EmptyState, ErrorState, LoadingState } from "../components/StateViews";
import { StatusBadge } from "../components/StatusBadge";
import { formatVnd, getItemDetail, getSimilarProducts, type EventType, type RecommendationCard } from "../lib/api";
import { buildOriginFromCard, trackDirectDetailAction, trackRecommendationAction, type RecommendationOrigin } from "../lib/tracking";
import { useImpressionLogger } from "../lib/useImpressionLogger";
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
    const [selectedImageUrl, setSelectedImageUrl] = useState<string | null>(null);
    const galleryImages = useMemo(() => {
        const item = itemQuery.data;
        if (!item) {
            return [];
        }
        return Array.from(
            new Set(
                [item.image_url, ...item.image_urls]
                    .filter((url): url is string => Boolean(url))
                    .filter((url) => url !== item.image_fallback_url),
            ),
        );
    }, [itemQuery.data]);
    const featureLines = useMemo(
        () =>
            (itemQuery.data?.source_text?.features_text || "")
                .split(/\r?\n/)
                .map((line) => line.trim())
                .filter(Boolean),
        [itemQuery.data?.source_text?.features_text],
    );

    useEffect(() => {
        setSelectedImageUrl(itemQuery.data?.image_url || null);
    }, [itemQuery.data?.image_url, itemQuery.data?.item_id]);

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
        if (!userIdHash || !itemId) {
            return;
        }

        const startedAt = performance.now();
        return () => {
            const dwell = Math.max(500, Math.round(performance.now() - startedAt));
            if (origin) {
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
                return;
            }
            void trackDirectDetailAction({
                userIdHash,
                sessionId,
                itemId,
                eventType: "view_detail",
                dwellTimeMs: dwell,
                clientComponent: "product-detail",
            });
        };
    }, [itemId, origin, originKey, sessionId, userIdHash]);

    async function handleOriginAction(eventType: EventType) {
        if (!userIdHash || !itemId) {
            return;
        }

        if (origin) {
            await trackRecommendationAction({
                userIdHash,
                sessionId,
                itemId,
                eventType,
                origin,
                queryText: origin.queryText,
                clientComponent: "product-detail",
            });
            setDetailFeedback(`${eventType.replace(/_/g, " ")} logged against the originating ${origin.surface} recommendation.`);
            return;
        }

        await trackDirectDetailAction({
            userIdHash,
            sessionId,
            itemId,
            eventType,
            clientComponent: "product-detail",
        });
        setDetailFeedback(`${eventType.replace(/_/g, " ")} logged on this product detail page.`);
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
        <div className="space-y-10">
            {itemQuery.isLoading ? (
                <LoadingState title="Loading product" message="Fetching catalog metadata and cold-start state." />
            ) : itemQuery.error ? (
                <ErrorState message={String(itemQuery.error)} />
            ) : itemQuery.data ? (
                <section className="panel overflow-hidden">
                    <div className="grid gap-0 lg:grid-cols-[420px,minmax(0,1fr)]">
                        <div className="bg-[var(--surface-muted)] p-5">
                            <div className="aspect-[4/3] overflow-hidden rounded-lg bg-white">
                                <ProductImage
                                    alt={itemQuery.data.title}
                                    className="h-full w-full object-contain p-5"
                                    fallbackSrc={itemQuery.data.image_fallback_url}
                                    loading="eager"
                                    src={selectedImageUrl || itemQuery.data.image_url}
                                />
                            </div>
                            {galleryImages.length > 1 ? (
                                <div className="mt-3 grid grid-cols-4 gap-2">
                                    {galleryImages.slice(0, 8).map((imageUrl, index) => (
                                        <button
                                            className={`aspect-square overflow-hidden rounded-md border bg-white p-1 ${(selectedImageUrl || itemQuery.data.image_url) === imageUrl
                                                    ? "border-[var(--mint)]"
                                                    : "border-[var(--line-soft)]"
                                                }`}
                                            key={imageUrl}
                                            aria-label={`View product image ${index + 1}`}
                                            onClick={() => setSelectedImageUrl(imageUrl)}
                                            type="button"
                                        >
                                            <ProductImage alt="" className="h-full w-full object-contain" src={imageUrl} />
                                        </button>
                                    ))}
                                </div>
                            ) : null}
                        </div>

                        <div className="space-y-6 p-6">
                            <div className="flex flex-wrap gap-2">
                                <StatusBadge tone="sky">{itemQuery.data.category_id}</StatusBadge>
                                <StatusBadge tone="amber">{itemQuery.data.price_bucket}</StatusBadge>
                                <StatusBadge tone="mint">Quality {itemQuery.data.quality_score.toFixed(2)}</StatusBadge>
                                {itemQuery.data.cold_start.is_cold_item ? <StatusBadge tone="amber">Cold-start item</StatusBadge> : null}
                            </div>

                            <div>
                                <p className="soft-label">Product detail</p>
                                <h2 className="display-title mt-3">
                                    {itemQuery.data.title}
                                </h2>
                                <p className="mt-3 text-sm leading-6 text-[var(--ink-soft)]">
                                    {itemQuery.data.brand || "Unknown brand"} / {itemQuery.data.source_category || "Unknown source category"}
                                </p>
                            </div>

                            <div className="grid gap-3 sm:grid-cols-3">
                                <div className="metric-block">
                                    <p className="soft-label">Price</p>
                                    <p className="metric-value">{formatVnd(itemQuery.data.price_vnd)}</p>
                                </div>
                                <div className="metric-block">
                                    <p className="soft-label">Interactions</p>
                                    <p className="metric-value">{itemQuery.data.cold_start.interaction_count}</p>
                                </div>
                                <div className="metric-block">
                                    <p className="soft-label">Stock</p>
                                    <p className="metric-value">Ready</p>
                                </div>
                            </div>

                            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
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
                                <div className="rounded-lg border border-[#c7d8f3] bg-[var(--sky-soft)] p-3 text-sm font-medium text-[var(--sky)]">
                                    {detailFeedback}
                                </div>
                            ) : null}

                            <div className="cream-callout p-4">
                                <p className="soft-label">Recommendation origin</p>
                                {origin ? (
                                    <p className="mt-1 text-sm text-[var(--ink-soft)]">
                                        Opened from <strong className="text-[var(--ink-strong)]">{origin.surface}</strong> at rank{" "}
                                        <strong className="text-[var(--ink-strong)]">{origin.rankPosition ?? "n/a"}</strong>.
                                    </p>
                                ) : (
                                    <p className="mt-1 text-sm text-[var(--ink-soft)]">
                                        Opened directly. Detail views and actions are still logged, but without recommendation attribution.
                                    </p>
                                )}
                            </div>

                            {itemQuery.data.source_text.description_text ||
                                itemQuery.data.source_text.features_text ||
                                itemQuery.data.source_text.details_text ? (
                                <div className="space-y-4 rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                                    <p className="soft-label">Product information</p>
                                    {itemQuery.data.source_text.description_text ? (
                                        <div>
                                            <h3 className="text-sm font-medium text-[var(--ink-strong)]">Description</h3>
                                            <p className="mt-2 whitespace-pre-line text-sm leading-6 text-[var(--ink-soft)]">
                                                {itemQuery.data.source_text.description_text}
                                            </p>
                                        </div>
                                    ) : null}
                                    {featureLines.length ? (
                                        <div>
                                            <h3 className="text-sm font-medium text-[var(--ink-strong)]">Features</h3>
                                            <ul className="mt-2 space-y-1 text-sm leading-6 text-[var(--ink-soft)]">
                                                {featureLines.map((line) => (
                                                    <li key={line}>- {line}</li>
                                                ))}
                                            </ul>
                                        </div>
                                    ) : null}
                                    {itemQuery.data.source_text.details_text ? (
                                        <details>
                                            <summary className="cursor-pointer text-sm font-medium text-[var(--ink-strong)]">
                                                Technical details
                                            </summary>
                                            <p className="mt-2 whitespace-pre-line text-sm leading-6 text-[var(--ink-soft)]">
                                                {itemQuery.data.source_text.details_text}
                                            </p>
                                        </details>
                                    ) : null}
                                </div>
                            ) : (
                                <p className="text-sm text-[var(--ink-soft)]">No product description is available in the catalog.</p>
                            )}
                        </div>
                    </div>
                </section>
            ) : null}

            <section className="border-t border-[var(--line-soft)] pt-10">
                <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
                    <div>
                        <p className="soft-label">Related recommendations</p>
                        <h3 className="section-title mt-2">Similar products</h3>
                        <p className="mt-2 text-sm text-[var(--ink-soft)]">
                            Semantic similarity and collaborative filtering are shown separately in each card.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <StatusBadge tone="sky">Semantic similarity</StatusBadge>
                        <StatusBadge tone="violet">Collaborative Filtering</StatusBadge>
                    </div>
                </div>

                {similarQuery.isLoading ? (
                    <LoadingState title="Finding similar products" message="Combining semantic neighbors with behavior-derived CF evidence." />
                ) : similarQuery.error ? (
                    <ErrorState message={String(similarQuery.error)} />
                ) : !userIdHash ? (
                    <EmptyState title="Select a profile" message="A shopper profile is required for personalized similar products." />
                ) : !similarQuery.data?.items?.length ? (
                    <EmptyState title="No similar products found" message="This item does not have enough neighbor evidence yet." />
                ) : (
                    <div className="grid-cards">
                        {similarQuery.data.items.map((card) => (
                            <ProductCard
                                key={`${card.request_id}:${card.item_id}`}
                                card={card}
                                onOpenDetail={handleOpenSimilar}
                                onAction={handleSimilarAction}
                            />
                        ))}
                    </div>
                )}
            </section>
        </div>
    );
}
