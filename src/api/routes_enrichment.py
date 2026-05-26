from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import require_seller_or_admin
from src.auth.schemas import AuthContext
from src.config import get_settings
from src.enrichment.schemas import ApplyEnrichmentPayload
from src.enrichment.service import (
    apply_enrichment_to_draft,
    get_enrichment_request,
    preview_seller_draft_enrichment,
    request_web_enrichment,
    web_enrichment_disabled_response,
)
from src.mongodb import get_seller_product_drafts_collection, get_web_enrichment_requests_collection


router = APIRouter(prefix="/api/enrichment")


def _settings_or_disabled() -> Any:
    settings = get_settings()
    if not settings.enable_seller_tools:
        return None
    return settings


@router.post("/seller-drafts/{draft_id}/preview")
def preview_seller_draft(draft_id: str) -> dict[str, Any]:
    settings = _settings_or_disabled()
    if settings is None:
        return web_enrichment_disabled_response(get_settings())
    try:
        return preview_seller_draft_enrichment(
            draft_id,
            drafts_collection=get_seller_product_drafts_collection(),
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/seller-drafts/{draft_id}/request")
def request_seller_draft_enrichment(
    draft_id: str,
    _auth: AuthContext = Depends(require_seller_or_admin),
) -> dict[str, Any]:
    settings = _settings_or_disabled()
    if settings is None:
        return web_enrichment_disabled_response(get_settings())
    try:
        return request_web_enrichment(
            draft_id,
            drafts_collection=get_seller_product_drafts_collection(),
            requests_collection=get_web_enrichment_requests_collection(),
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/requests/{request_id}")
def get_request(request_id: str) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "request": get_enrichment_request(
                request_id,
                requests_collection=get_web_enrichment_requests_collection(),
            ),
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/requests/{request_id}/apply")
def apply_request(
    request_id: str,
    payload: ApplyEnrichmentPayload,
    confirm: str | None = None,
    _auth: AuthContext = Depends(require_seller_or_admin),
) -> dict[str, Any]:
    settings = _settings_or_disabled()
    if settings is None:
        return web_enrichment_disabled_response(get_settings())
    try:
        return apply_enrichment_to_draft(
            request_id,
            fields_to_apply=payload.fields_to_apply,
            confirm=confirm,
            drafts_collection=get_seller_product_drafts_collection(),
            requests_collection=get_web_enrichment_requests_collection(),
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
