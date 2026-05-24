import { AlertTriangle, Loader2, PackageSearch } from "lucide-react";
import type { ReactNode } from "react";


type StateViewProps = {
    title: string;
    message: string;
    action?: ReactNode;
};


export function LoadingState({ title = "Loading", message = "Fetching the latest recommendations." }) {
    return (
        <section className="state-card text-[var(--ink-soft)]">
            <div>
                <Loader2 className="mx-auto mb-3 h-7 w-7 animate-spin-slow text-[var(--sky)]" />
                <h3 className="text-base font-semibold text-[var(--ink-strong)]">{title}</h3>
                <p className="mt-1 text-sm">{message}</p>
            </div>
        </section>
    );
}


export function EmptyState({ title, message, action }: StateViewProps) {
    return (
        <section className="state-card">
            <div>
                <PackageSearch className="mx-auto mb-3 h-8 w-8 text-[var(--ink-muted)]" />
                <h3 className="text-base font-semibold text-[var(--ink-strong)]">{title}</h3>
                <p className="mt-1 max-w-md text-sm text-[var(--ink-soft)]">{message}</p>
                {action ? <div className="mt-4">{action}</div> : null}
            </div>
        </section>
    );
}


export function ErrorState({ title = "Something went wrong", message }: { title?: string; message: string }) {
    return (
        <section className="state-card border-[rgba(190,18,60,0.25)] bg-[var(--rose-soft)]">
            <div>
                <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-[var(--rose)]" />
                <h3 className="text-base font-semibold text-[var(--ink-strong)]">{title}</h3>
                <p className="mt-1 max-w-2xl text-sm text-[var(--rose)]">{message}</p>
            </div>
        </section>
    );
}
