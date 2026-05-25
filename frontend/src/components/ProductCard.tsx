import { ChevronDown, ChevronUp, ExternalLink, Heart, MinusCircle, ShoppingBag } from "lucide-react";
import { useMemo, useState } from "react";

import type { EventType, RecommendationCard } from "../lib/api";
import { formatVnd } from "../lib/api";
import { ProductImage } from "./ProductImage";
import { ScoreBreakdown } from "./ScoreBreakdown";
import { StatusBadge } from "./StatusBadge";


type ProductCardProps = {
    card: RecommendationCard;
    onOpenDetail: (card: RecommendationCard) => Promise<void> | void;
    onAction: (eventType: EventType, card: RecommendationCard) => Promise<void> | void;
};


function scoreValue(card: RecommendationCard, key: string) {
    return Number(card.score_breakdown?.[key] ?? card.scores?.[key] ?? 0);
}


function hasPositiveScore(card: RecommendationCard, key: string) {
    return scoreValue(card, key) > 0.0001;
}


function buildBadges(card: RecommendationCard) {
    const badges: Array<{ label: string; tone: "mint" | "sky" | "amber" | "violet" | "neutral" }> = [];
    const channels = card.debug?.matched_channels || card.attribution?.matched_channels || [];
    if (card.reason_badges.includes("Profile")) {
        badges.push({ label: "Profile", tone: "mint" });
    }
    if (card.attribution.cf_evidence || hasPositiveScore(card, "item_item_cf_score")) {
        badges.push({ label: "Collaborative Filtering", tone: "violet" });
    }
    if (hasPositiveScore(card, "semantic_neighbor_score")) {
        badges.push({ label: "Semantic similar", tone: "sky" });
    }
    if (channels.includes("bm25")) {
        badges.push({ label: "BM25 fact", tone: "neutral" });
    }
    if (card.reason_badges.some((badge) => /hype|semantic/i.test(badge)) || channels.includes("vector")) {
        badges.push({ label: "HyPE intent", tone: "sky" });
    }
    if (card.is_cold_item) {
        badges.push({ label: "Cold-start", tone: "amber" });
    }
    return badges.slice(0, 4);
}


function primaryExplanation(card: RecommendationCard) {
    if (card.explanations.length) {
        return card.explanations[0];
    }
    if (card.attribution.cf_evidence) {
        return "Users with overlapping behavior also interacted with this item.";
    }
    if (card.matched_intent) {
        return `Matched intent: ${card.matched_intent}`;
    }
    return "Recommended from the current ranking blend.";
}


function cardExplanations(card: RecommendationCard) {
    const explanations = card.explanations.map((explanation) => explanation.trim()).filter(Boolean);
    return explanations.length ? [...new Set(explanations)] : [primaryExplanation(card)];
}


export function ProductCard({ card, onOpenDetail, onAction }: ProductCardProps) {
    const [scoresExpanded, setScoresExpanded] = useState(false);
    const [whyExpanded, setWhyExpanded] = useState(false);
    const [busyAction, setBusyAction] = useState<string | null>(null);
    const badges = useMemo(() => buildBadges(card), [card]);
    const explanations = useMemo(() => cardExplanations(card), [card]);
    const cfEvidence = card.attribution.cf_evidence;
    const canExpandExplanation = explanations.length > 1 || explanations[0].length > 90;
    const explanationId = `why-shown-${card.request_id}-${card.item_id}`;

    async function runAction(eventType: EventType) {
        try {
            setBusyAction(eventType);
            await onAction(eventType, card);
        } finally {
            setBusyAction(null);
        }
    }

    return (
        <article className="product-card">
            <div className="product-card-image relative">
                <ProductImage
                    alt={card.title}
                    className="h-full w-full object-contain p-3"
                    fallbackSrc={card.image_fallback_url}
                    src={card.image_url}
                />
                <div className="absolute left-3 top-3">
                    <StatusBadge tone="sky">Rank #{card.rank_position}</StatusBadge>
                </div>
            </div>

            <div className="space-y-4 p-4">
                <div className="flex flex-wrap gap-1.5">
                    {badges.map((badge) => (
                        <StatusBadge key={badge.label} tone={badge.tone}>
                            {badge.label}
                        </StatusBadge>
                    ))}
                </div>

                <div>
                    <h3 className="product-title text-base leading-snug">
                        {card.title}
                    </h3>
                    <p className="mt-1 line-clamp-2 text-sm text-[var(--ink-soft)]">
                        {card.brand || "Unknown brand"} / {card.category_id || "uncategorized"}
                    </p>
                </div>

                <div className="flex items-end justify-between gap-3">
                    <div>
                        <p className="soft-label">Price</p>
                        <p className="mt-1 text-lg font-medium text-[var(--ink-strong)]">{formatVnd(card.price_vnd)}</p>
                    </div>
                    <div className="text-right">
                        <p className="soft-label">Score</p>
                        <p className="mt-1 text-lg font-medium text-[var(--mint)]">{card.final_score.toFixed(3)}</p>
                    </div>
                </div>

                <div className="rounded-lg bg-[var(--surface-muted)] p-3">
                    <p className="soft-label mb-1">Why shown</p>
                    <div id={explanationId} className="space-y-2">
                        {(whyExpanded ? explanations : explanations.slice(0, 1)).map((explanation, index) => (
                            <p
                                className={`${whyExpanded ? "" : "line-clamp-2 "}text-sm leading-5 text-[var(--ink-soft)]`}
                                key={`${index}:${explanation}`}
                            >
                                {explanation}
                            </p>
                        ))}
                    </div>
                    {canExpandExplanation ? (
                        <button
                            aria-controls={explanationId}
                            aria-expanded={whyExpanded}
                            className="why-toggle"
                            onClick={() => setWhyExpanded((value) => !value)}
                            type="button"
                        >
                            {whyExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                            {whyExpanded ? "Collapse reason" : "Read full reason"}
                        </button>
                    ) : null}
                </div>

                <div className="grid grid-cols-[1fr,auto] gap-2">
                    <button className="action-button action-button-primary" onClick={() => void onOpenDetail(card)}>
                        <ExternalLink className="h-4 w-4" />
                        View details
                    </button>
                    <button
                        className="action-button action-button-secondary"
                        aria-label={scoresExpanded ? "Hide score details" : "Show score details"}
                        onClick={() => setScoresExpanded((value) => !value)}
                    >
                        {scoresExpanded ? "Hide" : "Scores"}
                    </button>
                </div>

                <div className="grid grid-cols-3 gap-2">
                    <button
                        className="action-button action-button-secondary text-xs"
                        disabled={busyAction === "wishlist"}
                        onClick={() => void runAction("wishlist")}
                    >
                        <Heart className="h-4 w-4" />
                        Save
                    </button>
                    <button
                        className="action-button action-button-secondary text-xs"
                        disabled={busyAction === "add_to_cart"}
                        onClick={() => void runAction("add_to_cart")}
                    >
                        <ShoppingBag className="h-4 w-4" />
                        Cart
                    </button>
                    <button
                        className="action-button action-button-ghost text-xs"
                        disabled={busyAction === "hide" || busyAction === "dislike"}
                        onClick={() => void runAction("hide")}
                    >
                        <MinusCircle className="h-4 w-4" />
                        Hide
                    </button>
                </div>

                {scoresExpanded ? (
                    <div className="space-y-4 border-t border-[var(--line-soft)] pt-4">
                        <div>
                            <p className="soft-label mb-2">Score breakdown</p>
                            <ScoreBreakdown breakdown={card.score_breakdown} />
                        </div>
                        {cfEvidence ? (
                            <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--violet-soft)] p-3">
                                <p className="soft-label mb-2 text-[var(--violet)]">Collaborative Filtering evidence</p>
                                <div className="grid grid-cols-2 gap-2 text-sm">
                                    <div>
                                        <span className="text-[var(--ink-soft)]">Support</span>
                                        <p className="font-medium text-[var(--ink-strong)]">{cfEvidence.support ?? 0}</p>
                                    </div>
                                    <div>
                                        <span className="text-[var(--ink-soft)]">CF score</span>
                                        <p className="font-medium text-[var(--ink-strong)]">
                                            {(cfEvidence.cf_score ?? 0).toFixed(3)}
                                        </p>
                                    </div>
                                    <div>
                                        <span className="text-[var(--ink-soft)]">Co-clicks</span>
                                        <p className="font-medium text-[var(--ink-strong)]">{cfEvidence.co_click_count ?? 0}</p>
                                    </div>
                                    <div>
                                        <span className="text-[var(--ink-soft)]">Co-carts</span>
                                        <p className="font-medium text-[var(--ink-strong)]">{cfEvidence.co_cart_count ?? 0}</p>
                                    </div>
                                </div>
                            </div>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </article>
    );
}
