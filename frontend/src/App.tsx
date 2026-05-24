import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { DebugPage } from "./pages/DebugPage";
import { HomePage } from "./pages/HomePage";
import { ItemDetailPage } from "./pages/ItemDetailPage";
import { SearchPage } from "./pages/SearchPage";


export default function App() {
    return (
        <Routes>
            <Route element={<AppShell />}>
                <Route path="/" element={<HomePage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/items/:itemId" element={<ItemDetailPage />} />
                <Route path="/debug" element={<DebugPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}