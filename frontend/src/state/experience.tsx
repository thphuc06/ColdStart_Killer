import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
    type PropsWithChildren,
} from "react";

import { createSessionId } from "../lib/ids";
import type { RecommendationSurface } from "../lib/api";


type SurfaceRequestState = {
    requestId: string | null;
    impressionsLogged: string[];
};

type ExperienceState = {
    userIdHash: string | null;
    sessionId: string;
    surfaces: Record<RecommendationSurface, SurfaceRequestState>;
};

type ExperienceContextValue = ExperienceState & {
    setUserIdHash: (userIdHash: string | null) => void;
    resetSession: () => void;
    hasLoggedImpression: (surface: RecommendationSurface, requestId: string, itemId: string) => boolean;
    markImpressionLogged: (surface: RecommendationSurface, requestId: string, itemId: string) => void;
};

const STORAGE_KEY = "coldstart-killer/frontend-state/v1";
const LOGIN_SESSION_KEY = "coldstart-killer/active-login/v1";

const emptySurfaceState = (): SurfaceRequestState => ({ requestId: null, impressionsLogged: [] });

const defaultState = (): ExperienceState => ({
    userIdHash: null,
    sessionId: createSessionId(),
    surfaces: {
        home: emptySurfaceState(),
        search: emptySurfaceState(),
        detail_similar: emptySurfaceState(),
    },
});

const ExperienceContext = createContext<ExperienceContextValue | null>(null);


function loadInitialState(): ExperienceState {
    if (typeof window === "undefined") {
        return defaultState();
    }

    try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (!raw) {
            return defaultState();
        }
        const parsed = JSON.parse(raw) as Partial<ExperienceState>;
        const base = defaultState();
        const hasActiveLogin = window.sessionStorage.getItem(LOGIN_SESSION_KEY) === "true";
        return {
            userIdHash: hasActiveLogin && typeof parsed.userIdHash === "string" ? parsed.userIdHash : null,
            sessionId: typeof parsed.sessionId === "string" && parsed.sessionId ? parsed.sessionId : base.sessionId,
            surfaces: {
                home: parsed.surfaces?.home || base.surfaces.home,
                search: parsed.surfaces?.search || base.surfaces.search,
                detail_similar: parsed.surfaces?.detail_similar || base.surfaces.detail_similar,
            },
        };
    } catch {
        return defaultState();
    }
}


export function ExperienceProvider({ children }: PropsWithChildren) {
    const [state, setState] = useState<ExperienceState>(loadInitialState);

    useEffect(() => {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    }, [state]);

    const setUserIdHash = useCallback((userIdHash: string | null) => {
        if (userIdHash) {
            window.sessionStorage.setItem(LOGIN_SESSION_KEY, "true");
        } else {
            window.sessionStorage.removeItem(LOGIN_SESSION_KEY);
        }
        setState((current) => ({
            ...current,
            userIdHash,
            sessionId: current.userIdHash === userIdHash ? current.sessionId : createSessionId(),
            surfaces: {
                home: emptySurfaceState(),
                search: emptySurfaceState(),
                detail_similar: emptySurfaceState(),
            },
        }));
    }, []);

    const resetSession = useCallback(() => {
        setState((current) => ({
            ...current,
            sessionId: createSessionId(),
            surfaces: {
                home: emptySurfaceState(),
                search: emptySurfaceState(),
                detail_similar: emptySurfaceState(),
            },
        }));
    }, []);

    const hasLoggedImpression = useCallback(
        (surface: RecommendationSurface, requestId: string, itemId: string) => {
            const currentSurface = state.surfaces[surface];
            if (currentSurface.requestId !== requestId) {
                return false;
            }
            return currentSurface.impressionsLogged.includes(itemId);
        },
        [state.surfaces],
    );

    const markImpressionLogged = useCallback((surface: RecommendationSurface, requestId: string, itemId: string) => {
        setState((current) => {
            const existing = current.surfaces[surface];
            const nextLogged = existing.requestId === requestId ? existing.impressionsLogged : [];
            if (existing.requestId === requestId && nextLogged.includes(itemId)) {
                return current;
            }
            return {
                ...current,
                surfaces: {
                    ...current.surfaces,
                    [surface]: {
                        requestId,
                        impressionsLogged: [...nextLogged, itemId],
                    },
                },
            };
        });
    }, []);

    const value = useMemo<ExperienceContextValue>(
        () => ({
            ...state,
            setUserIdHash,
            resetSession,
            hasLoggedImpression,
            markImpressionLogged,
        }),
        [state, setUserIdHash, resetSession, hasLoggedImpression, markImpressionLogged],
    );

    return <ExperienceContext.Provider value={value}>{children}</ExperienceContext.Provider>;
}


export function useExperience() {
    const context = useContext(ExperienceContext);
    if (!context) {
        throw new Error("useExperience must be used inside ExperienceProvider");
    }
    return context;
}
