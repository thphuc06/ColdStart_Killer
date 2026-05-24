import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { ExperienceProvider } from "./state/experience";
import "./styles.css";


const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
        },
    },
});


ReactDOM.createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={queryClient}>
        <ExperienceProvider>
            <BrowserRouter>
                <App />
            </BrowserRouter>
        </ExperienceProvider>
    </QueryClientProvider>,
);