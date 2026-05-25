import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Fingerprint, PlusCircle, SlidersHorizontal, Sparkles, UserRound, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { StatusBadge } from "../components/StatusBadge";
import { createUser, getDemoUsers, getHealth, type DemoUser, type DemoUsersResponse, type Persona } from "../lib/api";
import { useExperience } from "../state/experience";


type LoginLocationState = {
    from?: string;
};


function shortId(value: string) {
    return `...${value.slice(-10)}`;
}


function userPersona(user: DemoUser, personas: Persona[]) {
    return personas.find((persona) => user.user_id_hash.startsWith(`u_syn_${persona.persona_id}_`));
}


function userLabel(user: DemoUser, personas: Persona[]) {
    const persona = userPersona(user, personas);
    const name = user.username || user.demo_label || shortId(user.user_id_hash);
    return persona ? `${name} - persona: ${persona.label}` : name;
}


export function ShopperLoginPage() {
    const navigate = useNavigate();
    const location = useLocation();
    const queryClient = useQueryClient();
    const { setUserIdHash } = useExperience();
    const [selectedUserId, setSelectedUserId] = useState("");
    const [username, setUsername] = useState("");
    const healthQuery = useQuery({ queryKey: ["health"], queryFn: getHealth });
    const demoUsersQuery = useQuery({ queryKey: ["demo-users"], queryFn: getDemoUsers });
    const personas = demoUsersQuery.data?.personas || [];
    const users = demoUsersQuery.data?.users || [];
    const selectedUser = users.find((user) => user.user_id_hash === selectedUserId);
    const selectedPersona = selectedUser ? userPersona(selectedUser, personas) : undefined;
    const destination = (location.state as LoginLocationState | null)?.from || "/";
    const personalUsers = useMemo(
        () => users.filter((user) => user.demo_source === "user_created"),
        [users],
    );
    const seededUsers = useMemo(
        () => users.filter((user) => Boolean(userPersona(user, personas))),
        [personas, users],
    );
    const otherUsers = useMemo(
        () => users.filter((user) => user.demo_source !== "user_created" && !userPersona(user, personas)),
        [personas, users],
    );

    function enterShopper(userIdHash: string) {
        setUserIdHash(userIdHash);
        navigate(destination, { replace: true });
    }

    function startOnboarding(userIdHash: string) {
        setUserIdHash(userIdHash);
        navigate("/onboarding", { replace: true });
    }

    const createUserMutation = useMutation({
        mutationFn: () =>
            createUser({
                displayName: username.trim(),
                allow_personalization: true,
                allow_clickstream_logging: true,
            }),
        onSuccess: (user) => {
            queryClient.setQueryData<DemoUsersResponse>(["demo-users"], (current) => ({
                users: [user, ...(current?.users.filter((existing) => existing.user_id_hash !== user.user_id_hash) || [])],
                personas: current?.personas || [],
            }));
            startOnboarding(user.user_id_hash);
        },
    });

    return (
        <div className="app-shell min-h-screen">
            <header className="top-nav">
                <div className="page-wrap flex min-h-16 items-center gap-3">
                    <div className="brand-mark">
                        <Sparkles className="h-5 w-5" />
                    </div>
                    <div>
                        <h1 className="brand-title">ColdStart Killer</h1>
                        <p className="text-xs text-[var(--ink-soft)]">Select a shopper before recommendation tracking begins.</p>
                    </div>
                </div>
            </header>

            <main className="page-wrap pb-12">
                <section className="editorial-hero">
                    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr),360px] lg:items-center">
                        <div>
                            <p className="soft-label">Shopper sign in</p>
                            <h2 className="display-title mt-3">
                                Start a personalized shopping session
                            </h2>
                            <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--ink-soft)]">
                                Create a personal account for live behavior learning, or enter a seeded persona to inspect an
                                already learned profile and collaborative-filtering evidence.
                            </p>
                        </div>
                        <div className="signature-card signature-dark">
                            <StatusBadge tone={healthQuery.data?.ok ? "mint" : "rose"}>
                                {healthQuery.data?.ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
                                {healthQuery.data?.ok ? "API online" : "API offline"}
                            </StatusBadge>
                            <h3 className="mt-5 text-2xl font-normal leading-snug">Interaction-aware discovery</h3>
                            <p className="mt-3 text-sm leading-6">
                                Impressions and actions remain attached to the active shopper and recommendation request.
                            </p>
                        </div>
                    </div>
                </section>

                <div className="grid gap-5 lg:grid-cols-2">
                    <section className="panel p-6">
                        <div className="mb-5 flex items-center gap-3">
                            <PlusCircle className="h-6 w-6 text-[var(--mint)]" />
                            <div>
                                <p className="soft-label">Live learning</p>
                                <h3 className="text-xl font-medium text-[var(--ink-strong)]">Create personal shopper</h3>
                            </div>
                        </div>
                        <label className="mb-2 block text-sm font-medium text-[var(--ink-soft)]" htmlFor="new-shopper-name">
                            Shopper name
                        </label>
                        <input
                            className="form-input"
                            id="new-shopper-name"
                            maxLength={80}
                            placeholder="Example: Judge live demo"
                            value={username}
                            onChange={(event) => setUsername(event.target.value)}
                        />
                        <p className="mt-3 text-xs leading-5 text-[var(--ink-soft)]">
                            The name is saved as <strong>username</strong> in MongoDB. Your clicks, saves and carts are recorded
                            only for this shopper, then learned when you apply behavior.
                        </p>
                        <button
                            className="action-button action-button-primary mt-5 w-full"
                            disabled={!username.trim() || createUserMutation.isPending}
                            onClick={() => createUserMutation.mutate()}
                        >
                            <PlusCircle className="h-4 w-4" />
                            {createUserMutation.isPending ? "Creating account..." : "Create account and choose preferences"}
                        </button>
                        {createUserMutation.error ? (
                            <p className="mt-3 text-sm font-semibold text-[var(--rose)]">{String(createUserMutation.error)}</p>
                        ) : null}
                    </section>

                    <section className="panel p-6">
                        <div className="mb-5 flex items-center gap-3">
                            <Fingerprint className="h-6 w-6 text-[var(--violet)]" />
                            <div>
                                <p className="soft-label">Existing shoppers</p>
                                <h3 className="text-xl font-medium text-[var(--ink-strong)]">Select a saved profile</h3>
                            </div>
                        </div>
                        <label className="mb-2 block text-sm font-medium text-[var(--ink-soft)]" htmlFor="login-shopper">
                            Shopper account or seeded persona
                        </label>
                        <select
                            className="form-select"
                            id="login-shopper"
                            value={selectedUserId}
                            onChange={(event) => setSelectedUserId(event.target.value)}
                        >
                            <option value="">{demoUsersQuery.isLoading ? "Loading shoppers..." : "Choose a shopper..."}</option>
                            {personalUsers.length ? (
                                <optgroup label="Personal shopper accounts">
                                    {personalUsers.map((user) => (
                                        <option key={user.user_id_hash} value={user.user_id_hash}>
                                            {userLabel(user, personas)} - {user.profile_status}
                                        </option>
                                    ))}
                                </optgroup>
                            ) : null}
                            {seededUsers.length ? (
                                <optgroup label="Seeded persona scenarios">
                                    {seededUsers.map((user) => (
                                        <option key={user.user_id_hash} value={user.user_id_hash}>
                                            {userLabel(user, personas)} - {user.profile_status}
                                        </option>
                                    ))}
                                </optgroup>
                            ) : null}
                            {otherUsers.length ? (
                                <optgroup label="Other profiles">
                                    {otherUsers.map((user) => (
                                        <option key={user.user_id_hash} value={user.user_id_hash}>
                                            {userLabel(user, personas)} - {user.profile_status}
                                        </option>
                                    ))}
                                </optgroup>
                            ) : null}
                        </select>

                        {selectedUser ? (
                            <div className="mt-4 rounded-lg border border-[var(--line-soft)] bg-[var(--surface-muted)] p-3 text-sm">
                                <p className="font-medium text-[var(--ink-strong)]">{userLabel(selectedUser, personas)}</p>
                                <p className="mt-1 text-[var(--ink-soft)]">
                                    {selectedUser.profile_status} profile / {selectedUser.has_profile ? "learned behavior available" : "new shopper"}
                                </p>
                                {selectedPersona ? (
                                    <p className="mt-1 text-xs font-semibold text-[var(--violet)]">Seeded demo persona</p>
                                ) : null}
                            </div>
                        ) : (
                            <div className="mt-4 flex items-center gap-2 rounded-lg bg-[var(--sky-soft)] p-3 text-xs leading-5 text-[var(--sky)]">
                                <UserRound className="h-4 w-4 shrink-0" />
                                Seeded personas are for prepared demonstrations; create a shopper to demonstrate live learning.
                            </div>
                        )}

                        <button
                            className="action-button action-button-secondary mt-5 w-full"
                            disabled={!selectedUserId}
                            onClick={() => selectedUserId && enterShopper(selectedUserId)}
                        >
                            Enter as selected shopper
                        </button>
                        <button
                            className="action-button action-button-ghost mt-3 w-full"
                            disabled={!selectedUserId}
                            onClick={() => selectedUserId && startOnboarding(selectedUserId)}
                        >
                            <SlidersHorizontal className="h-4 w-4" />
                            Choose starter preferences
                        </button>
                    </section>
                </div>
            </main>
        </div>
    );
}
