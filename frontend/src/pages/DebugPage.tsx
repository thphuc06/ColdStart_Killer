import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DatabaseBackup, Gauge, RefreshCcw, TestTube2, Wrench } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { JsonCard } from "../components/JsonCard";
import { EvaluationSummaryCard } from "../components/EvaluationSummaryCard";
import { JobRunsPanel } from "../components/JobRunsPanel";
import { StatusBadge } from "../components/StatusBadge";
import { applyPendingBehavior, getDebugUser, getDemoStatus, getLatestEvaluationRun, processEvents, rebuildCf, rebuildProfiles, resetDemo, seedDemo } from "../lib/api";
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
            <span className="text-right text-sm font-medium text-[var(--ink-strong)]">{value ?? "n/a"}</span>
        </div>
    );
}


function formatVersionStatus(stored: string | null | undefined, configured: string | null | undefined) {
    if (!stored && !configured) {
        return "n/a";
    }
    if (!stored) {
        return `stored: n/a | expected: ${configured ?? "n/a"}`;
    }
    if (!configured || stored === configured) {
        return stored;
    }
    return `stored: ${stored} | expected: ${configured}`;
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

const ADMIN_TOKEN_STORAGE_KEY = "coldstart-killer/admin-token/v1";
const SEED_DEMO_CONFIRMATION = "SEED_DEMO_BEHAVIOR";
const PROCESS_EVENTS_CONFIRMATION = "PROCESS_EVENTS_WRITE";
const APPLY_PENDING_BEHAVIOR_CONFIRMATION = "APPLY_PENDING_BEHAVIOR_WRITE";
const REBUILD_PROFILES_CONFIRMATION = "REBUILD_PROFILES_WRITE";
const REBUILD_CF_CONFIRMATION = "REBUILD_CF_WRITE";


export function DebugPage() {
    const { userIdHash } = useExperience();
    const queryClient = useQueryClient();
    const [adminToken, setAdminToken] = useState(() => {
        if (typeof window === "undefined") {
            return "";
        }
        return window.sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) || "";
    });
    const [resetWrite, setResetWrite] = useState(false);
    const [resetFull, setResetFull] = useState(false);
    const [resetConfirm, setResetConfirm] = useState("");
    const [seedWrite, setSeedWrite] = useState(false);
    const [seedUsers, setSeedUsers] = useState(40);
    const [seedRequests, setSeedRequests] = useState(3);
    const [seedItems, setSeedItems] = useState(10);
    const [seedValue, setSeedValue] = useState(42);
    const [seedConfirm, setSeedConfirm] = useState("");
    const [processWrite, setProcessWrite] = useState(false);
    const [processLimit, setProcessLimit] = useState("100");
    const [processConfirm, setProcessConfirm] = useState("");
    const [profileWrite, setProfileWrite] = useState(false);
    const [profileLimitUsers, setProfileLimitUsers] = useState("");
    const [profileConfirm, setProfileConfirm] = useState("");
    const [cfWrite, setCfWrite] = useState(false);
    const [cfLimitUsers, setCfLimitUsers] = useState("");
    const [cfSupport, setCfSupport] = useState(2);
    const [cfConfirm, setCfConfirm] = useState("");
    const [applyWrite, setApplyWrite] = useState(false);
    const [applyMaxEvents, setApplyMaxEvents] = useState("500");
    const [applyConfirm, setApplyConfirm] = useState("");
    const hasAdminToken = adminToken.trim().length > 0;

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }
        const value = adminToken.trim();
        if (value) {
            window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, value);
            return;
        }
        window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
    }, [adminToken]);

    const debugQuery = useQuery({
        queryKey: ["debug-user", userIdHash],
        queryFn: () => getDebugUser(userIdHash!, adminToken),
        enabled: Boolean(userIdHash && hasAdminToken),
    });
    const demoStatusQuery = useQuery({
        queryKey: ["demo-status"],
        queryFn: () => getDemoStatus(adminToken),
        enabled: hasAdminToken,
    });
    const evaluationRunQuery = useQuery({ queryKey: ["evaluation-run-latest"], queryFn: getLatestEvaluationRun });

    const refreshAdminState = async () => {
        const tasks: Promise<unknown>[] = [queryClient.invalidateQueries({ queryKey: ["demo-users"] })];
        if (hasAdminToken) {
            tasks.push(demoStatusQuery.refetch());
        }
        tasks.push(queryClient.invalidateQueries({ queryKey: ["homepage-feed"] }));
        if (userIdHash && hasAdminToken) {
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
        mutationFn: () =>
            applyPendingBehavior({
                maxEvents: Number(applyMaxEvents) || 500,
                rebuildItemStats: true,
                write: applyWrite,
                confirm: applyConfirm || undefined,
                adminToken,
                userIdHash: userIdHash || undefined,
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
    const freshness = debugQuery.data?.freshness;
    const configuredVersions = freshness?.model_versions?.configured ?? demoStatusQuery.data?.model_versions;
    const storedVersions = freshness?.model_versions?.stored;
    const staleVersionComponents = freshness?.model_versions?.stale_version_components ?? [];
    const profileWriteBlocked = profileWrite && profileLimitUsers.trim().length > 0;
    const cfWriteBlocked = cfWrite && cfLimitUsers.trim().length > 0;
    const processWriteBlocked = processWrite && processLimit.trim().length > 0;
    const seedConfirmBlocked = seedWrite && seedConfirm !== SEED_DEMO_CONFIRMATION;
    const processConfirmBlocked = processWrite && processConfirm !== PROCESS_EVENTS_CONFIRMATION;
    const applyConfirmBlocked = applyWrite && applyConfirm !== APPLY_PENDING_BEHAVIOR_CONFIRMATION;
    const profileConfirmBlocked = profileWrite && profileConfirm !== REBUILD_PROFILES_CONFIRMATION;
    const cfConfirmBlocked = cfWrite && cfConfirm !== REBUILD_CF_CONFIRMATION;
    const adminActionBlocked = !hasAdminToken;

    return (
        <div className="space-y-8">
            <section className="editorial-hero">
                <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr),420px] lg:items-end">
                    <div>
                        <div className="mb-4 flex flex-wrap gap-2">
                            <StatusBadge tone="sky">Technical reviewer mode</StatusBadge>
                            <StatusBadge tone="mint">Lineage visible</StatusBadge>
                            <StatusBadge tone="amber">Dry-run first</StatusBadge>
                        </div>
                        <p className="soft-label">Debug and demo recovery</p>
                        <h2 className="display-title mt-3">
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

            <section className="panel p-5">
                <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr),320px] lg:items-end">
                    <div>
                        <p className="soft-label">Admin access</p>
                        <h3 className="mt-2 text-lg font-medium text-[var(--ink-strong)]">Unlock debug and demo controls</h3>
                        <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                            Protected debug/demo endpoints now require the backend <strong>X-Admin-Token</strong>. Enter it here to load lineage and enable write actions.
                        </p>
                    </div>
                    <div className="space-y-3">
                        <input
                            className="form-input"
                            type="password"
                            placeholder="Enter admin token"
                            value={adminToken}
                            onChange={(event) => setAdminToken(event.target.value)}
                        />
                        <StatusBadge tone={hasAdminToken ? "mint" : "amber"}>
                            {hasAdminToken ? "Admin token loaded" : "Admin token required"}
                        </StatusBadge>
                    </div>
                </div>
            </section>

            <section className="grid gap-5 xl:grid-cols-[360px,minmax(0,1fr)]">
                <section className="panel p-5">
                    <p className="soft-label">Current user</p>
                    <h3 className="mt-2 text-lg font-medium text-[var(--ink-strong)]">
                        {userIdHash ? `...${userIdHash.slice(-12)}` : "No active user"}
                    </h3>
                    <div className="mt-4">
                        <FieldRow label="Profile status" value={String(debugQuery.data?.profile?.profile_status ?? "not loaded")} />
                        <FieldRow label="Events" value={Number(profileQuality?.num_events ?? 0)} />
                        <FieldRow label="Positive items" value={Number(profileQuality?.num_positive_items ?? 0)} />
                        <FieldRow label="Confidence" value={Number(profileQuality?.confidence ?? 0).toFixed(2)} />
                    </div>
                    {freshness ? (
                        <div className="mt-5 rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-3">
                            <StatusBadge
                                tone={
                                    freshness.state === "stale_version"
                                        ? "rose"
                                        : freshness.state === "stale"
                                            ? "amber"
                                            : freshness.state === "current"
                                                ? "mint"
                                                : "sky"
                                }
                            >
                                {freshness.state === "stale_version"
                                    ? "Derived version mismatch"
                                    : freshness.state === "stale"
                                        ? "Derived data stale"
                                        : freshness.state === "current"
                                            ? "Derived data current"
                                            : "Freshness unknown"}
                            </StatusBadge>
                            <div className="mt-3">
                                <FieldRow label="Pending events" value={freshness.pending_event_count} />
                                <FieldRow label="Latest event" value={freshness.latest_event_at ?? "n/a"} />
                                <FieldRow label="Signals built" value={freshness.signal_built_at ?? "n/a"} />
                                <FieldRow label="Profile built" value={freshness.profile_built_at ?? "n/a"} />
                                <FieldRow label="CF built" value={freshness.cf_built_at ?? "n/a"} />
                                {freshness.components ? (
                                    <>
                                        <FieldRow label="Signals state" value={freshness.components.signals.state} />
                                        <FieldRow label="Profile state" value={freshness.components.profile.state} />
                                        <FieldRow label="CF state" value={freshness.components.cf.state} />
                                        <FieldRow label="CF input policy" value={freshness.components.cf.input_policy} />
                                    </>
                                ) : null}
                            </div>
                            {configuredVersions ? (
                                <div className="mt-4 border-t border-[var(--line-soft)] pt-3">
                                    <p className="soft-label">Model versions</p>
                                    <div className="mt-2">
                                        <FieldRow
                                            label="Signals"
                                            value={formatVersionStatus(
                                                storedVersions?.signal_model_version,
                                                configuredVersions.signal_model_version,
                                            )}
                                        />
                                        <FieldRow
                                            label="Profiles"
                                            value={formatVersionStatus(
                                                storedVersions?.profile_model_version,
                                                configuredVersions.profile_model_version,
                                            )}
                                        />
                                        <FieldRow
                                            label="CF"
                                            value={formatVersionStatus(
                                                storedVersions?.cf_model_version,
                                                configuredVersions.cf_model_version,
                                            )}
                                        />
                                        <FieldRow label="Explanations" value={configuredVersions.explanation_version} />
                                    </div>
                                </div>
                            ) : null}
                            {staleVersionComponents.length ? (
                                <p className="mt-2 text-xs text-[var(--rose)]">
                                    Version rebuild required: {staleVersionComponents.join(", ")}.
                                </p>
                            ) : freshness.stale_components.length ? (
                                <p className="mt-2 text-xs text-[var(--ink-soft)]">
                                    Rebuild required: {freshness.stale_components.join(", ")}.
                                </p>
                            ) : null}
                            {freshness.components?.cf.state === "refresh_required" ? (
                                <p className="mt-2 text-xs text-[var(--amber)]">
                                    Profile updated; CF scheduled refresh required.
                                </p>
                            ) : null}
                        </div>
                    ) : null}
                </section>

                <section className="panel p-5">
                    <p className="soft-label">Data lineage</p>
                    <h3 className="mt-2 text-lg font-medium text-[var(--ink-strong)]">Recommendation trace</h3>
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
                                <p className="mt-3 text-sm font-medium text-[var(--ink-strong)]">{label}</p>
                                <p className="text-xs text-[var(--ink-soft)]">{String(value)} records visible</p>
                            </div>
                        ))}
                    </div>
                </section>
            </section>

            <EvaluationSummaryCard
                data={evaluationRunQuery.data}
                isLoading={evaluationRunQuery.isLoading}
                error={evaluationRunQuery.error instanceof Error ? evaluationRunQuery.error : null}
            />

            <JobRunsPanel adminToken={adminToken} />

            <section className="panel p-5">
                <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr),360px]">
                    <div>
                        <p className="soft-label">Demo Recovery</p>
                        <h3 className="mt-2 text-xl font-medium text-[var(--ink-strong)]">Reset modes and rebuild order</h3>
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
                            {demoStatusQuery.data?.model_versions ? (
                                <div className="mt-4 border-t border-[var(--line-soft)] pt-3">
                                    <p className="soft-label">Configured versions</p>
                                    <div className="mt-2 space-y-2">
                                        <FieldRow label="Signals" value={demoStatusQuery.data.model_versions.signal_model_version} />
                                        <FieldRow label="Profiles" value={demoStatusQuery.data.model_versions.profile_model_version} />
                                        <FieldRow label="CF" value={demoStatusQuery.data.model_versions.cf_model_version} />
                                        <FieldRow label="Explanations" value={demoStatusQuery.data.model_versions.explanation_version} />
                                    </div>
                                </div>
                            ) : null}
                        </div>
                    </div>
                </div>

                <details className="mt-5 rounded-lg border border-[var(--line-soft)] bg-white p-4">
                    <summary className="cursor-pointer font-medium text-[var(--ink-strong)]">
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
                            <h3 className="mt-2 text-lg font-medium text-[var(--ink-strong)]">
                                Apply interactions to personalization
                            </h3>
                            <p className="mt-2 text-sm leading-6 text-[var(--ink-soft)]">
                                Impressions and actions are written to clickstream immediately. This action is scoped to the current
                                shopper and incrementally refreshes affected signals, item stats and profiles. Preview mode does not
                                write derived personalization state.
                            </p>
                        </div>
                        <button
                            className="action-button action-button-primary w-full"
                            disabled={applyBehaviorMutation.isPending || applyConfirmBlocked || adminActionBlocked}
                            onClick={() => applyBehaviorMutation.mutate()}
                        >
                            <Wrench className="h-4 w-4" />
                            {applyBehaviorMutation.isPending
                                ? (applyWrite ? "Applying behavior..." : "Previewing behavior...")
                                : (applyWrite ? "Apply captured behavior" : "Preview pending behavior")}
                        </button>
                        <label className="flex items-center gap-3 rounded-lg bg-[var(--surface-muted)] px-4 py-3 text-sm font-semibold">
                            <input checked={applyWrite} type="checkbox" onChange={(event) => setApplyWrite(event.target.checked)} />
                            write mode
                        </label>
                        <label className="space-y-1 text-sm font-semibold text-[var(--ink-strong)]">
                            max events for current shopper
                            <input
                                className="form-input"
                                inputMode="numeric"
                                value={applyMaxEvents}
                                onChange={(event) => setApplyMaxEvents(event.target.value)}
                            />
                        </label>
                        <p className="text-xs leading-5 text-[var(--ink-soft)]">
                            Current shopper: {userIdHash || "n/a"}. Turn on write mode and enter the confirmation text to make homepage
                            recommendations change.
                        </p>
                        {applyWrite ? (
                            <input
                                className="form-input"
                                placeholder={APPLY_PENDING_BEHAVIOR_CONFIRMATION}
                                value={applyConfirm}
                                onChange={(event) => setApplyConfirm(event.target.value)}
                            />
                        ) : null}
                    </div>
                </section>

                <section className="panel p-5">
                    <div className="mb-4 flex items-center gap-3">
                        <DatabaseBackup className="h-5 w-5 text-[var(--rose)]" />
                        <div>
                            <p className="soft-label">Reset behavior data</p>
                            <h3 className="text-lg font-medium text-[var(--ink-strong)]">Dry-run first, confirm before live reset</h3>
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
                            disabled={resetMutation.isPending || adminActionBlocked}
                            onClick={() =>
                                resetMutation.mutate({
                                    write: resetWrite,
                                    full: resetFull,
                                    confirm: resetConfirm || undefined,
                                    adminToken,
                                })
                            }
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
                            <h3 className="text-lg font-medium text-[var(--ink-strong)]">Admin-only synthetic data writer</h3>
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
                    {seedWrite ? (
                        <input
                            className="form-input mt-3"
                            placeholder={SEED_DEMO_CONFIRMATION}
                            value={seedConfirm}
                            onChange={(event) => setSeedConfirm(event.target.value)}
                        />
                    ) : null}
                    <button
                        className="action-button action-button-primary mt-3 w-full"
                        disabled={seedMutation.isPending || seedConfirmBlocked || adminActionBlocked}
                        onClick={() =>
                            seedMutation.mutate({
                                users: seedUsers,
                                requestsPerUser: seedRequests,
                                itemsPerRequest: seedItems,
                                seed: seedValue,
                                write: seedWrite,
                                confirm: seedConfirm || undefined,
                                adminToken,
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
                            <h3 className="text-lg font-medium text-[var(--ink-strong)]">Signals and item stats</h3>
                        </div>
                    </div>
                    <input className="form-input" type="number" placeholder="event limit (dry-run only)" value={processLimit} onChange={(event) => setProcessLimit(event.target.value)} />
                    <p className={`text-xs leading-5 ${processWriteBlocked ? "text-[var(--rose)]" : "text-[var(--ink-soft)]"}`}>
                        {processWriteBlocked
                            ? "Full signal write does not allow an event limit. Clear the limit or use Apply captured behavior."
                            : "Limited full processing is for dry-run inspection; live behavior uses the incremental action above."}
                    </p>
                    <label className="mt-3 flex items-center gap-3 rounded-lg bg-[var(--surface-muted)] px-4 py-3 text-sm font-semibold">
                        <input checked={processWrite} type="checkbox" onChange={(event) => setProcessWrite(event.target.checked)} />
                        write mode
                    </label>
                    {processWrite ? (
                        <input
                            className="form-input mt-3"
                            placeholder={PROCESS_EVENTS_CONFIRMATION}
                            value={processConfirm}
                            onChange={(event) => setProcessConfirm(event.target.value)}
                        />
                    ) : null}
                    <button
                        className="action-button action-button-primary mt-3 w-full"
                        disabled={processMutation.isPending || processWriteBlocked || processConfirmBlocked || adminActionBlocked}
                        onClick={() =>
                            processMutation.mutate({
                                limit: processLimit ? Number(processLimit) : undefined,
                                write: processWrite,
                                rebuildItemStats: true,
                                confirm: processConfirm || undefined,
                                adminToken,
                            })
                        }
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
                            <h3 className="text-lg font-medium text-[var(--ink-strong)]">Profiles and CF edges</h3>
                        </div>
                    </div>

                    <div className="grid gap-4 lg:grid-cols-2">
                        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                            <div className="mb-3 font-medium text-[var(--ink-strong)]">Profiles</div>
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
                            {profileWrite ? (
                                <input
                                    className="form-input mt-3"
                                    placeholder={REBUILD_PROFILES_CONFIRMATION}
                                    value={profileConfirm}
                                    onChange={(event) => setProfileConfirm(event.target.value)}
                                />
                            ) : null}
                            <p className={`mt-2 text-xs leading-5 ${profileWriteBlocked ? "text-[var(--rose)]" : "text-[var(--ink-soft)]"}`}>
                                {profileWriteBlocked
                                    ? "Write mode requires a full rebuild. Clear the user limit first."
                                    : "Use limit users for dry-run inspection only."}
                            </p>
                            <button
                                className="action-button action-button-secondary mt-3 w-full"
                                disabled={profileMutation.isPending || profileWriteBlocked || profileConfirmBlocked || adminActionBlocked}
                                onClick={() =>
                                    profileMutation.mutate({
                                        limitUsers: profileLimitUsers ? Number(profileLimitUsers) : undefined,
                                        write: profileWrite,
                                        confirm: profileConfirm || undefined,
                                        adminToken,
                                    })
                                }
                            >
                                Rebuild profiles
                            </button>
                        </div>

                        <div className="rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-4">
                            <div className="mb-3 font-medium text-[var(--ink-strong)]">Collaborative Filtering</div>
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
                            {cfWrite ? (
                                <input
                                    className="form-input mt-3"
                                    placeholder={REBUILD_CF_CONFIRMATION}
                                    value={cfConfirm}
                                    onChange={(event) => setCfConfirm(event.target.value)}
                                />
                            ) : null}
                            <p className={`mt-2 text-xs leading-5 ${cfWriteBlocked ? "text-[var(--rose)]" : "text-[var(--ink-soft)]"}`}>
                                {cfWriteBlocked
                                    ? "Write mode requires a full rebuild. Clear the user limit first."
                                    : "Use limit users for dry-run inspection only."}
                            </p>
                            <button
                                className="action-button action-button-secondary mt-3 w-full"
                                disabled={cfMutation.isPending || cfWriteBlocked || cfConfirmBlocked || adminActionBlocked}
                                onClick={() =>
                                    cfMutation.mutate({
                                        limitUsers: cfLimitUsers ? Number(cfLimitUsers) : undefined,
                                        minSupport: cfSupport,
                                        write: cfWrite,
                                        confirm: cfConfirm || undefined,
                                        adminToken,
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
