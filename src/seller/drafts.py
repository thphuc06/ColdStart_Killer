from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from src.config import Settings, get_settings
from src.seller.schemas import SellerDraftPayload
from src.utils import utc_now_iso


VALID_STATUSES_FOR_PREVIEW = {"validated", "previewed"}
VALID_STATUSES_FOR_INDEX = {"validated", "previewed", "approved"}


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _slug(value: str, *, fallback: str = "item") -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text[:64] or fallback


def derive_price_bucket(price_vnd: int | None) -> str:
    if price_vnd is None:
        return "unknown"
    if price_vnd < 100_000:
        return "under_100k"
    if price_vnd < 300_000:
        return "100k_300k"
    if price_vnd < 700_000:
        return "300k_700k"
    if price_vnd < 1_500_000:
        return "700k_1500k"
    return "over_1500k"


def build_proposed_item_id(payload: dict[str, Any]) -> str:
    seller_slug = _slug(str(payload.get("seller_id") or "seller"), fallback="seller")
    title_slug = _slug(str(payload.get("title") or "draft"), fallback="draft")
    digest_source = "|".join(
        [
            str(payload.get("seller_id") or ""),
            str(payload.get("title") or ""),
            str(payload.get("category_id") or ""),
            str(payload.get("price_vnd") or ""),
        ]
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:10]
    return f"seller_{seller_slug}_{title_slug}_{digest}"[:120]


def validate_seller_payload(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    title = str(payload.get("title") or "").strip()
    description = str(payload.get("description") or "").strip()
    category_id = str(payload.get("category_id") or "").strip()
    brand = str(payload.get("brand") or "").strip()
    image_url = str(payload.get("image_url") or "").strip()
    attributes = payload.get("attributes")

    if len(title) < 3:
        errors.append("title must be at least 3 characters")
    if len(description) < 20:
        errors.append("description must be at least 20 characters")
    if not category_id:
        errors.append("category_id is required")
    if payload.get("price_vnd") is not None and int(payload.get("price_vnd") or 0) < 0:
        errors.append("price_vnd must be >= 0")
    if attributes is not None and not isinstance(attributes, dict):
        errors.append("attributes must be an object")

    if not brand:
        warnings.append("brand is empty")
    if image_url and not image_url.startswith(("http://", "https://")):
        warnings.append("image_url should be an http(s) URL")
    if not payload.get("price_bucket") or str(payload.get("price_bucket")) == "unknown":
        warnings.append("price_bucket will be derived when price_vnd is available")
    return errors, warnings


def normalize_seller_payload(payload: dict[str, Any]) -> dict[str, Any]:
    model = SellerDraftPayload(**payload)
    data = _dump_model(model)
    data["seller_id"] = str(data.get("seller_id") or "seller_demo_001").strip()
    data["title"] = str(data.get("title") or "").strip()
    data["description"] = str(data.get("description") or "").strip()
    data["brand"] = str(data.get("brand") or "").strip()
    data["category_id"] = _slug(str(data.get("category_id") or ""), fallback="")
    data["price_bucket"] = str(data.get("price_bucket") or "").strip() or derive_price_bucket(data.get("price_vnd"))
    if data["price_bucket"] == "unknown" and data.get("price_vnd") is not None:
        data["price_bucket"] = derive_price_bucket(data.get("price_vnd"))
    data["image_url"] = str(data.get("image_url") or "").strip() or None
    data["attributes"] = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
    return data


def seller_tools_disabled_response(settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    return {
        "ok": True,
        "enabled": False,
        "drafts": [],
        "message": "Seller tools are disabled by ENABLE_SELLER_TOOLS=false.",
        "required_confirmation": active_settings.seller_index_confirmation,
    }


def sanitize_seller_draft(doc: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(doc)
    if "_id" in sanitized:
        sanitized["id"] = str(sanitized.pop("_id"))
    return sanitized


def create_seller_draft(
    payload: dict[str, Any],
    *,
    drafts_collection: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    data = normalize_seller_payload(payload)
    validation_errors, validation_warnings = validate_seller_payload(data)
    now = utc_now_iso()
    draft = {
        **data,
        "draft_id": f"draft_{uuid.uuid4().hex}",
        "status": "validated" if not validation_errors else "draft",
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "proposed_item_id": build_proposed_item_id(data),
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
        "approved_at": None,
        "indexed_at": None,
        "settings": {
            "seller_draft_max_preview_units": active_settings.seller_draft_max_preview_units,
        },
    }
    drafts_collection.insert_one(dict(draft))
    return {"ok": True, "enabled": True, "draft": sanitize_seller_draft(draft), "write_scope": ["seller_product_drafts"]}


def get_seller_draft(draft_id: str, *, drafts_collection: Any) -> dict[str, Any]:
    doc = drafts_collection.find_one({"draft_id": draft_id})
    if not doc:
        raise LookupError(f"seller draft not found: {draft_id}")
    return sanitize_seller_draft(dict(doc))


def list_seller_drafts(
    *,
    drafts_collection: Any,
    seller_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = {"seller_id": seller_id} if seller_id else {}
    cursor = drafts_collection.find(query)
    if hasattr(cursor, "sort"):
        cursor = cursor.sort("created_at", -1)
    if hasattr(cursor, "limit"):
        cursor = cursor.limit(max(1, min(int(limit), 50)))
    return [sanitize_seller_draft(dict(doc)) for doc in cursor]


def validate_seller_draft(draft_id: str, *, drafts_collection: Any) -> dict[str, Any]:
    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    errors, warnings = validate_seller_payload(draft)
    status = "validated" if not errors else "draft"
    updated_at = utc_now_iso()
    drafts_collection.update_one(
        {"draft_id": draft_id},
        {"$set": {"validation_errors": errors, "validation_warnings": warnings, "status": status, "updated_at": updated_at}},
    )
    draft.update({"validation_errors": errors, "validation_warnings": warnings, "status": status, "updated_at": updated_at})
    return {"ok": True, "enabled": True, "draft": sanitize_seller_draft(draft), "write_scope": ["seller_product_drafts"]}


def set_draft_failure(draft_id: str, *, drafts_collection: Any, error: str) -> None:
    drafts_collection.update_one(
        {"draft_id": draft_id},
        {
            "$set": {
                "status": "failed",
                "failure_error": error,
                "updated_at": utc_now_iso(),
            }
        },
    )
