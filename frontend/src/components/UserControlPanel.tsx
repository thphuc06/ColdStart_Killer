import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Fingerprint, PlusCircle, RefreshCcw, UserRound, XCircle } from "lucide-react";
import { useEffect } from "react";

import { createUser, getDemoUsers, getHealth } from "../lib/api";
import { useExperience } from "../state/experience";
import { StatusBadge } from "./StatusBadge";


function shortId(value: string) {
    return `...${value.slice(-10)}`;
}


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
    const activeUser = demoUsersQuery.data?.users.find((user) => user.user_id_hash === userIdHash);

    return (
        <section className="panel p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Fingerprint className="h-5 w-5 text-[var(--mint)]" />
                    <div>
                        <p className="soft-label">Shopper context</p>
                        <h2 className="text-base font-bold text-[var(--ink-strong)]">Active profile</h2>
                    </div>
                </div>
                <StatusBadge tone={apiOnline ? "mint" : "rose"}>
                    {apiOnline ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                    {apiOnline ? "API online" : "API offline"}
                </StatusBadge>
            </div>

            {userIdHash ? (
                <div className="mb-4 rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-3">
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <p className="text-xs font-semibold text-[var(--ink-muted)]">Selected shopper</p>
                            <p className="mt-1 font-mono text-sm font-black text-[var(--ink-strong)]">{shortId(userIdHash)}</p>
                        </div>
                        <StatusBadge tone={activeUser?.has_profile ? "mint" : "amber"}>
                            {activeUser?.has_profile ? "Profile-backed" : "New user"}
                        </StatusBadge>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-[var(--ink-soft)]">
                        {activeUser?.profile_status || "new"} profile. Personalization{" "}
                        {activeUser?.privacy.allow_personalization === false ? "off" : "on"}.
                    </p>
                </div>
            ) : (
                <div className="mb-4 rounded-lg border border-dashed border-[var(--line-soft)] bg-[var(--surface-muted)] p-3 text-sm text-[var(--ink-soft)]">
                    Choose a demo shopper to activate recommendations.
                </div>
            )}

            <div className="mb-4 grid grid-cols-2 gap-2">
                <button className="action-button action-button-secondary text-xs" onClick={() => resetSession()}>
                    <RefreshCcw className="h-3.5 w-3.5" />
                    New session
                </button>
                <button className="action-button action-button-secondary text-xs" onClick={() => demoUsersQuery.refetch()}>
                    <RefreshCcw className="h-3.5 w-3.5" />
                    Reload users
                </button>
            </div>

            <div className="mb-4">
                <label className="mb-2 block text-xs font-bold text-[var(--ink-soft)]">Switch demo shopper</label>
                <select
                    className="form-select"
                    value={userIdHash || ""}
                    onChange={(event) => setUserIdHash(event.target.value || null)}
                >
                    {demoUsersQuery.isLoading ? <option value="">Loading profiles...</option> : null}
                    {demoUsersQuery.data?.users.map((user) => (
                        <option key={user.user_id_hash} value={user.user_id_hash}>
                            {shortId(user.user_id_hash)} - {user.profile_status}
                            {user.has_profile ? " - profile" : " - new"}
                        </option>
                    ))}
                </select>
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

            <details className="mt-4 text-xs text-[var(--ink-soft)]">
                <summary className="cursor-pointer select-none font-semibold">Session details</summary>
                <div className="mt-2 rounded-lg bg-[var(--surface-muted)] p-3 font-mono">
                    <div className="truncate">{sessionId}</div>
                </div>
            </details>

            <div className="mt-4 flex items-center gap-2 rounded-lg bg-[var(--sky-soft)] p-3 text-xs leading-5 text-[var(--sky)]">
                <UserRound className="h-4 w-4 shrink-0" />
                Profile-backed users are prioritized for the demo so homepage ranking can use behavior-derived profiles.
            </div>
        </section>
    );
}
