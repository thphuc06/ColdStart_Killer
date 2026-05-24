import { createEventId } from "./ids";
import type { EventType, RecommendationCard, RecommendationSurface } from "./api";
import { postEvent } from "./api";


export type RecommendationOrigin = {
    surface: RecommendationSurface;
    requestId: string;
    rankPosition?: number;
    queryText?: string;
    sourceItemId?: string;
};


export function buildOriginFromCard(
    card: RecommendationCard,
    extras: { queryText?: string; sourceItemId?: string } = {},
): RecommendationOrigin {
    return {
        surface: card.surface,
        requestId: card.request_id,
        rankPosition: card.rank_position,
        queryText: extras.queryText,
        sourceItemId: extras.sourceItemId,
    };
}


export async function trackRecommendationAction(params: {
    userIdHash: string;
    sessionId: string;
    itemId: string;
    eventType: EventType;
    origin: RecommendationOrigin;
    queryText?: string;
    dwellTimeMs?: number;
    metadata?: Record<string, unknown>;
    clientComponent: string;
}) {
    const metadata = {
        ...(params.origin.sourceItemId ? { source_item_id: params.origin.sourceItemId } : {}),
        ...(params.metadata || {}),
    };

    return postEvent({
        user_id_hash: params.userIdHash,
        session_id: params.sessionId,
        item_id: params.itemId,
        event_type: params.eventType,
        surface: params.origin.surface,
        request_id: params.origin.requestId,
        event_id: createEventId(),
        query_text: params.queryText ?? params.origin.queryText ?? "",
        rank_position: params.origin.rankPosition,
        dwell_time_ms: params.dwellTimeMs,
        client: {
            component: params.clientComponent,
            device_type: window.innerWidth < 900 ? "mobile" : "desktop",
        },
        metadata,
    });
}