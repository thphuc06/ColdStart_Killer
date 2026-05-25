from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.behavior.onboarding import (
    complete_onboarding,
    get_onboarding_options,
    preview_onboarding_preferences,
)
from src.config import get_settings
from src.mongodb import get_clickstream_events_collection, get_items_collection, get_users_collection


router = APIRouter(prefix="/api/onboarding")


class OnboardingPreferencesRequest(BaseModel):
    user_id_hash: str | None = None
    selected_categories: list[str] = Field(default_factory=list)
    selected_price_buckets: list[str] = Field(default_factory=list)
    selected_intents: list[str] = Field(default_factory=list)
    selected_seed_item_ids: list[str] = Field(default_factory=list)


class CompleteOnboardingRequest(OnboardingPreferencesRequest):
    user_id_hash: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


def _disabled_response() -> dict[str, Any]:
    return {
        "ok": True,
        "enabled": False,
        "categories": [],
        "price_buckets": [],
        "intent_chips": [],
        "seed_items": [],
        "source": "disabled",
        "message": "Onboarding is disabled by ENABLE_ONBOARDING=false.",
    }


@router.get("/options")
def options() -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_onboarding:
        return _disabled_response()
    return get_onboarding_options(items_collection=get_items_collection(), settings=settings)


@router.post("/preview")
def preview(payload: OnboardingPreferencesRequest) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_onboarding:
        raise HTTPException(status_code=403, detail="Onboarding is disabled by ENABLE_ONBOARDING=false.")
    try:
        return preview_onboarding_preferences(
            payload.model_dump(),
            items_collection=get_items_collection(),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/complete")
def complete(payload: CompleteOnboardingRequest) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_onboarding:
        raise HTTPException(status_code=403, detail="Onboarding is disabled by ENABLE_ONBOARDING=false.")
    try:
        return complete_onboarding(
            payload.model_dump(),
            users_collection=get_users_collection(),
            clickstream_events_collection=get_clickstream_events_collection(),
            items_collection=get_items_collection(),
            settings=settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
