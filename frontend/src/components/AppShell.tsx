import { BarChart3, Home, PackagePlus, Search, ShieldCheck, SlidersHorizontal, Sparkles } from "lucide-react";
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
                <div className="page-wrap flex min-h-16 items-center justify-between gap-5">
                    <div className="flex min-w-0 items-center gap-3">
                        <div className="brand-mark">
                            <Sparkles className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                                <h1 className="brand-title">ColdStart Killer</h1>
                                <StatusBadge tone="mint">MongoDB recommendations</StatusBadge>
                            </div>
                            <p className="hidden text-xs text-[var(--ink-soft)] sm:block">
                                Personalized shopping with visible recommendation evidence.
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
                        <NavLink className={navLinkClassName} to="/onboarding">
                            <SlidersHorizontal className="h-4 w-4" />
                            Preferences
                        </NavLink>
                        <NavLink className={navLinkClassName} to="/seller/drafts">
                            <PackagePlus className="h-4 w-4" />
                            Seller
                        </NavLink>
                        <NavLink className={navLinkClassName} to="/debug">
                            <BarChart3 className="h-4 w-4" />
                            Debug
                        </NavLink>
                    </nav>
                </div>
            </header>

            <div className="page-wrap py-8 lg:py-12">
                <nav className="mb-4 flex gap-2 md:hidden">
                    <NavLink className={navLinkClassName} to="/">
                        <Home className="h-4 w-4" />
                        Home
                    </NavLink>
                    <NavLink className={navLinkClassName} to="/search">
                        <Search className="h-4 w-4" />
                        Search
                    </NavLink>
                    <NavLink className={navLinkClassName} to="/onboarding">
                        <SlidersHorizontal className="h-4 w-4" />
                        Preferences
                    </NavLink>
                    <NavLink className={navLinkClassName} to="/seller/drafts">
                        <PackagePlus className="h-4 w-4" />
                        Seller
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
                        <div className="signature-card signature-forest p-5">
                            <div className="flex items-start gap-3">
                                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/20 text-white">
                                    <ShieldCheck className="h-5 w-5" />
                                </div>
                                <div>
                                    <p className="soft-label">Demo guardrails</p>
                                    <h3 className="mt-2 text-base font-medium">Tracked recommendations</h3>
                                    <p className="mt-2 text-xs leading-5">
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
