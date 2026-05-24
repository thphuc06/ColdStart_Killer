import { useEffect } from "react";

import { createEventId } from "./ids";
import type { RecommendationResponse, RecommendationSurface } from "./api";
import { postEvent } from "./api";
import { useExperience } from "../state/experience";


type UseImpressionLoggerParams = {
    response?: RecommendationResponse | null;
    surface: RecommendationSurface;
    userIdHash: string | null;
    sessionId: string;
    queryText?: string;
    metadata?: Record<string, unknown>;
    component: string;
};


export function useImpressionLogger(params: UseImpressionLoggerParams) {
    const { hasLoggedImpression, markImpressionLogged } = useExperience();

    useEffect(() => {
        if (!params.response || !params.userIdHash) {
            return;
        }

        const userIdHash = params.userIdHash;
        const { request_id, items } = params.response;
        const pending = items.filter((item) => !hasLoggedImpression(params.surface, request_id, item.item_id));
        if (!pending.length) {
            return;
        }

        let cancelled = false;

        void (async () => {
            for (const item of pending) {
                try {
                    await postEvent({
                        user_id_hash: userIdHash,
                        session_id: params.sessionId,
                        item_id: item.item_id,
                        event_type: "impression",
                        surface: params.surface,
                        request_id,
                        event_id: createEventId(),
                        query_text: params.queryText ?? "",
                        rank_position: item.rank_position,
                        client: {
                            component: params.component,
                            device_type: window.innerWidth < 900 ? "mobile" : "desktop",
                        },
                        metadata: params.metadata,
                    });
                    if (!cancelled) {
                        markImpressionLogged(params.surface, request_id, item.item_id);
                    }
                } catch (error) {
                    console.error("Failed to log impression", error);
                }
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [
        params.response,
        params.surface,
        params.userIdHash,
        params.sessionId,
        params.queryText,
        params.metadata,
        params.component,
        hasLoggedImpression,
        markImpressionLogged,
    ]);
}