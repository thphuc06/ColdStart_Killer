import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup, Gauge, RefreshCcw, TestTube2, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { JsonCard } from "../components/JsonCard";
import { StatusBadge } from "../components/StatusBadge";
import { getDebugUser, getDemoStatus, processEvents, rebuildCf, rebuildProfiles, resetDemo, seedDemo } from "../lib/api";
import { useExperience } from "../state/experience";


function ActionResult({ title, data }: { title: string; data: unknown }) {
    if (!data) {
        return null;
    }
    return <JsonCard title={title} data={data} emptyMessage="No response yet." />;
}


function FieldRow({ label, value }: { label: string; value: string | number | null | undefined }) {
    return (
        <div className="flex items-center justify-between gap-3 border-b border-[var(--line-soft)] py-2 last:border-0">
            <span className="text-sm text-[var(--ink-soft)]">{label}</span>
            <span className="text-right text-sm font-bold text-[var(--ink-strong)]">{value ?? "n/a"}</span>
        </div>
    );
}


const SOFT_RESET_RECOVERY_STEPS = [
    "Re-seed recommendation logs and clickstream events.",
    "Build user_item_signals and rebuild item_stats.",
    "Build user_profiles from reseeded behavior.",
    "Keep seeded/precomputed item_item_cf_edges for quick recovery.",
    "Use full reset only when you need to replay the complete CF rebuild from signals.",
];

const FULL_RESET_RECOVERY_STEPS = [
    "Re-seed recommendation logs and clickstream events.",
    "Build user_item_signals and rebuild item_stats.",
    "Build user_profiles from derived signals/events.",
    "Build true item_item_cf_edges from multi-user signals.",
    "Optionally rebuild item_semantic_neighbors if they were explicitly cleared.",
    "Run evaluation and browser smoke test before recording the demo.",
];


export function DebugPage() {
    const { userIdHash } = useExperience();
    const queryClient = useQueryClient();
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
    const demoStatusQuery = useQuery({ queryKey: ["demo-status"], queryFn: getDemoStatus });

    const refreshAdminState = async () => {
        const tasks: Promise<unknown>[] = [
            demoStatusQuery.refetch(),
            queryClient.invalidateQueries({ queryKey: ["demo-users"] }),
            queryClient.invalidateQueries({ queryKey: ["homepage-feed"] }),
        ];
        if (userIdHash) {
            tasks.unshift(debugQuery.refetch());
        }
        await Promise.all(tasks);
    };

    const resetMutation = useMutation({ mutationFn: resetDemo, onSuccess: refreshAdminState });
    const seedMutation = useMutation({ mutationFn: seedDemo, onSuccess: refreshAdminState });
    const processMutation = useMutation({ mutationFn: processEvents, onSuccess: refreshAdminState });
    const profileMutation = useMutation({ mutationFn: rebuildProfiles, onSuccess: refreshAdminState });
    const cfMutation = useMutation({ mutationFn: rebuildCf, onSuccess: refreshAdminState });
    const applyBehaviorMutation = useMutation({
        mutationFn: async () => ({
            signals: await processEvents({ limit: 100000, rebuildItemStats: true, write: true }),
            profiles: await rebuildProfiles({ write: true }),
            cf: await rebuildCf({ write: true }),
        }),
        onSuccess: refreshAdminState,
    });

    const metricSummary = useMemo(
        () => ({
            signals: debugQuery.data?.signals.length ?? 0,
            logs: debugQuery.data?.recent_logs.length ?? 0,
            events: debugQuery.data?.recent_events.length ?? 0,
            cfEdges: debugQuery.data?.cf_edges.length ?? 0,
        }),
        [debugQuery.data],
    );

    const profileQuality = debugQuery.data?.profile?.profile_quality as Record<string, unknown> | undefined;

    return (
        <div className="space-y-5">
            <section className="page-hero p-6">
                <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr),420px] lg:items-end">
                    <div>
                        <div className="mb-4 flex flex-wrap gap-2">
                            <StatusBadge tone="sky">Technical reviewer mode</StatusBadge>
                            <StatusBadge tone="mint">Lineage visible</StatusBadge>
                            <StatusBadge tone="amber">Dry-run first</StatusBadge>
                        </div>
                        <p className="soft-label">Debug and demo recovery</p>
                        <h2 className="mt-2 text-3xl font-black tracking-tight text-[var(--ink-strong)]">
                            Inspect lineage and operate the demo safely
                        </h2>
                        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--ink-soft)]">
                            Use this page to show how recommendations connect to logs, events, user signals, profile vectors,
                            and item-item collaborative filtering without crowding the shopping pages.
                        </p>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                        <div className="metric-block">
                            <p className="soft-label">Signals</p>
                            <p className="metric-value">{metricSummary.signals}</p>
                        </div>
                        <div className="metric-block">
                            <p className="soft-label">Events</p>
                            <p className="metric-value">{metricSummary.events}</p>
                        </div>
                        <div className="metric-block">
                            <p className="soft-label">Logs</p>
                            <p className="metric-value">{metricSummary.logs}</p>
                        </div>
                        <div className="metric-block">
                            <p className="soft-label">CF edges</p>
                            <p className="metric-value">{metricSummary.cfEdges}</p>
                        </div>
                    </div>
                </div>
            </section>

            <section className="grid gap-5 xl:grid-cols-[360px,minmax(0,1fr)]">
                <section className="panel p-5">
                    <p className="soft-label">Current user</p>
                    <h3 className="mt-1 text-lg font-black text-[var(--ink-strong)]">
                        {userIdHash ? `...${userIdHash.slice(-12)}` : "No active user"}
                    </h3>
                    <div className="mt-4">
                        <FieldRow label="Profile status" value={String(debugQuery.data?.profile?.profile_status ?? "not loaded")} />
                        <FieldRow label="Events" value={Number(profileQuality?.num_events ?? 0)} />
                        <FieldRow label="Positive items" value={Number(profileQuality?.num_positive_items ?? 0)} />
                        <FieldRow label="Confidence" value={Number(profileQuality?.confidence ?? 0).toFixed(2)} />
                    </div>
                </section>

                <section className="panel p-5">
                    <p className="soft-label">Data lineage</p>
                    <h3 className="mt-1 text-lg font-black text-[var(--ink-strong)]">Recommendation trace</h3>
                    <div className="mt-4 grid gap-3 md:grid-cols-5">
                        {[
                            ["Logs", metricSummary.logs, "sky"],
                            ["Events", metricSummary.events, "mint"],
                            ["Signals", metricSummary.signals, "amber"],
                            ["Profile", debugQuery.data?.profile ? 1 : 0, "mint"],
                            ["CF edges", metricSummary.cfEdges, "violet"],
                        ].map(([label, value, tone]) => (
                            <div key={String(label)} className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-3">
                                <StatusBadge tone={tone as "sky" | "mint" | "amber" | "violet"}>{Number(value) > 0 ? "Verified" : "Not verified"}</StatusBadge>
                                <p className="mt-3 text-sm font-bold text-[var(--ink-strong)]">{label}</p>
                                <p className="text-xs text-[var(--ink-soft)]">{String(value)} records visible</p>
                            </div>
                        ))}
                    </div>
                </section>
            </section>

            <section className="panel p-5">
                <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr),360px]">
                    <div>
                        <p className="soft-label">Demo Recovery</p>
                        <h3 className="mt-1 text-xl font-black text-[var(--ink-strong)]">Reset modes and rebuild order</h3>
                        <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                            Soft reset clears recommendation logs, clickstream events, user signals, profiles, and item stats while
                            keeping catalog data and precomputed synthetic CF edges. Full reset also clears behavior-derived CF edges
                            and requires rebuilding signals, profiles, item stats, and item-item CF.
                        </p>
                        <div className="mt-4 grid gap-3 md:grid-cols-2">
                            <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                                <StatusBadge tone="mint">Soft reset</StatusBadge>
                                <p className="mt-3 text-sm text-[var(--ink-soft)]">
                                    Clears behavior state but keeps seeded/precomputed `item_item_cf_edges` for quick recovery.
                                </p>
                                <p className="mt-2 font-mono text-xs text-[var(--ink-muted)]">Confirm: DEMO_RESET</p>
                            </div>
                            <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                                <StatusBadge tone="amber">Full reset</StatusBadge>
                                <p className="mt-3 text-sm text-[var(--ink-soft)]">
                                    Also clears `item_item_cf_edges`. Use only when replaying the full event-to-signal-to-profile-to-CF pipeline.
                                </p>
                                <p className="mt-2 font-mono text-xs text-[var(--ink-muted)]">Confirm: FULL_DEMO_RESET</p>
                            </div>
                        </div>
                        <div className="mt-4 rounded-lg border border-[rgba(109,40,217,0.18)] bg-[var(--violet-soft)] p-4 text-sm leading-6 text-[var(--violet)]">
                            {demoStatusQuery.data?.precomputed_cf_note ||
                                "CF evidence may be seeded/precomputed for demo stability. Use full reset + rebuild to replay event -> signal -> profile -> CF."}
                        </div>
                    </div>

                    <div className="space-y-3">
                        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                            <p className="soft-label">Protected collections</p>
                            <div className="mt-3 flex flex-wrap gap-2">
                                {(demoStatusQuery.data?.protected_collections || ["items", "retrieval_units"]).map((name) => (
                                    <StatusBadge key={name} tone="rose">{name}</StatusBadge>
                                ))}
                            </div>
                        </div>
                        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                            <p className="soft-label">Current demo state</p>
                            <div className="mt-3 space-y-2">
                                {["recommendation_logs", "clickstream_events", "user_item_signals", "user_profiles", "item_stats", "item_item_cf_edges"].map((name) => (
                                    <FieldRow key={name} label={name} value={demoStatusQuery.data?.counts?.[name] ?? "n/a"} />
                                ))}
                            </div>
                        </div>
                    </div>
                </div>

                <details className="mt-5 rounded-lg border border-[var(--line-soft)] bg-white p-4">
                    <summary className="cursor-pointer font-bold text-[var(--ink-strong)]">
                        Recovery steps after {resetFull ? "full" : "soft"} reset
                    </summary>
                    <div className="mt-3">
                        <StatusBadge tone={resetFull ? "amber" : "mint"}>{resetFull ? "Full reset selected" : "Soft reset selected"}</StatusBadge>
                    </div>
                    <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6 text-[var(--ink-soft)]">
                        {(resetFull ? FULL_RESET_RECOVERY_STEPS : SOFT_RESET_RECOVERY_STEPS).map((step) => (
                            <li key={step}>{step}</li>
                        ))}
                    </ol>
                </details>
            </section>

            <section className="grid gap-5 xl:grid-cols-2">
                <section className="panel p-5 xl:col-span-2">
                    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr),320px] lg:items-center">
                        <div>
                            <p className="soft-label">Captured UI behavior</p>
                            <h3 className="mt-1 text-lg font-black text-[var(--ink-strong)]">
                                Apply interactions to personalization
                            </h3>
                            <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                                Impressions and actions are written to clickstream immediately. This action processes them into
                                signals and item stats, rebuilds user profiles, then refreshes collaborative-filtering edges.
                            </p>
                        </div>
                        <button
                            className="action-button action-button-primary w-full"
                            disabled={applyBehaviorMutation.isPending}
                            onClick={() => applyBehaviorMutation.mutate()}
                        >
                            <Wrench className="h-4 w-4" />
                            {applyBehaviorMutation.isPending ? "Applying behavior..." : "Apply captured behavior"}
                        </button>
                    </div>
                </section>

                <section className="panel p-5">
                    <div className="mb-4 flex items-center gap-3">
                        <DatabaseBackup className="h-5 w-5 text-[var(--rose)]" />
                        <div>
                            <p className="soft-label">Reset behavior data</p>
                            <h3 className="text-lg font-black text-[var(--ink-strong)]">Dry-run first, confirm before live reset</h3>
                        </div>
                    </div>

                    <div className="space-y-3">
                        <label className="flex items-center gap-3 rounded-lg bg-[var(--surface-muted)] px-4 py-3 text-sm font-semibold">
                            <input checked={resetWrite} type="checkbox" onChange={(event) => setResetWrite(event.target.checked)} />
                            write mode
                        </label>
                        <label className="flex items-center gap-3 rounded-lg bg-[var(--surface-muted)] px-4 py-3 text-sm font-semibold">
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
                        <p className="text-xs leading-5 text-[var(--ink-muted)]">This will clear current demo interactions.</p>
                    </div>
                </section>

                <section className="panel p-5">
                    <div className="mb-4 flex items-center gap-3">
                        <TestTube2 className="h-5 w-5 text-[var(--amber)]" />
                        <div>
                            <p className="soft-label">Seed synthetic behavior</p>
                            <h3 className="text-lg font-black text-[var(--ink-strong)]">Admin-only synthetic data writer</h3>
                        </div>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2">
                        <input className="form-input" type="number" placeholder="# users" value={seedUsers} onChange={(event) => setSeedUsers(Number(event.target.value))} />
                        <input className="form-input" type="number" placeholder="requests / user" value={seedRequests} onChange={(event) => setSeedRequests(Number(event.target.value))} />
                        <input className="form-input" type="number" placeholder="items / request" value={seedItems} onChange={(event) => setSeedItems(Number(event.target.value))} />
                        <input className="form-input" type="number" placeholder="random seed" value={seedValue} onChange={(event) => setSeedValue(Number(event.target.value))} />
                    </div>
                    <label className="mt-3 flex items-center gap-3 rounded-lg bg-[var(--surface-muted)] px-4 py-3 text-sm font-semibold">
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
                            <h3 className="text-lg font-black text-[var(--ink-strong)]">Signals and item stats</h3>
                        </div>
                    </div>
                    <input className="form-input" type="number" placeholder="event limit" value={processLimit} onChange={(event) => setProcessLimit(Number(event.target.value))} />
                    <label className="mt-3 flex items-center gap-3 rounded-lg bg-[var(--surface-muted)] px-4 py-3 text-sm font-semibold">
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
                            <h3 className="text-lg font-black text-[var(--ink-strong)]">Profiles and CF edges</h3>
                        </div>
                    </div>

                    <div className="grid gap-4 lg:grid-cols-2">
                        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                            <div className="mb-3 font-bold text-[var(--ink-strong)]">Profiles</div>
                            <input
                                className="form-input"
                                placeholder="limit users (optional)"
                                value={profileLimitUsers}
                                onChange={(event) => setProfileLimitUsers(event.target.value)}
                            />
                            <label className="mt-3 flex items-center gap-3 text-sm font-semibold">
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

                        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                            <div className="mb-3 font-bold text-[var(--ink-strong)]">Collaborative Filtering</div>
                            <div className="grid gap-3 sm:grid-cols-2">
                                <input
                                    className="form-input"
                                    placeholder="limit users"
                                    value={cfLimitUsers}
                                    onChange={(event) => setCfLimitUsers(event.target.value)}
                                />
                                <input className="form-input" type="number" placeholder="min support" value={cfSupport} onChange={(event) => setCfSupport(Number(event.target.value))} />
                            </div>
                            <label className="mt-3 flex items-center gap-3 text-sm font-semibold">
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
                <ActionResult title="Applied behavior response" data={applyBehaviorMutation.data} />
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
