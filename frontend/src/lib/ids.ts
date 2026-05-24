function uidSlice() {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
        return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
    }
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`.slice(0, 16);
}


export function createSessionId() {
    return `sess_ui_${uidSlice()}`;
}


export function createEventId() {
    return `evt_ui_${uidSlice()}`;
}