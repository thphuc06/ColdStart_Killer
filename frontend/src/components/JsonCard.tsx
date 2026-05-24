type JsonCardProps = {
    title: string;
    data: unknown;
    emptyMessage?: string;
};


export function JsonCard({ title, data, emptyMessage = "No data yet." }: JsonCardProps) {
    const hasData = data !== null && data !== undefined && !(Array.isArray(data) && data.length === 0);

    return (
        <section className="panel p-5">
            <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                    <p className="soft-label">Inspect</p>
                    <h3 className="text-lg font-semibold text-[var(--ink-strong)]">{title}</h3>
                </div>
            </div>
            {hasData ? (
                <pre className="code-block scroll-soft">{JSON.stringify(data, null, 2)}</pre>
            ) : (
                <div className="rounded-2xl border border-dashed border-[var(--line-soft)] bg-white/65 p-5 text-sm text-[var(--ink-soft)]">
                    {emptyMessage}
                </div>
            )}
        </section>
    );
}