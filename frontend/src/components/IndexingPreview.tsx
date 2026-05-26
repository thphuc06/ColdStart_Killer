import { AlertTriangle, CheckCircle2, Database, FileText } from "lucide-react";

import type { SellerIndexingPreview } from "../lib/api";
import { StatusBadge } from "./StatusBadge";


type IndexingPreviewProps = {
    preview?: SellerIndexingPreview | null;
};


export function IndexingPreview({ preview }: IndexingPreviewProps) {
    if (!preview) {
        return (
            <section className="panel p-5">
                <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--surface-muted)] text-[var(--ink-muted)]">
                        <FileText className="h-5 w-5" />
                    </div>
                    <div>
                        <p className="soft-label">Indexing preview</p>
                        <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">No preview generated yet</h3>
                        <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                            Generate a preview before any catalog write. Preview writes only to the seller draft record.
                        </p>
                    </div>
                </div>
            </section>
        );
    }

    return (
        <section className="panel p-5">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                    <p className="soft-label">Indexing preview</p>
                    <h3 className="mt-1 text-base font-medium text-[var(--ink-strong)]">{preview.proposed_item_id}</h3>
                    <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">{preview.message}</p>
                </div>
                <StatusBadge tone={preview.valid ? "mint" : "rose"}>
                    {preview.valid ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
                    {preview.valid ? "Preview valid" : "Needs fixes"}
                </StatusBadge>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
                <div className="metric-block">
                    <p className="soft-label">Catalog writes</p>
                    <p className="metric-value">{preview.catalog_write_performed ? "yes" : "no"}</p>
                </div>
                <div className="metric-block">
                    <p className="soft-label">Text units</p>
                    <p className="metric-value">{preview.estimated_retrieval_units}</p>
                </div>
                <div className="metric-block">
                    <p className="soft-label">Vector units</p>
                    <p className="metric-value">{preview.vector_units_generated ?? 0}</p>
                </div>
            </div>

            {preview.validation_errors.length ? (
                <div className="mt-4 rounded-lg bg-[var(--rose-soft)] p-3 text-sm text-[var(--rose)]">
                    {preview.validation_errors.join("; ")}
                </div>
            ) : null}
            {preview.validation_warnings.length ? (
                <div className="mt-4 rounded-lg bg-[var(--amber-soft)] p-3 text-sm text-[var(--amber)]">
                    {preview.validation_warnings.join("; ")}
                </div>
            ) : null}

            <div className="mt-4 space-y-2">
                {preview.retrieval_units.slice(0, 6).map((unit) => (
                    <div key={unit._id} className="rounded-lg bg-[var(--surface-muted)] p-3 text-sm">
                        <div className="mb-1 flex items-center gap-2">
                            <Database className="h-3.5 w-3.5 text-[var(--sky)]" />
                            <span className="font-medium text-[var(--ink-strong)]">{unit.unit_type}</span>
                            <span className="text-xs text-[var(--ink-soft)]">{unit.source}</span>
                        </div>
                        <p className="text-[var(--ink-soft)]">{unit.raw_text}</p>
                    </div>
                ))}
            </div>
        </section>
    );
}
