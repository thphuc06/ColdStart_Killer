import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { DebugPage } from "./pages/DebugPage";
import { HomePage } from "./pages/HomePage";
import { ItemDetailPage } from "./pages/ItemDetailPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { SearchPage } from "./pages/SearchPage";
import { SellerDraftPage } from "./pages/SellerDraftPage";
import { ShopperLoginPage } from "./pages/ShopperLoginPage";
import { useExperience } from "./state/experience";


function RequireShopper() {
    const { userIdHash } = useExperience();
    const location = useLocation();

    if (!userIdHash) {
        return <Navigate replace state={{ from: `${location.pathname}${location.search}` }} to="/login" />;
    }

    return <Outlet />;
}


export default function App() {
    return (
        <Routes>
            <Route path="/login" element={<ShopperLoginPage />} />
            <Route element={<RequireShopper />}>
                <Route element={<AppShell />}>
                    <Route path="/" element={<HomePage />} />
                    <Route path="/onboarding" element={<OnboardingPage />} />
                    <Route path="/seller/drafts" element={<SellerDraftPage />} />
                    <Route path="/search" element={<SearchPage />} />
                    <Route path="/items/:itemId" element={<ItemDetailPage />} />
                    <Route path="/debug" element={<DebugPage />} />
                </Route>
            </Route>
            <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
    );
}
