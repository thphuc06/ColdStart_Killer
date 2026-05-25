type ScoreBreakdownProps = {
    breakdown: Record<string, number>;
};


const preferredOrder = [
    "final_score",
    "query_hybrid_score",
    "profile_score",
    "item_item_cf_score",
    "semantic_neighbor_score",
    "cold_start_boost",
    "exploration_score",
    "seen_penalty",
    "negative_penalty",
];


function formatLabel(key: string) {
    return key.replace(/_/g, " ");
}


export function ScoreBreakdown({ breakdown }: ScoreBreakdownProps) {
    const rows = Object.entries(breakdown)
        .filter(([, value]) => typeof value === "number" && Number.isFinite(value) && Math.abs(value) > 0.0001)
        .sort((left, right) => {
            const leftIndex = preferredOrder.indexOf(left[0]);
            const rightIndex = preferredOrder.indexOf(right[0]);
            if (leftIndex !== -1 || rightIndex !== -1) {
                return (leftIndex === -1 ? 99 : leftIndex) - (rightIndex === -1 ? 99 : rightIndex);
            }
            return Math.abs(right[1]) - Math.abs(left[1]);
        })
        .slice(0, 9);

    if (!rows.length) {
        return <p className="text-sm text-[var(--ink-soft)]">No score breakdown returned for this item.</p>;
    }

    const maxAbs = Math.max(...rows.map(([, value]) => Math.abs(value)), 0.001);

    return (
        <div className="space-y-2">
            {rows.map(([key, value]) => {
                const width = `${Math.max(6, Math.min(100, (Math.abs(value) / maxAbs) * 100))}%`;
                const negative = value < 0;
                return (
                    <div key={key} className="rounded-lg border border-[var(--line-soft)] bg-white p-3">
                        <div className="mb-2 flex items-center justify-between gap-3 text-sm">
                            <span className="capitalize text-[var(--ink-soft)]">{formatLabel(key)}</span>
                            <span className="font-medium text-[var(--ink-strong)]">{value.toFixed(3)}</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                            <div
                                className={`h-full rounded-full ${negative ? "bg-[var(--rose)]" : "bg-[var(--sky)]"}`}
                                style={{ width }}
                            />
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
