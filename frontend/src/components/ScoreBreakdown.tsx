type ScoreBreakdownProps = {
    breakdown: Record<string, number>;
};


function formatLabel(key: string) {
    return key.replace(/_/g, " ");
}


export function ScoreBreakdown({ breakdown }: ScoreBreakdownProps) {
    const rows = Object.entries(breakdown)
        .filter(([, value]) => typeof value === "number" && Number.isFinite(value))
        .sort((left, right) => Math.abs(right[1]) - Math.abs(left[1]));

    if (!rows.length) {
        return <p className="text-sm text-[var(--ink-soft)]">No score breakdown returned for this item.</p>;
    }

    return (
        <div className="space-y-2">
            {rows.map(([key, value]) => (
                <div key={key} className="flex items-center justify-between rounded-2xl bg-white/70 px-3 py-2 text-sm">
                    <span className="capitalize text-[var(--ink-soft)]">{formatLabel(key)}</span>
                    <span className="font-semibold text-[var(--ink-strong)]">{value.toFixed(3)}</span>
                </div>
            ))}
        </div>
    );
}