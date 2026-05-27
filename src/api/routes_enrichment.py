from __future__ import annotations

from dataclasses import replace
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import require_seller_or_admin
from src.auth.schemas import AuthContext
from src.config import get_settings
from src.enrichment.schemas import ApplyEnrichmentPayload
from src.enrichment.service import (
    apply_enrichment_to_draft,
    get_enrichment_request,
    preview_seller_draft_enrichment,
    request_web_enrichment_async,
    web_enrichment_disabled_response,
)
from src.seller.drafts import build_proposed_item_id, normalize_seller_payload
from src.seller.indexing_preview import preview_seller_draft_indexing
from src.seller.schemas import SellerDraftPayload
from src.utils import utc_now_iso
from src.mongodb import (
    get_seller_indexing_previews_collection,
    get_seller_product_drafts_collection,
    get_web_enrichment_requests_collection,
)

from .request_guards import enforce_seller_scope_for_doc, enforce_seller_scope_for_seller_id, require_seller_or_admin_for_seller_tools


router = APIRouter(prefix="/api/enrichment")


class _LivePreviewDraftCollection:
    def __init__(self, draft: dict[str, Any]) -> None:
        self._draft = dict(draft)

    def find_one(self, filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        if filter_doc.get("draft_id") == self._draft.get("draft_id"):
            return dict(self._draft)
        return None

    def update_one(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Live enrichment preview attempted a draft write.")


class _LivePreviewRequestCollection:
    def insert_one(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Live enrichment preview attempted a request write.")

    def update_one(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Live enrichment preview attempted a request write.")


def _require_seller_tools_enabled() -> Any:
    settings = get_settings()
    if not settings.enable_seller_tools:
        raise HTTPException(status_code=403, detail="Seller tools are disabled by ENABLE_SELLER_TOOLS=false.")
    return settings


@router.post("/live-preview")
async def live_preview(
    payload: SellerDraftPayload,
    include_indexing_preview: bool = False,
    _auth: AuthContext = Depends(require_seller_or_admin),
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.enable_web_enrichment_live_preview:
        return {
            "ok": True,
            "enabled": False,
            "status": "disabled",
            "message": "Live enrichment preview is disabled by ENABLE_WEB_ENRICHMENT_LIVE_PREVIEW=false.",
            "write_scope": [],
            "catalog_write_performed": False,
        }

    payload_data = normalize_seller_payload(payload.model_dump())
    effective_seller_id = enforce_seller_scope_for_seller_id(_auth, payload_data.get("seller_id"))
    if effective_seller_id is not None:
        payload_data["seller_id"] = effective_seller_id
    draft_id = f"live_preview_{uuid.uuid4().hex}"
    now = utc_now_iso()
    draft = {
        **payload_data,
        "draft_id": draft_id,
        "status": "draft",
        "validation_errors": [],
        "validation_warnings": [],
        "proposed_item_id": build_proposed_item_id(payload_data),
        "indexing_preview": None,
        "enrichment": {
            "status": "none",
            "latest_request_id": None,
            "applied_request_ids": [],
            "applied_fields": [],
            "source_urls": [],
        },
        "source": {"type": "seller", "seller_confirmed": False},
        "created_at": now,
        "updated_at": now,
    }

    try:
        response = await request_web_enrichment_async(
            draft_id,
            drafts_collection=_LivePreviewDraftCollection(draft),
            requests_collection=_LivePreviewRequestCollection(),
            settings=replace(settings, enable_web_enrichment=True),
            dry_run=True,
            wait_for_completion=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = {
        **response,
        "preview_only": True,
        "database_write_performed": False,
        "message": "Live preview only. Tavily and Qwen ran without persisting a draft or enrichment request.",
    }
    if not include_indexing_preview:
        return result

    request_doc = response.get("request") if isinstance(response.get("request"), dict) else {}
    synthesis = request_doc.get("synthesis") if isinstance(request_doc.get("synthesis"), dict) else {}
    enriched_description = str(synthesis.get("enriched_description") or "").strip()
    if not enriched_description:
        return {
            **result,
            "indexing_preview": None,
            "indexing_preview_error": "Full preview skipped because enrichment did not produce an accepted description.",
        }

    draft["description"] = enriched_description
    draft["enrichment"] = {
        "status": "applied",
        "latest_request_id": request_doc.get("request_id"),
        "applied_request_ids": [request_doc.get("request_id")] if request_doc.get("request_id") else [],
        "applied_fields": ["description"],
        "source_urls": [item.get("url") for item in request_doc.get("results") or [] if item.get("url")],
        "quality": synthesis.get("quality"),
        "model": synthesis.get("model"),
        "key_facts": synthesis.get("key_facts") or [],
    }
    try:
        indexing_response = preview_seller_draft_indexing(
            draft_id,
            drafts_collection=_LivePreviewDraftCollection(draft),
            previews_collection=_LivePreviewRequestCollection(),
            settings=settings,
            persist_preview=False,
        )
    except Exception as exc:
        return {
            **result,
            "indexing_preview": None,
            "indexing_preview_error": f"{exc.__class__.__name__}: {str(exc)[:240]}",
        }

    return {
        **result,
        "indexing_preview": indexing_response["preview"],
        "indexing_write_scope": indexing_response["write_scope"],
        "indexing_input_source": "enriched_description",
    }


@router.post("/seller-drafts/{draft_id}/preview")
def preview_seller_draft(
    draft_id: str,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_seller_tools_enabled()
    if not settings.enable_web_enrichment:
        return web_enrichment_disabled_response(settings)
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
async def request_seller_draft_enrichment(
    draft_id: str,
    wait: bool = False,
    _auth: AuthContext = Depends(require_seller_or_admin_for_seller_tools),
) -> dict[str, Any]:
    settings = _require_seller_tools_enabled()
    if not settings.enable_web_enrichment:
        return web_enrichment_disabled_response(settings)
    try:
        draft = get_seller_product_drafts_collection().find_one({"draft_id": draft_id})
        if not draft:
            raise LookupError(f"seller draft not found: {draft_id}")
        enforce_seller_scope_for_doc(_auth, dict(draft), resource_name="seller draft")
        return await request_web_enrichment_async(
            draft_id,
            drafts_collection=get_seller_product_drafts_collection(),
            requests_collection=get_web_enrichment_requests_collection(),
            settings=settings,
            wait_for_completion=wait,
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
    if not settings.enable_web_enrichment:
        return web_enrichment_disabled_response(settings)
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
            previews_collection=get_seller_indexing_previews_collection(),
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
