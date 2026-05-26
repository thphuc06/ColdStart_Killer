from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.auth.schemas import AuthContext
from src.config import get_settings
from src.mongodb import (
    get_items_collection,
    get_retrieval_units_collection,
    get_seller_product_drafts_collection,
)
from src.seller.drafts import (
    create_seller_draft,
    get_seller_draft,
    list_seller_drafts,
    seller_tools_disabled_response,
    validate_seller_draft,
)
from src.seller.indexing_preview import approve_and_index_seller_draft, preview_seller_draft_indexing
from src.seller.schemas import SellerDraftPayload

from .request_guards import enforce_seller_scope_for_doc, enforce_seller_scope_for_seller_id, require_seller_or_admin_for_seller_tools


router = APIRouter(prefix="/api/seller")


def _require_enabled() -> Any:
    settings = get_settings()
    if not settings.enable_seller_tools:
        raise HTTPException(status_code=403, detail="Seller tools are disabled by ENABLE_SELLER_TOOLS=false.")
    return settings


def _authorized_draft(draft_id: str, auth: AuthContext) -> dict[str, Any]:
    draft = get_seller_draft(draft_id, drafts_collection=get_seller_product_drafts_collection())
    enforce_seller_scope_for_doc(auth, draft, resource_name="seller draft")
    return draft


@router.get("/drafts")
def list_drafts(
    seller_id: str | None = None,
    limit: int = Query(20, ge=1),
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_seller_tools:
        return seller_tools_disabled_response(settings)
    effective_seller_id = enforce_seller_scope_for_seller_id(_auth, seller_id)
    drafts = list_seller_drafts(
        drafts_collection=get_seller_product_drafts_collection(),
        seller_id=effective_seller_id,
        limit=limit,
    )
    return {
        "ok": True,
        "enabled": True,
        "drafts": drafts,
        "required_confirmation": settings.seller_index_confirmation,
    }


@router.post("/drafts")
def create_draft(
    payload: SellerDraftPayload,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_enabled()
    payload_data = payload.model_dump()
    effective_seller_id = enforce_seller_scope_for_seller_id(_auth, payload_data.get("seller_id"))
    if effective_seller_id is not None:
        payload_data["seller_id"] = effective_seller_id
    return create_seller_draft(
        payload_data,
        drafts_collection=get_seller_product_drafts_collection(),
        settings=settings,
    )


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: str,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    _require_enabled()
    try:
        return {"ok": True, "enabled": True, "draft": _authorized_draft(draft_id, _auth)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/drafts/{draft_id}/validate")
def validate_draft(
    draft_id: str,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    _require_enabled()
    try:
        _authorized_draft(draft_id, _auth)
        return validate_seller_draft(draft_id, drafts_collection=get_seller_product_drafts_collection())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/drafts/{draft_id}/index-preview")
def preview_indexing(
    draft_id: str,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_enabled()
    try:
        _authorized_draft(draft_id, _auth)
        return preview_seller_draft_indexing(
            draft_id,
            drafts_collection=get_seller_product_drafts_collection(),
            settings=settings,
            persist_preview=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/drafts/{draft_id}/approve-index")
def approve_indexing(
    draft_id: str,
    write: bool = False,
    confirm: str | None = None,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_enabled()
    try:
        _authorized_draft(draft_id, _auth)
        return approve_and_index_seller_draft(
            draft_id,
            write=write,
            confirm=confirm,
            drafts_collection=get_seller_product_drafts_collection(),
            items_collection=get_items_collection(),
            retrieval_units_collection=get_retrieval_units_collection(),
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
