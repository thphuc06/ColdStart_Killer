import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";


const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendDir = path.resolve(__dirname, "..");
const repoRoot = path.resolve(frontendDir, "..");
const artifactDir = path.resolve(repoRoot, ".runtime", "phase11_smoke");

const apiBaseUrl = (process.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const frontendBaseUrl = (process.env.FRONTEND_BASE_URL || "http://127.0.0.1:4173").replace(/\/$/, "");
const searchQuery = process.env.PHASE11_SMOKE_QUERY || "wireless charger under 300k";


async function fetchJson(url, init) {
    const response = await fetch(url, {
        headers: {
            Accept: "application/json",
            ...(init?.body ? { "Content-Type": "application/json" } : {}),
            ...(init?.headers || {}),
        },
        ...init,
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
        throw new Error(`HTTP ${response.status} for ${url}: ${typeof payload === "string" ? payload : JSON.stringify(payload)}`);
    }
    return payload;
}

async function pollDebugUser(userIdHash) {
    for (let attempt = 0; attempt < 10; attempt += 1) {
        const payload = await fetchJson(`${apiBaseUrl}/api/debug/user/${encodeURIComponent(userIdHash)}`);
        if ((payload.recent_events?.length || 0) > 0) {
            return payload;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    return fetchJson(`${apiBaseUrl}/api/debug/user/${encodeURIComponent(userIdHash)}`);
}


async function main() {
    await rm(artifactDir, { recursive: true, force: true });
    await mkdir(artifactDir, { recursive: true });

    const health = await fetchJson(`${apiBaseUrl}/api/health`);
    const createdUser = await fetchJson(`${apiBaseUrl}/api/users`, {
        method: "POST",
        body: JSON.stringify({
            allow_personalization: true,
            allow_clickstream_logging: true,
        }),
    });

    const userIdHash = createdUser.user_id_hash;
    const sessionId = `sess_ui_phase11_smoke_${Date.now()}`;
    const homePayload = await fetchJson(
        `${apiBaseUrl}/api/feed/home?user_id_hash=${encodeURIComponent(userIdHash)}&session_id=${encodeURIComponent(sessionId)}&top_k=20&personalized=true`,
    );
    console.log("[phase11-smoke] homepage API ready");
    if (!homePayload.items?.length) {
        throw new Error(`Homepage feed returned no items for smoke user ${userIdHash}.`);
    }

    const searchPayload = await fetchJson(
        `${apiBaseUrl}/api/search?user_id_hash=${encodeURIComponent(userIdHash)}&session_id=${encodeURIComponent(sessionId)}&q=${encodeURIComponent(searchQuery)}&top_k=20&personalized=true`,
    );
    if (!searchPayload.items?.length) {
        throw new Error(`Search returned no items for query: ${searchQuery}`);
    }
    console.log("[phase11-smoke] search API ready");

    const anchorItemId = homePayload.items[0].item_id;
    const detailPayload = await fetchJson(`${apiBaseUrl}/api/items/${encodeURIComponent(anchorItemId)}`);
    const similarPayload = await fetchJson(
        `${apiBaseUrl}/api/items/${encodeURIComponent(anchorItemId)}/similar?user_id_hash=${encodeURIComponent(userIdHash)}&session_id=${encodeURIComponent(sessionId)}&top_k=12`,
    );
    console.log("[phase11-smoke] detail API ready");
    if (!detailPayload.item_id || detailPayload.item_id !== anchorItemId) {
        throw new Error("Item detail response did not include item_id.");
    }
    if (!similarPayload.items?.length) {
        throw new Error(`Similar products returned no items for item ${detailPayload.item_id}.`);
    }

    await fetchJson(`${apiBaseUrl}/api/events`, {
        method: "POST",
        body: JSON.stringify({
            user_id_hash: userIdHash,
            session_id: sessionId,
            item_id: homePayload.items[0].item_id,
            event_type: "click",
            surface: "home",
            request_id: homePayload.request_id,
            rank_position: homePayload.items[0].rank_position,
            is_synthetic: true,
            client: {
                component: "phase11-smoke-home",
                device_type: "desktop",
            },
        }),
    });
    await fetchJson(`${apiBaseUrl}/api/events`, {
        method: "POST",
        body: JSON.stringify({
            user_id_hash: userIdHash,
            session_id: sessionId,
            item_id: searchPayload.items[0].item_id,
            event_type: "click",
            surface: "search",
            request_id: searchPayload.request_id,
            query_text: searchQuery,
            rank_position: searchPayload.items[0].rank_position,
            is_synthetic: true,
            client: {
                component: "phase11-smoke-search",
                device_type: "desktop",
            },
        }),
    });
    console.log("[phase11-smoke] event logging ready");

    const debugPayload = await pollDebugUser(userIdHash);
    console.log("[phase11-smoke] debug API ready");
    const result = {
        ok: (debugPayload.recent_events?.length || 0) > 0,
        apiBaseUrl,
        frontendBaseUrl,
        health,
        userIdHash,
        sessionId,
        homeItemCount: homePayload.items?.length || 0,
        searchItemCount: searchPayload.items?.length || 0,
        similarItemCount: similarPayload.items?.length || 0,
        recentEventCount: debugPayload.recent_events?.length || 0,
        recentLogCount: debugPayload.recent_logs?.length || 0,
        signalCount: debugPayload.signals?.length || 0,
        artifactDir,
    };

    await writeFile(path.join(artifactDir, "result.json"), `${JSON.stringify(result, null, 2)}\n`);

    console.log(JSON.stringify(result, null, 2));

    if (!result.ok) {
        process.exitCode = 1;
    }
}


await main();