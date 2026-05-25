from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.behavior.event_logger import log_clickstream_event
from src.behavior.schemas import EventSurface, EventType
from .request_guards import clickstream_logging_enabled_for_user


router = APIRouter(prefix="/api")


class EventRequest(BaseModel):
    user_id_hash: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    event_type: EventType
    surface: EventSurface
    event_id: str | None = None
    request_id: str | None = None
    idempotency_key: str | None = None
    query_text: str = ""
    rank_position: int | None = None
    dwell_time_ms: int | None = None
    is_synthetic: bool = False
    client: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


@router.post("/events")
def post_event(payload: EventRequest) -> dict[str, Any]:
    if not clickstream_logging_enabled_for_user(payload.user_id_hash):
        return {
            "ok": True,
            "skipped": True,
            "reason": "clickstream_logging_disabled",
            "user_id_hash": payload.user_id_hash,
            "item_id": payload.item_id,
            "event_type": payload.event_type,
        }
    try:
        return log_clickstream_event(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
