from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.auth.dependencies import require_seller_or_admin
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


router = APIRouter(prefix="/api/seller")


def _require_enabled() -> Any:
    settings = get_settings()
    if not settings.enable_seller_tools:
        raise HTTPException(status_code=403, detail="Seller tools are disabled by ENABLE_SELLER_TOOLS=false.")
    return settings


@router.get("/drafts")
def list_drafts(seller_id: str | None = None, limit: int = Query(20, ge=1)) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_seller_tools:
        return seller_tools_disabled_response(settings)
    drafts = list_seller_drafts(
        drafts_collection=get_seller_product_drafts_collection(),
        seller_id=seller_id,
        limit=limit,
    )
    return {
        "ok": True,
        "enabled": True,
        "drafts": drafts,
        "required_confirmation": settings.seller_index_confirmation,
    }


@router.post("/drafts")
def create_draft(payload: SellerDraftPayload) -> dict[str, Any]:
    settings = _require_enabled()
    return create_seller_draft(
        payload.model_dump(),
        drafts_collection=get_seller_product_drafts_collection(),
        settings=settings,
    )


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str) -> dict[str, Any]:
    _require_enabled()
    try:
        return {"ok": True, "enabled": True, "draft": get_seller_draft(draft_id, drafts_collection=get_seller_product_drafts_collection())}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/drafts/{draft_id}/validate")
def validate_draft(draft_id: str) -> dict[str, Any]:
    _require_enabled()
    try:
        return validate_seller_draft(draft_id, drafts_collection=get_seller_product_drafts_collection())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/drafts/{draft_id}/index-preview")
def preview_indexing(draft_id: str) -> dict[str, Any]:
    settings = _require_enabled()
    try:
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
    _auth: AuthContext = Depends(require_seller_or_admin),
) -> dict[str, Any]:
    settings = _require_enabled()
    try:
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
