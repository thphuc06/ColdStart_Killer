import { BarChart3, Home, Search, ShieldCheck, Sparkles } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { StatusBadge } from "./StatusBadge";
import { UserControlPanel } from "./UserControlPanel";


function navLinkClassName({ isActive }: { isActive: boolean }) {
    return `nav-link ${isActive ? "nav-link-active" : ""}`;
}


export function AppShell() {
    return (
        <div className="app-shell">
            <header className="top-nav">
                <div className="page-wrap flex min-h-[72px] items-center justify-between gap-4">
                    <div className="flex min-w-0 items-center gap-3">
                        <div className="brand-mark">
                            <Sparkles className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                                <h1 className="text-lg font-black tracking-tight text-[var(--ink-strong)]">
                                    ColdStart Killer
                                </h1>
                                <StatusBadge tone="mint">MongoDB Recommendation Engine</StatusBadge>
                            </div>
                            <p className="text-xs font-medium text-[var(--ink-soft)]">
                                HyPE retrieval, behavior signals, and item-item CF in one shopping demo.
                            </p>
                        </div>
                    </div>

                    <nav className="hidden items-center gap-1 md:flex">
                        <NavLink className={navLinkClassName} to="/">
                            <Home className="h-4 w-4" />
                            Home
                        </NavLink>
                        <NavLink className={navLinkClassName} to="/search">
                            <Search className="h-4 w-4" />
                            Search
                        </NavLink>
                        <NavLink className={navLinkClassName} to="/debug">
                            <BarChart3 className="h-4 w-4" />
                            Debug
                        </NavLink>
                    </nav>
                </div>
            </header>

            <div className="page-wrap py-6">
                <nav className="mb-4 flex gap-2 md:hidden">
                    <NavLink className={navLinkClassName} to="/">
                        <Home className="h-4 w-4" />
                        Home
                    </NavLink>
                    <NavLink className={navLinkClassName} to="/search">
                        <Search className="h-4 w-4" />
                        Search
                    </NavLink>
                    <NavLink className={navLinkClassName} to="/debug">
                        <BarChart3 className="h-4 w-4" />
                        Debug
                    </NavLink>
                </nav>

                <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr),320px]">
                    <main className="min-w-0">
                        <Outlet />
                    </main>
                    <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
                        <div className="panel p-4">
                            <div className="flex items-start gap-3">
                                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[var(--sky-soft)] text-[var(--sky)]">
                                    <ShieldCheck className="h-5 w-5" />
                                </div>
                                <div>
                                    <p className="text-sm font-bold text-[var(--ink-strong)]">Demo guardrails</p>
                                    <p className="mt-1 text-xs leading-5 text-[var(--ink-soft)]">
                                        Search stays query-first. CF badges only appear when behavior edges are present.
                                    </p>
                                </div>
                            </div>
                        </div>
                        <UserControlPanel />
                    </aside>
                </div>
            </div>
        </div>
    );
}
