from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.behavior.event_logger import log_clickstream_event


router = APIRouter(prefix="/api")


class EventRequest(BaseModel):
    user_id_hash: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    surface: str = Field(min_length=1)
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
    return log_clickstream_event(**payload.model_dump())
