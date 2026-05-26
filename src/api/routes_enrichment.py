from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.auth.schemas import AuthContext
from src.config import get_settings
from src.enrichment.schemas import ApplyEnrichmentPayload
from src.enrichment.service import (
    apply_enrichment_to_draft,
    get_enrichment_request,
    preview_seller_draft_enrichment,
    request_web_enrichment,
)
from src.mongodb import get_seller_product_drafts_collection, get_web_enrichment_requests_collection

from .request_guards import enforce_seller_scope_for_doc, require_seller_or_admin_for_seller_tools


router = APIRouter(prefix="/api/enrichment")


def _require_seller_tools_enabled() -> Any:
    settings = get_settings()
    if not settings.enable_seller_tools:
        raise HTTPException(status_code=403, detail="Seller tools are disabled by ENABLE_SELLER_TOOLS=false.")
    return settings


@router.post("/seller-drafts/{draft_id}/preview")
def preview_seller_draft(
    draft_id: str,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_seller_tools_enabled()
    try:
        draft = get_seller_product_drafts_collection().find_one({"draft_id": draft_id})
        if not draft:
            raise LookupError(f"seller draft not found: {draft_id}")
        enforce_seller_scope_for_doc(_auth, dict(draft), resource_name="seller draft")
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
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_seller_tools_enabled()
    try:
        draft = get_seller_product_drafts_collection().find_one({"draft_id": draft_id})
        if not draft:
            raise LookupError(f"seller draft not found: {draft_id}")
        enforce_seller_scope_for_doc(_auth, dict(draft), resource_name="seller draft")
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
def get_request(
    request_id: str,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    _require_seller_tools_enabled()
    try:
        request_doc = get_enrichment_request(
            request_id,
            requests_collection=get_web_enrichment_requests_collection(),
        )
        enforce_seller_scope_for_doc(_auth, request_doc, resource_name="enrichment request")
        return {
            "ok": True,
            "request": request_doc,
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/requests/{request_id}/apply")
def apply_request(
    request_id: str,
    payload: ApplyEnrichmentPayload,
    confirm: str | None = None,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_seller_tools_enabled()
    try:
        request_doc = get_enrichment_request(
            request_id,
            requests_collection=get_web_enrichment_requests_collection(),
        )
        enforce_seller_scope_for_doc(_auth, request_doc, resource_name="enrichment request")
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
