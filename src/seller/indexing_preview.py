from __future__ import annotations

import hashlib
from typing import Any

from src.config import Settings, get_settings
from src.schemas import ColdStartState, DescriptionEnriched, ItemDocument, PropositionRetrievalUnit, SourceText, TextStats, to_mongo_dict
from src.seller.drafts import (
    VALID_STATUSES_FOR_INDEX,
    VALID_STATUSES_FOR_PREVIEW,
    get_seller_draft,
    set_draft_failure,
    validate_seller_payload,
)
from src.utils import utc_now_iso


def _word_count(text: str) -> int:
    return len([part for part in str(text or "").split() if part.strip()])


def _attributes_text(attributes: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in sorted(attributes.items()) if str(value).strip())


def _quality_score(title: str, description: str, attributes: dict[str, Any]) -> float:
    words = _word_count(title) + _word_count(description) + _word_count(_attributes_text(attributes))
    return round(min(0.95, max(0.25, words / 120)), 3)


def _quality_tier(score: float) -> str:
    if score >= 0.75:
        return "tier_A"
    if score >= 0.5:
        return "tier_B"
    if score >= 0.3:
        return "tier_C"
    return "tier_D"


def _unit_id(item_id: str, label: str, text: str) -> str:
    digest = hashlib.sha256(f"{item_id}|{label}|{text}".encode("utf-8")).hexdigest()[:12]
    return f"seller_prop_{item_id}_{label}_{digest}"[:180]


def build_item_document_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    title = str(draft.get("title") or "").strip()
    description = str(draft.get("description") or "").strip()
    attributes = draft.get("attributes") if isinstance(draft.get("attributes"), dict) else {}
    details_text = _attributes_text(attributes)
    combined_text = "\n".join(part for part in [title, description, details_text] if part)
    quality_score = _quality_score(title, description, attributes)
    item = ItemDocument(
        _id=str(draft["proposed_item_id"]),
        raw_parent_asin=str(draft["proposed_item_id"]),
        source_dataset="seller_drafts",
        source_file="seller_product_drafts",
        source_category=str(draft.get("category_id") or "seller"),
        title_en=title,
        brand=str(draft.get("brand") or ""),
        brand_source="seller",
        category_id=str(draft.get("category_id") or "seller"),
        category_path=[str(draft.get("category_id") or "seller")],
        raw_main_category=str(draft.get("category_id") or "seller"),
        price_vnd=draft.get("price_vnd"),
        price_parse_status="seller_provided" if draft.get("price_vnd") is not None else "missing",
        price_bucket=str(draft.get("price_bucket") or "unknown"),
        image_url=draft.get("image_url"),
        image_urls=[draft["image_url"]] if draft.get("image_url") else [],
        content_richness=quality_score,
        quality_score=quality_score,
        quality_tier=_quality_tier(quality_score),
        product_text_for_llm=combined_text,
        source_text=SourceText(description_text=description, details_text=details_text),
        text_stats=TextStats(
            title_words=_word_count(title),
            description_words=_word_count(description),
            details_words=_word_count(details_text),
            combined_words=_word_count(combined_text),
        ),
        cold_start=ColdStartState(is_cold_item=True, interaction_count=0),
        description_enriched=DescriptionEnriched(
            source="seller_submitted",
            enrichment_quality="seller_provided",
            seller_confirmed=True,
            key_facts=[{"key": str(key), "value": value} for key, value in sorted(attributes.items())],
            enrichment_note="Seller-submitted product. HyPE/item profile rebuild is a separate reviewed step.",
        ),
        created_at=now,
        updated_at=now,
    )
    return to_mongo_dict(item)


def build_retrieval_units_preview_from_draft(
    draft: dict[str, Any],
    *,
    settings: Settings | None = None,
    final: bool = False,
) -> list[dict[str, Any]]:
    active_settings = settings or get_settings()
    item_id = str(draft["proposed_item_id"])
    title = str(draft.get("title") or "").strip()
    description = str(draft.get("description") or "").strip()
    attributes = draft.get("attributes") if isinstance(draft.get("attributes"), dict) else {}
    candidate_texts: list[tuple[str, str, str]] = [
        ("title", title, "title"),
        ("description", description, "description"),
    ]
    for key, value in sorted(attributes.items()):
        text = f"{key}: {value}".strip()
        if text and len(candidate_texts) < active_settings.seller_draft_max_preview_units:
            candidate_texts.append(("attribute", text, f"attribute_{key}"))

    units: list[dict[str, Any]] = []
    for index, (prop_type, raw_text, source_field) in enumerate(candidate_texts):
        if not raw_text:
            continue
        unit = PropositionRetrievalUnit(
            _id=_unit_id(item_id, str(index), raw_text),
            item_id=item_id,
            raw_text=raw_text,
            proposition_type=prop_type,
            text_search=raw_text,
            item_title_en=title,
            item_brand=str(draft.get("brand") or ""),
            source_field=source_field,
            confidence=1.0 if final else 0.8,
            source="seller_submitted",
            category_id=str(draft.get("category_id") or "seller"),
            price_vnd=draft.get("price_vnd"),
            price_bucket=str(draft.get("price_bucket") or "unknown"),
            in_stock=True,
            is_cold_item=True,
            seller_confirmed=final,
            generation_model="seller_text_v1",
            generation_prompt_version="seller_draft_text_v1",
        )
        units.append(to_mongo_dict(unit))
    return units[: active_settings.seller_draft_max_preview_units]


def build_seller_indexing_preview(draft: dict[str, Any], *, settings: Settings | None = None) -> dict[str, Any]:
    units = build_retrieval_units_preview_from_draft(draft, settings=settings, final=False)
    errors, warnings = validate_seller_payload(draft)
    return {
        "preview_only": True,
        "catalog_write_performed": False,
        "valid": not errors and bool(units),
        "validation_errors": errors,
        "validation_warnings": warnings,
        "proposed_item_id": draft.get("proposed_item_id"),
        "estimated_retrieval_units": len(units),
        "retrieval_units": units,
        "embedding_model": None,
        "vector_units_generated": 0,
        "requires_hype_profile_rebuild": True,
        "message": (
            "Preview uses seller-provided text proposition units only. HyPE vectors and item_hype_profiles "
            "are a separate reviewed rebuild step."
        ),
    }


def preview_seller_draft_indexing(
    draft_id: str,
    *,
    drafts_collection: Any,
    settings: Settings | None = None,
    persist_preview: bool = True,
) -> dict[str, Any]:
    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    if draft.get("status") not in VALID_STATUSES_FOR_PREVIEW:
        errors, _warnings = validate_seller_payload(draft)
        if errors:
            raise ValueError("draft must be valid before indexing preview")
    preview = build_seller_indexing_preview(draft, settings=settings)
    if persist_preview:
        drafts_collection.update_one(
            {"draft_id": draft_id},
            {"$set": {"indexing_preview": preview, "status": "previewed", "updated_at": utc_now_iso()}},
        )
    return {
        "ok": True,
        "enabled": True,
        "draft_id": draft_id,
        "preview": preview,
        "write_scope": ["seller_product_drafts"] if persist_preview else [],
        "catalog_write_performed": False,
    }


def _collection_has_item(collection: Any, item_id: str) -> bool:
    return bool(collection.find_one({"_id": item_id}, {"_id": 1}))


def _collection_has_retrieval_units(collection: Any, item_id: str) -> bool:
    if hasattr(collection, "count_documents"):
        return int(collection.count_documents({"item_id": item_id})) > 0
    return bool(collection.find_one({"item_id": item_id}, {"_id": 1}))


def _delete_one_for_rollback(collection: Any, filter_doc: dict[str, Any]) -> None:
    if hasattr(collection, "delete_one"):
        collection.delete_one(filter_doc)
        return
    if hasattr(collection, "delete_many"):
        collection.delete_many(filter_doc)
        return
    raise RuntimeError("collection does not support delete_one rollback")


def _delete_many_for_rollback(collection: Any, filter_doc: dict[str, Any]) -> None:
    if hasattr(collection, "delete_many"):
        collection.delete_many(filter_doc)
        return
    if hasattr(collection, "delete_one"):
        while collection.find_one(filter_doc, {"_id": 1}):
            collection.delete_one(filter_doc)
        return
    raise RuntimeError("collection does not support delete_many rollback")


def _rollback_catalog_writes(
    *,
    item_inserted: bool,
    retrieval_units_inserted: bool,
    item_id: str,
    items_collection: Any,
    retrieval_units_collection: Any,
) -> list[str]:
    rollback_errors: list[str] = []
    if retrieval_units_inserted:
        try:
            _delete_many_for_rollback(retrieval_units_collection, {"item_id": item_id})
        except Exception as exc:
            rollback_errors.append(f"retrieval_units rollback failed: {exc}")
    if item_inserted:
        try:
            _delete_one_for_rollback(items_collection, {"_id": item_id})
        except Exception as exc:
            rollback_errors.append(f"item rollback failed: {exc}")
    return rollback_errors


def approve_and_index_seller_draft(
    draft_id: str,
    *,
    write: bool,
    confirm: str | None,
    drafts_collection: Any,
    items_collection: Any,
    retrieval_units_collection: Any,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not write:
        raise PermissionError("approve-index requires write=true")
    if confirm != active_settings.seller_index_confirmation:
        raise PermissionError(f"approve-index requires confirm={active_settings.seller_index_confirmation}")

    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    if draft.get("status") != "previewed":
        raise ValueError("draft must be previewed before approve-index")
    errors, warnings = validate_seller_payload(draft)
    if errors:
        raise ValueError("draft has validation errors: " + "; ".join(errors))

    item_id = str(draft.get("proposed_item_id") or "")
    preview = draft.get("indexing_preview") if isinstance(draft.get("indexing_preview"), dict) else None
    if not preview or preview.get("proposed_item_id") != item_id or preview.get("preview_only") is not True:
        raise ValueError("draft must have a persisted preview before approve-index")
    if not item_id:
        raise ValueError("draft is missing proposed_item_id")
    if _collection_has_item(items_collection, item_id):
        raise ValueError(f"item already exists: {item_id}")
    if _collection_has_retrieval_units(retrieval_units_collection, item_id):
        raise ValueError(f"retrieval_units already exist for item: {item_id}")

    item_doc = build_item_document_from_draft(draft)
    retrieval_units = build_retrieval_units_preview_from_draft(draft, settings=active_settings, final=True)
    if not retrieval_units:
        raise ValueError("no retrieval units generated from seller draft")

    now = utc_now_iso()
    item_inserted = False
    retrieval_units_inserted = False
    try:
        items_collection.insert_one(item_doc)
        item_inserted = True
        retrieval_units_collection.insert_many(retrieval_units, ordered=True)
        retrieval_units_inserted = True
        drafts_collection.update_one(
            {"draft_id": draft_id},
            {
                "$set": {
                    "status": "indexed",
                    "indexed_at": now,
                    "approved_at": now,
                    "updated_at": now,
                    "validation_warnings": warnings,
                    "source.seller_confirmed": True,
                    "indexing_preview": {
                        "preview_only": False,
                        "catalog_write_performed": True,
                        "proposed_item_id": item_id,
                        "estimated_retrieval_units": len(retrieval_units),
                        "retrieval_units": retrieval_units,
                        "requires_hype_profile_rebuild": True,
                    },
                }
            },
        )
    except Exception as exc:
        rollback_errors = _rollback_catalog_writes(
            item_inserted=item_inserted,
            retrieval_units_inserted=retrieval_units_inserted,
            item_id=item_id,
            items_collection=items_collection,
            retrieval_units_collection=retrieval_units_collection,
        )
        error_message = str(exc)
        if rollback_errors:
            error_message = error_message + " | " + " | ".join(rollback_errors)
        set_draft_failure(draft_id, drafts_collection=drafts_collection, error=error_message)
        raise

    return {
        "ok": True,
        "enabled": True,
        "write_performed": True,
        "catalog_write_performed": True,
        "draft_id": draft_id,
        "item_id": item_id,
        "inserted_items": 1,
        "inserted_retrieval_units": len(retrieval_units),
        "writes": ["items", "retrieval_units", "seller_product_drafts"],
        "forbidden_writes_performed": [],
        "message": "Seller draft indexed additively. Run separate reviewed HyPE/item profile rebuild if vector exposure is required.",
    }

