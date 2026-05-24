import { ExternalLink, Heart, MinusCircle, ShoppingBag, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import type { EventType, RecommendationCard } from "../lib/api";
import { formatVnd } from "../lib/api";
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
    if (hasPositiveScore(card, "profile_score") || card.attribution.matched_profile_interest_ids.length) {
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


export function ProductCard({ card, onOpenDetail, onAction }: ProductCardProps) {
    const [expanded, setExpanded] = useState(false);
    const [busyAction, setBusyAction] = useState<string | null>(null);
    const badges = useMemo(() => buildBadges(card), [card]);
    const cfEvidence = card.attribution.cf_evidence;

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
                {card.image_url ? (
                    <img className="h-full w-full object-cover" src={card.image_url} alt={card.title} loading="lazy" />
                ) : (
                    <div className="flex h-full items-center justify-center text-[var(--ink-muted)]">
                        <Sparkles className="h-8 w-8" />
                    </div>
                )}
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
                    <h3 className="product-title text-base font-black leading-snug text-[var(--ink-strong)]">
                        {card.title}
                    </h3>
                    <p className="mt-1 line-clamp-2 text-sm text-[var(--ink-soft)]">
                        {card.brand || "Unknown brand"} / {card.category_id || "uncategorized"}
                    </p>
                </div>

                <div className="flex items-end justify-between gap-3">
                    <div>
                        <p className="text-xs font-bold uppercase tracking-[0.08em] text-[var(--ink-muted)]">Price</p>
                        <p className="mt-0.5 text-lg font-black text-[var(--ink-strong)]">{formatVnd(card.price_vnd)}</p>
                    </div>
                    <div className="text-right">
                        <p className="text-xs font-bold uppercase tracking-[0.08em] text-[var(--ink-muted)]">Score</p>
                        <p className="mt-0.5 text-lg font-black text-[var(--mint)]">{card.final_score.toFixed(3)}</p>
                    </div>
                </div>

                <div className="rounded-lg bg-[var(--surface-muted)] p-3">
                    <p className="soft-label mb-1">Why shown</p>
                    <p className="line-clamp-2 text-sm leading-5 text-[var(--ink-soft)]">{primaryExplanation(card)}</p>
                </div>

                <div className="grid grid-cols-[1fr,auto] gap-2">
                    <button className="action-button action-button-primary" onClick={() => void onOpenDetail(card)}>
                        <ExternalLink className="h-4 w-4" />
                        View details
                    </button>
                    <button
                        className="action-button action-button-secondary"
                        aria-label={expanded ? "Hide score details" : "Show score details"}
                        onClick={() => setExpanded((value) => !value)}
                    >
                        {expanded ? "Hide" : "Scores"}
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

                {expanded ? (
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
                                        <p className="font-black text-[var(--ink-strong)]">{cfEvidence.support ?? 0}</p>
                                    </div>
                                    <div>
                                        <span className="text-[var(--ink-soft)]">CF score</span>
                                        <p className="font-black text-[var(--ink-strong)]">
                                            {(cfEvidence.cf_score ?? 0).toFixed(3)}
                                        </p>
                                    </div>
                                    <div>
                                        <span className="text-[var(--ink-soft)]">Co-clicks</span>
                                        <p className="font-black text-[var(--ink-strong)]">{cfEvidence.co_click_count ?? 0}</p>
                                    </div>
                                    <div>
                                        <span className="text-[var(--ink-soft)]">Co-carts</span>
                                        <p className="font-black text-[var(--ink-strong)]">{cfEvidence.co_cart_count ?? 0}</p>
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
