import { ExternalLink, Heart, MinusCircle, ShoppingBag, Sparkles } from "lucide-react";
import { useState } from "react";

import type { EventType, RecommendationCard } from "../lib/api";
import { formatVnd } from "../lib/api";
import { ScoreBreakdown } from "./ScoreBreakdown";


type ProductCardProps = {
    card: RecommendationCard;
    onOpenDetail: (card: RecommendationCard) => Promise<void> | void;
    onAction: (eventType: EventType, card: RecommendationCard) => Promise<void> | void;
};


export function ProductCard({ card, onOpenDetail, onAction }: ProductCardProps) {
    const [expanded, setExpanded] = useState(false);
    const [busyAction, setBusyAction] = useState<string | null>(null);

    const cfEvidence = card.attribution.cf_evidence;
    const reasons = card.explanations.length ? card.explanations : ["No explanation returned."];

    async function runAction(eventType: EventType) {
        try {
            setBusyAction(eventType);
            await onAction(eventType, card);
        } finally {
            setBusyAction(null);
        }
    }

    return (
        <article className="panel-strong overflow-hidden p-4">
            <div className="mb-4 flex items-start gap-4">
                <div className="h-28 w-24 shrink-0 overflow-hidden rounded-[22px] bg-gradient-to-br from-slate-100 via-white to-teal-50">
                    {card.image_url ? (
                        <img className="h-full w-full object-cover" src={card.image_url} alt={card.title} loading="lazy" />
                    ) : (
                        <div className="flex h-full items-center justify-center text-[var(--ink-soft)]">
                            <Sparkles className="h-6 w-6" />
                        </div>
                    )}
                </div>
                <div className="min-w-0 flex-1">
                    <div className="mb-2 flex flex-wrap gap-2">
                        {card.reason_badges.map((badge) => (
                            <span key={badge} className="chip">
                                {badge}
                            </span>
                        ))}
                        {card.is_cold_item ? <span className="chip chip-warm">Cold start</span> : null}
                    </div>
                    <h3 className="text-lg font-semibold leading-tight text-[var(--ink-strong)]">{card.title}</h3>
                    <p className="mt-1 text-sm text-[var(--ink-soft)]">
                        {card.brand || "Unknown brand"} · {card.category_id || "uncategorized"}
                    </p>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                        <span className="text-xl font-bold text-[var(--ink-strong)]">{formatVnd(card.price_vnd)}</span>
                        <span className="chip chip-primary">#{card.rank_position}</span>
                    </div>
                </div>
            </div>

            <div className="space-y-2 rounded-[22px] bg-white/70 p-4">
                <p className="soft-label">Why we picked this</p>
                <ul className="space-y-2 text-sm text-[var(--ink-soft)]">
                    {reasons.slice(0, 3).map((reason) => (
                        <li key={reason} className="flex gap-2">
                            <span className="mt-1 h-2 w-2 rounded-full bg-[var(--mint)]" />
                            <span>{reason}</span>
                        </li>
                    ))}
                </ul>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <button className="action-button action-button-primary" onClick={() => void onOpenDetail(card)}>
                    <ExternalLink className="h-4 w-4" />
                    Open detail
                </button>
                <button className="action-button action-button-secondary" onClick={() => setExpanded((value) => !value)}>
                    {expanded ? "Hide details" : "Score details"}
                </button>
            </div>

            <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <button
                    className="action-button action-button-secondary"
                    disabled={busyAction === "wishlist"}
                    onClick={() => void runAction("wishlist")}
                >
                    <Heart className="h-4 w-4" />
                    Save
                </button>
                <button
                    className="action-button action-button-secondary"
                    disabled={busyAction === "add_to_cart"}
                    onClick={() => void runAction("add_to_cart")}
                >
                    <ShoppingBag className="h-4 w-4" />
                    Cart
                </button>
                <button
                    className="action-button action-button-ghost"
                    disabled={busyAction === "hide" || busyAction === "dislike"}
                    onClick={() => void runAction("hide")}
                >
                    <MinusCircle className="h-4 w-4" />
                    Hide
                </button>
            </div>

            {expanded ? (
                <div className="mt-4 space-y-4 rounded-[22px] border border-[var(--line-soft)] bg-white/78 p-4">
                    <div>
                        <p className="soft-label mb-2">Score breakdown</p>
                        <ScoreBreakdown breakdown={card.score_breakdown} />
                    </div>
                    {cfEvidence ? (
                        <div>
                            <p className="soft-label mb-2">Collaborative Filtering evidence</p>
                            <div className="grid gap-2 sm:grid-cols-2">
                                <div className="metric-block">
                                    <div className="text-xs uppercase tracking-[0.08em] text-[var(--ink-soft)]">Support</div>
                                    <div className="mt-1 text-xl font-semibold text-[var(--ink-strong)]">{cfEvidence.support ?? 0}</div>
                                </div>
                                <div className="metric-block">
                                    <div className="text-xs uppercase tracking-[0.08em] text-[var(--ink-soft)]">CF score</div>
                                    <div className="mt-1 text-xl font-semibold text-[var(--ink-strong)]">
                                        {(cfEvidence.cf_score ?? 0).toFixed(3)}
                                    </div>
                                </div>
                                <div className="metric-block">
                                    <div className="text-xs uppercase tracking-[0.08em] text-[var(--ink-soft)]">Co-clicks</div>
                                    <div className="mt-1 text-xl font-semibold text-[var(--ink-strong)]">
                                        {cfEvidence.co_click_count ?? 0}
                                    </div>
                                </div>
                                <div className="metric-block">
                                    <div className="text-xs uppercase tracking-[0.08em] text-[var(--ink-soft)]">Co-carts</div>
                                    <div className="mt-1 text-xl font-semibold text-[var(--ink-strong)]">
                                        {cfEvidence.co_cart_count ?? 0}
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : null}
                </div>
            ) : null}
        </article>
    );
}