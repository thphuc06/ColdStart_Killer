import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle, Fingerprint, PlusCircle, RefreshCcw, XCircle } from "lucide-react";
import { useEffect } from "react";

import { createUser, getDemoUsers, getHealth } from "../lib/api";
import { useExperience } from "../state/experience";


export function UserControlPanel() {
    const { userIdHash, sessionId, setUserIdHash, resetSession } = useExperience();

    const healthQuery = useQuery({ queryKey: ["health"], queryFn: getHealth });
    const demoUsersQuery = useQuery({ queryKey: ["demo-users"], queryFn: getDemoUsers });

    const createUserMutation = useMutation({
        mutationFn: createUser,
        onSuccess: (user) => {
            setUserIdHash(user.user_id_hash);
        },
    });

    useEffect(() => {
        if (!userIdHash && demoUsersQuery.data?.users[0]?.user_id_hash) {
            setUserIdHash(demoUsersQuery.data.users[0].user_id_hash);
        }
    }, [demoUsersQuery.data?.users, setUserIdHash, userIdHash]);

    const apiOnline = healthQuery.data?.ok === true;

    return (
        <div className="space-y-4">
            {/* Active Profile */}
            <section className="panel-strong p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <Fingerprint className="h-5 w-5 text-[var(--mint)]" />
                        <h2 className="text-sm font-semibold text-[var(--ink-strong)]">Active profile</h2>
                    </div>
                    <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${apiOnline ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-600"}`}>
                        {apiOnline
                            ? <CheckCircle className="h-3.5 w-3.5" />
                            : <XCircle className="h-3.5 w-3.5" />}
                        {apiOnline ? "API online" : "API offline"}
                    </div>
                </div>

                {userIdHash ? (
                    <div className="mb-3 rounded-xl bg-white/80 px-3 py-2.5">
                        <div className="text-xs text-[var(--ink-soft)]">Shopper ID</div>
                        <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--ink-strong)]">
                            ...{userIdHash.slice(-12)}
                        </div>
                    </div>
                ) : (
                    <p className="mb-3 text-sm text-[var(--ink-soft)]">No profile selected yet.</p>
                )}

                <div className="grid grid-cols-2 gap-2">
                    <button className="action-button action-button-secondary text-xs" onClick={() => resetSession()}>
                        <RefreshCcw className="h-3.5 w-3.5" />
                        New session
                    </button>
                    <button className="action-button action-button-primary text-xs" onClick={() => demoUsersQuery.refetch()}>
                        <RefreshCcw className="h-3.5 w-3.5" />
                        Reload
                    </button>
                </div>
            </section>

            {/* Browse anonymously */}
            <section className="panel p-4">
                <div className="mb-3 flex items-center gap-2">
                    <PlusCircle className="h-4 w-4 text-[var(--amber)]" />
                    <h3 className="text-sm font-semibold text-[var(--ink-strong)]">Browse anonymously</h3>
                </div>
                <button
                    className="action-button action-button-primary w-full"
                    disabled={createUserMutation.isPending}
                    onClick={() =>
                        createUserMutation.mutate({
                            allow_personalization: true,
                            allow_clickstream_logging: true,
                        })
                    }
                >
                    <PlusCircle className="h-4 w-4" />
                    {createUserMutation.isPending ? "Creating..." : "Create anonymous shopper"}
                </button>
                {createUserMutation.error ? (
                    <p className="mt-2 text-xs text-[var(--rose)]">{String(createUserMutation.error)}</p>
                ) : null}
            </section>

            {/* Switch profile */}
            <section className="panel p-4">
                <h3 className="mb-3 text-sm font-semibold text-[var(--ink-strong)]">Switch profile</h3>

                <div className="max-h-64 space-y-1.5 overflow-auto pr-1 scroll-soft">
                    {demoUsersQuery.isLoading ? (
                        <p className="text-xs text-[var(--ink-soft)]">Loading profiles...</p>
                    ) : null}
                    {demoUsersQuery.data?.users.map((user) => (
                        <button
                            key={user.user_id_hash}
                            className={`w-full rounded-xl border px-3 py-2.5 text-left text-sm transition ${user.user_id_hash === userIdHash
                                ? "border-[rgba(15,118,110,0.38)] bg-[rgba(15,118,110,0.10)]"
                                : "border-[var(--line-soft)] bg-white/70 hover:bg-white"
                                }`}
                            onClick={() => setUserIdHash(user.user_id_hash)}
                        >
                            <div className="font-semibold text-[var(--ink-strong)]">...{user.user_id_hash.slice(-10)}</div>
                            <div className="mt-0.5 text-xs text-[var(--ink-soft)]">
                                {user.profile_status} - personalization {user.privacy.allow_personalization ? "on" : "off"}
                            </div>
                        </button>
                    ))}
                </div>
            </section>

            {/* Session info (collapsed/minimal) */}
            <details className="panel p-3 text-xs text-[var(--ink-soft)]">
                <summary className="cursor-pointer select-none font-medium text-[var(--ink-soft)]">Session details</summary>
                <div className="mt-2 space-y-1 font-mono">
                    <div className="truncate">{sessionId}</div>
                </div>
            </details>
        </div>
    );
}
