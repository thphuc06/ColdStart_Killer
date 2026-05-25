type JsonCardProps = {
    title: string;
    data: unknown;
    emptyMessage?: string;
    defaultOpen?: boolean;
};


export function JsonCard({ title, data, emptyMessage = "No data yet.", defaultOpen = false }: JsonCardProps) {
    const hasData = data !== null && data !== undefined && !(Array.isArray(data) && data.length === 0);

    return (
        <section className="panel p-5">
            <div className="mb-3">
                <p className="soft-label">Inspect</p>
                <h3 className="text-lg font-medium text-[var(--ink-strong)]">{title}</h3>
            </div>
            {hasData ? (
                <details open={defaultOpen}>
                    <summary className="cursor-pointer rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] px-3 py-2 text-sm font-medium text-[var(--ink-soft)]">
                        View structured payload
                    </summary>
                    <pre className="code-block scroll-soft mt-3">{JSON.stringify(data, null, 2)}</pre>
                </details>
            ) : (
                <div className="rounded-lg border border-dashed border-[var(--line-soft)] bg-[var(--surface-muted)] p-5 text-sm text-[var(--ink-soft)]">
                    {emptyMessage}
                </div>
            )}
        </section>
    );
}
