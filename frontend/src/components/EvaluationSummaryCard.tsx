import { BarChart3 } from "lucide-react";

import type { EvaluationLatestResponse, EvaluationRun } from "../lib/api";
import { StatusBadge } from "./StatusBadge";


type EvaluationSummaryCardProps = {
    data?: EvaluationLatestResponse;
    isLoading?: boolean;
    error?: Error | null;
};


function formatNumber(value: unknown, digits = 4) {
    if (typeof value !== "number" || Number.isNaN(value)) {
        return "n/a";
    }
    return value.toFixed(digits);
}


function MetricCell({ label, value }: { label: string; value: unknown }) {
    const displayValue = value === null || value === undefined ? "n/a" : String(value);
    return (
        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-3">
            <p className="soft-label">{label}</p>
            <p className="mt-2 text-lg font-semibold text-[var(--ink-strong)]">{displayValue}</p>
        </div>
    );
}


function FieldRow({ label, value }: { label: string; value: string | number | boolean | null | undefined }) {
    return (
        <div className="flex items-center justify-between gap-3 border-b border-[var(--line-soft)] py-2 last:border-0">
            <span className="text-sm text-[var(--ink-soft)]">{label}</span>
            <span className="text-right text-sm font-medium text-[var(--ink-strong)]">{value ?? "n/a"}</span>
        </div>
    );
}


function EvaluationRunSummary({ run }: { run: EvaluationRun }) {
    const bestCf = run.baseline_summaries.find((row) => row.baseline === "profile_plus_cf");
    const bestProfile = run.baseline_summaries.find((row) => row.baseline === "profile_only");

    return (
        <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
                <StatusBadge tone="mint">Read-only</StatusBadge>
                <StatusBadge tone={run.synthetic_data ? "amber" : "sky"}>
                    {run.synthetic_data ? "Synthetic/demo" : "Live labeled"}
                </StatusBadge>
                <StatusBadge tone="violet">Evaluation run</StatusBadge>
            </div>

            <div className="rounded-lg border border-[rgba(180,83,9,0.22)] bg-[var(--amber-soft)] p-4 text-sm leading-6 text-[var(--amber)]">
                {run.caveat || "Synthetic/demo metrics are indicative only; do not present them as ground truth."}
            </div>

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr),320px]">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <MetricCell label="Evaluated users" value={run.evaluated_user_count} />
                    <MetricCell label="Profile+CF Hit@10" value={formatNumber(bestCf?.hit_rate_at_10)} />
                    <MetricCell label="Profile+CF MAP@20" value={formatNumber(bestCf?.map_at_20)} />
                    <MetricCell label="CF-supported" value={bestCf?.cf_supported_recommendation_count ?? "n/a"} />
                </div>
                <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                    <p className="soft-label">Run metadata</p>
                    <div className="mt-3">
                        <FieldRow label="Run ID" value={run.run_id} />
                        <FieldRow label="Created" value={run.created_at || "n/a"} />
                        <FieldRow label="Algorithm" value={run.algorithm_version} />
                        <FieldRow label="Ranking" value={run.ranking_version} />
                        <FieldRow label="Data label" value={run.data_label} />
                        <FieldRow label="Artifacts" value={run.artifacts?.written ? run.artifacts.path || "written" : "not written"} />
                    </div>
                </div>
            </div>

            {run.baseline_summaries.length ? (
                <div className="overflow-x-auto rounded-lg border border-[var(--line-soft)]">
                    <table className="w-full min-w-[760px] text-left text-sm">
                        <thead className="bg-[var(--surface-muted)] text-xs uppercase tracking-wide text-[var(--ink-muted)]">
                            <tr>
                                <th className="px-3 py-2">Baseline</th>
                                <th className="px-3 py-2">Users</th>
                                <th className="px-3 py-2">Hit@10</th>
                                <th className="px-3 py-2">Recall@20</th>
                                <th className="px-3 py-2">MAP@20</th>
                                <th className="px-3 py-2">Coverage</th>
                                <th className="px-3 py-2">CF count</th>
                            </tr>
                        </thead>
                        <tbody>
                            {run.baseline_summaries.map((row) => (
                                <tr key={row.baseline} className="border-t border-[var(--line-soft)]">
                                    <td className="px-3 py-2 font-medium text-[var(--ink-strong)]">{row.baseline}</td>
                                    <td className="px-3 py-2">{row.evaluated_user_count ?? "n/a"}</td>
                                    <td className="px-3 py-2">{formatNumber(row.hit_rate_at_10)}</td>
                                    <td className="px-3 py-2">{formatNumber(row.recall_at_20)}</td>
                                    <td className="px-3 py-2">{formatNumber(row.map_at_20)}</td>
                                    <td className="px-3 py-2">{formatNumber(row.coverage)}</td>
                                    <td className="px-3 py-2">{row.cf_supported_recommendation_count ?? "n/a"}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : (
                <div className="rounded-lg border border-dashed border-[var(--line-soft)] bg-[var(--surface-muted)] p-4 text-sm text-[var(--ink-soft)]">
                    No baseline summaries were persisted for this run.
                </div>
            )}

            <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                    <p className="soft-label">Key comparison</p>
                    <p className="mt-2 text-sm text-[var(--ink-soft)]">
                        {run.comparisons[0]?.comparison ?? "No comparison rows were persisted."}
                    </p>
                    {run.comparisons[0] ? (
                        <div className="mt-3 grid grid-cols-2 gap-2">
                            <MetricCell label="Hit delta" value={formatNumber(run.comparisons[0].hit_rate_at_10_delta)} />
                            <MetricCell label="MAP delta" value={formatNumber(run.comparisons[0].map_at_20_delta)} />
                        </div>
                    ) : null}
                </div>
                <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                    <p className="soft-label">Live state counts</p>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                        {Object.entries(run.live_state_counts).length ? (
                            Object.entries(run.live_state_counts).map(([key, value]) => (
                                <FieldRow key={key} label={key} value={value} />
                            ))
                        ) : (
                            <p className="text-[var(--ink-soft)]">No live counts persisted.</p>
                        )}
                    </div>
                </div>
            </div>

            <details className="rounded-lg border border-[var(--line-soft)] bg-white p-4">
                <summary className="cursor-pointer text-sm font-medium text-[var(--ink-soft)]">
                    View sanitized evaluation payload
                </summary>
                <pre className="code-block scroll-soft mt-3">{JSON.stringify(run, null, 2)}</pre>
            </details>
        </div>
    );
}


export function EvaluationSummaryCard({ data, isLoading = false, error = null }: EvaluationSummaryCardProps) {
    return (
        <section className="panel p-5">
            <div className="mb-4 flex items-center gap-3">
                <BarChart3 className="h-5 w-5 text-[var(--violet)]" />
                <div>
                    <p className="soft-label">Evaluation dashboard</p>
                    <h3 className="text-lg font-medium text-[var(--ink-strong)]">Latest personalization evaluation</h3>
                </div>
            </div>
            {isLoading ? (
                <div className="rounded-lg border border-dashed border-[var(--line-soft)] bg-[var(--surface-muted)] p-5 text-sm text-[var(--ink-soft)]">
                    Loading persisted evaluation run...
                </div>
            ) : error ? (
                <div className="rounded-lg border border-[rgba(190,18,60,0.25)] bg-[var(--rose-soft)] p-5 text-sm text-[var(--rose)]">
                    Evaluation dashboard unavailable: {error.message}
                </div>
            ) : data?.latest ? (
                <EvaluationRunSummary run={data.latest} />
            ) : (
                <div className="rounded-lg border border-dashed border-[var(--line-soft)] bg-[var(--surface-muted)] p-5 text-sm leading-6 text-[var(--ink-soft)]">
                    <p className="font-medium text-[var(--ink-strong)]">No persisted evaluation runs yet.</p>
                    <p className="mt-2">
                        Create one only after human approval:
                    </p>
                    <code className="mt-3 block rounded-md bg-white px-3 py-2 text-xs text-[var(--ink-strong)]">
                        python scripts/run_personalization_evaluation.py --write-evaluation-run --confirm EVAL_RUN_WRITE
                    </code>
                    <p className="mt-2">This Debug page is read-only and does not run evaluation jobs.</p>
                </div>
            )}
        </section>
    );
}
