import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Fingerprint, LogOut, RefreshCcw, UserRound, XCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { getDemoUsers, getHealth, type DemoUser, type Persona } from "../lib/api";
import { useExperience } from "../state/experience";
import { StatusBadge } from "./StatusBadge";


function shortId(value: string) {
    return `...${value.slice(-10)}`;
}


function userPersona(user: DemoUser, personas: Persona[]) {
    return personas.find((persona) => user.user_id_hash.startsWith(`u_syn_${persona.persona_id}_`));
}


export function UserControlPanel() {
    const navigate = useNavigate();
    const { userIdHash, sessionId, setUserIdHash, resetSession } = useExperience();
    const healthQuery = useQuery({ queryKey: ["health"], queryFn: getHealth });
    const demoUsersQuery = useQuery({ queryKey: ["demo-users"], queryFn: getDemoUsers });
    const apiOnline = healthQuery.data?.ok === true;
    const activeUser = demoUsersQuery.data?.users.find((user) => user.user_id_hash === userIdHash);
    const activePersona = activeUser ? userPersona(activeUser, demoUsersQuery.data?.personas || []) : undefined;

    function changeShopper() {
        setUserIdHash(null);
        navigate("/login", { replace: true });
    }

    return (
        <section className="panel p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <Fingerprint className="h-5 w-5 text-[var(--mint)]" />
                    <div>
                        <p className="soft-label">Shopper context</p>
                        <h2 className="text-base font-medium text-[var(--ink-strong)]">Active account</h2>
                    </div>
                </div>
                <StatusBadge tone={apiOnline ? "mint" : "rose"}>
                    {apiOnline ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                    {apiOnline ? "API online" : "API offline"}
                </StatusBadge>
            </div>

            <div className="mb-4 rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-3">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <p className="text-xs font-medium text-[var(--ink-muted)]">Signed-in shopper</p>
                        <p className="mt-1 text-sm font-medium text-[var(--ink-strong)]">
                            {activeUser?.username || activeUser?.demo_label || "Loading shopper..."}
                        </p>
                        {userIdHash ? <p className="font-mono text-xs text-[var(--ink-muted)]">{shortId(userIdHash)}</p> : null}
                    </div>
                    <StatusBadge tone={activeUser?.has_profile ? "mint" : "amber"}>
                        {activeUser?.has_profile ? "Profile-backed" : "New user"}
                    </StatusBadge>
                </div>
                <p className="mt-2 text-xs leading-5 text-[var(--ink-soft)]">
                    {activeUser?.profile_status || "new"} profile. Clickstream is recorded for this account until you change shopper.
                </p>
                {activePersona ? (
                    <p className="mt-1 text-xs font-semibold text-[var(--violet)]">Persona: {activePersona.label}</p>
                ) : (
                    <p className="mt-1 text-xs font-semibold text-[var(--mint)]">Personal live-learning account</p>
                )}
            </div>

            <div className="grid grid-cols-2 gap-2">
                <button className="action-button action-button-secondary text-xs" onClick={() => resetSession()}>
                    <RefreshCcw className="h-3.5 w-3.5" />
                    New session
                </button>
                <button className="action-button action-button-secondary text-xs" onClick={changeShopper}>
                    <LogOut className="h-3.5 w-3.5" />
                    Change shopper
                </button>
            </div>

            <details className="mt-4 text-xs text-[var(--ink-soft)]">
                <summary className="cursor-pointer select-none font-semibold">Session details</summary>
                <div className="mt-2 rounded-lg bg-[var(--surface-muted)] p-3 font-mono">
                    <div className="truncate">{sessionId}</div>
                </div>
            </details>

            <div className="mt-4 flex items-center gap-2 rounded-lg bg-[var(--sky-soft)] p-3 text-xs leading-5 text-[var(--sky)]">
                <UserRound className="h-4 w-4 shrink-0" />
                Open Debug and apply captured behavior when you are ready to update this shopper's profile.
            </div>
        </section>
    );
}
