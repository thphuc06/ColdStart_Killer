import { ClipboardList } from "lucide-react";

import { useQuery } from "@tanstack/react-query";

import { getJobRegistry, getJobRuns, type JobDefinition, type JobRun } from "../lib/api";
import { StatusBadge } from "./StatusBadge";


type JobRunsPanelProps = {
    adminToken: string;
};


function JobRow({ job }: { job: JobDefinition }) {
    return (
        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-3">
            <div className="flex flex-wrap items-center gap-2">
                <StatusBadge tone={job.write_capable ? "amber" : "mint"}>
                    {job.write_capable ? "Write guarded" : "Dry-run"}
                </StatusBadge>
                <StatusBadge tone={job.triggerable_from_api ? "sky" : "violet"}>
                    {job.triggerable_from_api ? "API dry-run eligible" : "Manual"}
                </StatusBadge>
            </div>
            <p className="mt-3 text-sm font-medium text-[var(--ink-strong)]">{job.label}</p>
            <p className="mt-1 text-xs leading-5 text-[var(--ink-soft)]">{job.description}</p>
            {job.command ? <code className="mt-2 block text-xs text-[var(--ink-muted)]">{job.command}</code> : null}
        </div>
    );
}


function RunRow({ run }: { run: JobRun }) {
    return (
        <div className="rounded-lg border border-[var(--line-soft)] bg-white p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-medium text-[var(--ink-strong)]">{run.job_type}</p>
                <StatusBadge tone={run.status === "failed" ? "rose" : run.dry_run ? "mint" : "amber"}>
                    {run.status}
                </StatusBadge>
            </div>
            <div className="mt-2 grid gap-2 text-xs text-[var(--ink-soft)] sm:grid-cols-2">
                <span>Run: {run.job_run_id || "n/a"}</span>
                <span>Created: {run.created_at || "n/a"}</span>
                <span>Dry-run: {run.dry_run ? "yes" : "no"}</span>
                <span>Write requested: {run.write_requested ? "yes" : "no"}</span>
            </div>
        </div>
    );
}


export function JobRunsPanel({ adminToken }: JobRunsPanelProps) {
    const hasAdminToken = adminToken.trim().length > 0;
    const registryQuery = useQuery({
        queryKey: ["jobs-registry"],
        queryFn: () => getJobRegistry(adminToken),
        enabled: hasAdminToken,
    });
    const runsQuery = useQuery({
        queryKey: ["jobs-runs"],
        queryFn: () => getJobRuns({ limit: 10, adminToken }),
        enabled: hasAdminToken,
    });

    return (
        <section className="panel p-5">
            <div className="mb-4 flex items-center gap-3">
                <ClipboardList className="h-5 w-5 text-[var(--violet)]" />
                <div>
                    <p className="soft-label">Job orchestration</p>
                    <h3 className="text-lg font-medium text-[var(--ink-strong)]">Registry and recent job runs</h3>
                </div>
            </div>

            {!hasAdminToken ? (
                <div className="rounded-lg border border-dashed border-[var(--line-soft)] bg-[var(--surface-muted)] p-5 text-sm text-[var(--ink-soft)]">
                    Enter the admin token to inspect job registry and compact job run status.
                </div>
            ) : registryQuery.isLoading ? (
                <div className="rounded-lg border border-dashed border-[var(--line-soft)] bg-[var(--surface-muted)] p-5 text-sm text-[var(--ink-soft)]">
                    Loading job registry...
                </div>
            ) : registryQuery.error ? (
                <div className="rounded-lg border border-[rgba(190,18,60,0.25)] bg-[var(--rose-soft)] p-5 text-sm text-[var(--rose)]">
                    Job registry unavailable: {registryQuery.error instanceof Error ? registryQuery.error.message : "unknown error"}
                </div>
            ) : (
                <div className="space-y-5">
                    <div className="flex flex-wrap gap-2">
                        <StatusBadge tone={registryQuery.data?.enabled ? "mint" : "amber"}>
                            {registryQuery.data?.enabled ? "Tracking enabled" : "Tracking disabled"}
                        </StatusBadge>
                        <StatusBadge tone={registryQuery.data?.trigger_api_enabled ? "amber" : "sky"}>
                            {registryQuery.data?.trigger_api_enabled ? "Trigger API enabled" : "Trigger API disabled"}
                        </StatusBadge>
                        <StatusBadge tone="violet">No Celery/Redis</StatusBadge>
                    </div>

                    <div className="rounded-lg border border-[rgba(180,83,9,0.22)] bg-[var(--amber-soft)] p-4 text-sm leading-6 text-[var(--amber)]">
                        Job trigger API is disabled by default. This panel is read-only and does not run reset, seed, indexing, enrichment, or evaluation jobs.
                    </div>

                    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr),360px]">
                        <div className="grid gap-3 md:grid-cols-2">
                            {(registryQuery.data?.jobs || []).map((job) => (
                                <JobRow key={job.job_type} job={job} />
                            ))}
                        </div>
                        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                            <p className="soft-label">Recent job runs</p>
                            <div className="mt-3 space-y-3">
                                {runsQuery.isLoading ? (
                                    <p className="text-sm text-[var(--ink-soft)]">Loading recent runs...</p>
                                ) : runsQuery.data?.runs.length ? (
                                    runsQuery.data.runs.map((run) => <RunRow key={run.job_run_id} run={run} />)
                                ) : (
                                    <p className="text-sm leading-6 text-[var(--ink-soft)]">
                                        No job_runs records yet. CLI dry-runs use no tracking unless run with <code>--track</code>.
                                    </p>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </section>
    );
}
