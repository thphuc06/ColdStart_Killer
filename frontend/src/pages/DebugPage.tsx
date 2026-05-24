import { useMutation, useQuery } from "@tanstack/react-query";
import { DatabaseBackup, Gauge, RefreshCcw, TestTube2, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { JsonCard } from "../components/JsonCard";
import { getDebugUser, processEvents, rebuildCf, rebuildProfiles, resetDemo, seedDemo } from "../lib/api";
import { useExperience } from "../state/experience";


function ActionResult({ title, data }: { title: string; data: unknown }) {
    if (!data) {
        return null;
    }
    return <JsonCard title={title} data={data} emptyMessage="No response yet." />;
}


export function DebugPage() {
    const { userIdHash } = useExperience();
    const [resetWrite, setResetWrite] = useState(false);
    const [resetFull, setResetFull] = useState(false);
    const [resetConfirm, setResetConfirm] = useState("");
    const [seedWrite, setSeedWrite] = useState(false);
    const [seedUsers, setSeedUsers] = useState(40);
    const [seedRequests, setSeedRequests] = useState(3);
    const [seedItems, setSeedItems] = useState(10);
    const [seedValue, setSeedValue] = useState(42);
    const [processWrite, setProcessWrite] = useState(false);
    const [processLimit, setProcessLimit] = useState(500);
    const [profileWrite, setProfileWrite] = useState(false);
    const [profileLimitUsers, setProfileLimitUsers] = useState("");
    const [cfWrite, setCfWrite] = useState(false);
    const [cfLimitUsers, setCfLimitUsers] = useState("");
    const [cfSupport, setCfSupport] = useState(2);

    const debugQuery = useQuery({
        queryKey: ["debug-user", userIdHash],
        queryFn: () => getDebugUser(userIdHash!),
        enabled: Boolean(userIdHash),
    });

    const resetMutation = useMutation({ mutationFn: resetDemo });
    const seedMutation = useMutation({ mutationFn: seedDemo });
    const processMutation = useMutation({ mutationFn: processEvents });
    const profileMutation = useMutation({ mutationFn: rebuildProfiles });
    const cfMutation = useMutation({ mutationFn: rebuildCf });

    const metricSummary = useMemo(
        () => ({
            signals: debugQuery.data?.signals.length ?? 0,
            logs: debugQuery.data?.recent_logs.length ?? 0,
            events: debugQuery.data?.recent_events.length ?? 0,
            cfEdges: debugQuery.data?.cf_edges.length ?? 0,
        }),
        [debugQuery.data],
    );

    return (
        <div className="space-y-5">
            <section className="panel-strong p-6">
                <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
                    <div>
                        <div className="hero-ribbon mb-3">
                            <Gauge className="h-4 w-4 text-[var(--sky)]" />
                            Debug and demo recovery
                        </div>
                        <h2 className="text-3xl font-semibold text-[var(--ink-strong)]">Inspect lineage and operate the demo safely</h2>
                        <p className="mt-3 max-w-3xl text-[var(--ink-soft)]">
                            This page exposes the same dry-run-first behavior expected by the roadmap: inspect user state, test resets, seed behavior, and rebuild downstream artifacts without mixing business logic into the frontend.
                        </p>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <div className="metric-block">
                            <div className="soft-label">Signals</div>
                            <div className="mt-1 text-2xl font-semibold text-[var(--ink-strong)]">{metricSummary.signals}</div>
                        </div>
                        <div className="metric-block">
                            <div className="soft-label">Logs</div>
                            <div className="mt-1 text-2xl font-semibold text-[var(--ink-strong)]">{metricSummary.logs}</div>
                        </div>
                        <div className="metric-block">
                            <div className="soft-label">Events</div>
                            <div className="mt-1 text-2xl font-semibold text-[var(--ink-strong)]">{metricSummary.events}</div>
                        </div>
                        <div className="metric-block">
                            <div className="soft-label">CF edges</div>
                            <div className="mt-1 text-2xl font-semibold text-[var(--ink-strong)]">{metricSummary.cfEdges}</div>
                        </div>
                    </div>
                </div>
            </section>

            <section className="grid gap-5 xl:grid-cols-2">
                <section className="panel p-5">
                    <div className="mb-4 flex items-center gap-3">
                        <DatabaseBackup className="h-5 w-5 text-[var(--rose)]" />
                        <div>
                            <p className="soft-label">Reset behavior data</p>
                            <h3 className="text-lg font-semibold text-[var(--ink-strong)]">Dry-run first, confirm before live reset</h3>
                        </div>
                    </div>

                    <div className="space-y-3">
                        <label className="flex items-center gap-3 rounded-2xl bg-white/70 px-4 py-3">
                            <input checked={resetWrite} type="checkbox" onChange={(event) => setResetWrite(event.target.checked)} />
                            write mode
                        </label>
                        <label className="flex items-center gap-3 rounded-2xl bg-white/70 px-4 py-3">
                            <input checked={resetFull} type="checkbox" onChange={(event) => setResetFull(event.target.checked)} />
                            full reset
                        </label>
                        <input
                            className="form-input"
                            placeholder={resetFull ? "FULL_DEMO_RESET" : "DEMO_RESET"}
                            value={resetConfirm}
                            onChange={(event) => setResetConfirm(event.target.value)}
                        />
                        <button
                            className="action-button action-button-primary w-full"
                            disabled={resetMutation.isPending}
                            onClick={() => resetMutation.mutate({ write: resetWrite, full: resetFull, confirm: resetConfirm || undefined })}
                        >
                            <RefreshCcw className="h-4 w-4" />
                            {resetMutation.isPending ? "Submitting..." : "Run reset"}
                        </button>
                    </div>
                </section>

                <section className="panel p-5">
                    <div className="mb-4 flex items-center gap-3">
                        <TestTube2 className="h-5 w-5 text-[var(--amber)]" />
                        <div>
                            <p className="soft-label">Seed synthetic behavior</p>
                            <h3 className="text-lg font-semibold text-[var(--ink-strong)]">Admin-only synthetic data writer</h3>
                        </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                        <input className="form-input" type="number" placeholder="# users" value={seedUsers} onChange={(event) => setSeedUsers(Number(event.target.value))} />
                        <input className="form-input" type="number" placeholder="requests / user" value={seedRequests} onChange={(event) => setSeedRequests(Number(event.target.value))} />
                        <input className="form-input" type="number" placeholder="items / request" value={seedItems} onChange={(event) => setSeedItems(Number(event.target.value))} />
                        <input className="form-input" type="number" placeholder="random seed" value={seedValue} onChange={(event) => setSeedValue(Number(event.target.value))} />
                    </div>
                    <label className="mt-3 flex items-center gap-3 rounded-2xl bg-white/70 px-4 py-3">
                        <input checked={seedWrite} type="checkbox" onChange={(event) => setSeedWrite(event.target.checked)} />
                        write mode
                    </label>
                    <button
                        className="action-button action-button-primary mt-3 w-full"
                        disabled={seedMutation.isPending}
                        onClick={() =>
                            seedMutation.mutate({
                                users: seedUsers,
                                requestsPerUser: seedRequests,
                                itemsPerRequest: seedItems,
                                seed: seedValue,
                                write: seedWrite,
                            })
                        }
                    >
                        <TestTube2 className="h-4 w-4" />
                        {seedMutation.isPending ? "Submitting..." : "Run seed"}
                    </button>
                </section>

                <section className="panel p-5">
                    <div className="mb-4 flex items-center gap-3">
                        <Wrench className="h-5 w-5 text-[var(--mint)]" />
                        <div>
                            <p className="soft-label">Process events</p>
                            <h3 className="text-lg font-semibold text-[var(--ink-strong)]">Signals and item stats</h3>
                        </div>
                    </div>
                    <input className="form-input" type="number" placeholder="event limit" value={processLimit} onChange={(event) => setProcessLimit(Number(event.target.value))} />
                    <label className="mt-3 flex items-center gap-3 rounded-2xl bg-white/70 px-4 py-3">
                        <input checked={processWrite} type="checkbox" onChange={(event) => setProcessWrite(event.target.checked)} />
                        write mode
                    </label>
                    <button
                        className="action-button action-button-primary mt-3 w-full"
                        disabled={processMutation.isPending}
                        onClick={() => processMutation.mutate({ limit: processLimit, write: processWrite, rebuildItemStats: true })}
                    >
                        <Wrench className="h-4 w-4" />
                        {processMutation.isPending ? "Submitting..." : "Process events"}
                    </button>
                </section>

                <section className="panel p-5">
                    <div className="mb-4 flex items-center gap-3">
                        <Gauge className="h-5 w-5 text-[var(--sky)]" />
                        <div>
                            <p className="soft-label">Rebuild downstream artifacts</p>
                            <h3 className="text-lg font-semibold text-[var(--ink-strong)]">Profiles and CF edges</h3>
                        </div>
                    </div>

                    <div className="space-y-4">
                        <div className="rounded-2xl bg-white/70 p-4">
                            <div className="mb-3 font-semibold text-[var(--ink-strong)]">Profiles</div>
                            <input
                                className="form-input"
                                placeholder="limit users (optional)"
                                value={profileLimitUsers}
                                onChange={(event) => setProfileLimitUsers(event.target.value)}
                            />
                            <label className="mt-3 flex items-center gap-3 rounded-2xl bg-white/80 px-4 py-3">
                                <input checked={profileWrite} type="checkbox" onChange={(event) => setProfileWrite(event.target.checked)} />
                                write mode
                            </label>
                            <button
                                className="action-button action-button-secondary mt-3 w-full"
                                disabled={profileMutation.isPending}
                                onClick={() =>
                                    profileMutation.mutate({
                                        limitUsers: profileLimitUsers ? Number(profileLimitUsers) : undefined,
                                        write: profileWrite,
                                    })
                                }
                            >
                                Rebuild profiles
                            </button>
                        </div>

                        <div className="rounded-2xl bg-white/70 p-4">
                            <div className="mb-3 font-semibold text-[var(--ink-strong)]">Collaborative Filtering</div>
                            <div className="grid gap-3 sm:grid-cols-2">
                                <input
                                    className="form-input"
                                    placeholder="limit users"
                                    value={cfLimitUsers}
                                    onChange={(event) => setCfLimitUsers(event.target.value)}
                                />
                                <input className="form-input" type="number" placeholder="min support" value={cfSupport} onChange={(event) => setCfSupport(Number(event.target.value))} />
                            </div>
                            <label className="mt-3 flex items-center gap-3 rounded-2xl bg-white/80 px-4 py-3">
                                <input checked={cfWrite} type="checkbox" onChange={(event) => setCfWrite(event.target.checked)} />
                                write mode
                            </label>
                            <button
                                className="action-button action-button-secondary mt-3 w-full"
                                disabled={cfMutation.isPending}
                                onClick={() =>
                                    cfMutation.mutate({
                                        limitUsers: cfLimitUsers ? Number(cfLimitUsers) : undefined,
                                        minSupport: cfSupport,
                                        write: cfWrite,
                                    })
                                }
                            >
                                Rebuild CF edges
                            </button>
                        </div>
                    </div>
                </section>
            </section>

            <section className="grid gap-5 xl:grid-cols-2">
                <ActionResult title="Reset response" data={resetMutation.data} />
                <ActionResult title="Seed response" data={seedMutation.data} />
                <ActionResult title="Process-events response" data={processMutation.data} />
                <ActionResult title="Rebuild-profiles response" data={profileMutation.data} />
                <ActionResult title="Rebuild-cf response" data={cfMutation.data} />
            </section>

            <section className="grid gap-5 xl:grid-cols-2">
                <JsonCard title="User doc" data={debugQuery.data?.user} emptyMessage="Select a user to inspect." />
                <JsonCard title="Profile doc" data={debugQuery.data?.profile} emptyMessage="No profile yet for this user." />
                <JsonCard title="Top signals" data={debugQuery.data?.signals} emptyMessage="No signals yet." />
                <JsonCard title="Recent recommendation logs" data={debugQuery.data?.recent_logs} emptyMessage="No logs yet." />
                <JsonCard title="Recent clickstream events" data={debugQuery.data?.recent_events} emptyMessage="No events yet." />
                <JsonCard title="CF edges" data={debugQuery.data?.cf_edges} emptyMessage="No CF edges found." />
            </section>
        </div>
    );
}