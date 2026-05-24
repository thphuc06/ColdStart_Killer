import { BarChart3, Home, Search, Sparkles } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

import { UserControlPanel } from "./UserControlPanel";


function navLinkClassName({ isActive }: { isActive: boolean }) {
    return `nav-link ${isActive ? "nav-link-active" : ""}`;
}


export function AppShell() {
    return (
        <div className="min-h-screen px-4 py-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-[1500px]">
                <div className="grid gap-5 xl:grid-cols-[320px,1fr]">
                    <aside className="space-y-4">
                        <div className="panel-strong overflow-hidden p-5">
                            <div className="flex items-center gap-3">
                                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--mint)] to-teal-600">
                                    <Sparkles className="h-5 w-5 text-white" />
                                </div>
                                <div>
                                    <h1 className="text-lg font-bold leading-tight text-[var(--ink-strong)]">Discover</h1>
                                    <p className="text-xs text-[var(--ink-soft)]">Personalized recommendations</p>
                                </div>
                            </div>
                        </div>
                        <UserControlPanel />
                    </aside>

                    <div className="space-y-5">
                        <header className="panel-strong flex items-center justify-between gap-4 p-4">
                            <nav className="flex flex-wrap gap-2">
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
                        </header>

                        <Outlet />
                    </div>
                </div>
            </div>
        </div>
    );
}