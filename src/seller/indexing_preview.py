from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from src.config import Settings, get_settings
from src.embeddings import embed_texts
from src.indexing import build_contextual_header, build_hype_units, build_proposition_units
from src.llm_hype import generate_hype_queries_llm
from src.llm_propositions import extract_propositions_llm
from src.recommendation.item_hype_profiles import build_profile_from_hype_units
from src.schemas import ColdStartState, DescriptionEnriched, ItemDocument, SourceText, TextStats, to_mongo_dict
from src.seller.drafts import VALID_STATUSES_FOR_PREVIEW, get_seller_draft, set_draft_failure, validate_seller_payload
from src.utils import utc_now_iso


PREVIEW_PIPELINE_VERSION = "seller_full_index_preview_v1"


def _matched_count(result: Any) -> int:
    try:
        return int(getattr(result, "matched_count", 1))
    except (TypeError, ValueError):
        return 1


def _word_count(text: str) -> int:
    return len([part for part in str(text or "").split() if part.strip()])


def _attributes_text(attributes: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in sorted(attributes.items()) if str(value).strip())


def _features_text(features: list[Any]) -> str:
    return "\n".join(str(feature).strip() for feature in features if str(feature).strip())


def _quality_score(title: str, description: str, features: list[Any], attributes: dict[str, Any]) -> float:
    words = _word_count(title) + _word_count(description) + _word_count(_features_text(features)) + _word_count(
        _attributes_text(attributes)
    )
    return round(min(0.95, max(0.25, words / 120)), 3)


def _quality_tier(score: float) -> str:
    if score >= 0.75:
        return "tier_A"
    if score >= 0.5:
        return "tier_B"
    if score >= 0.3:
        return "tier_C"
    return "tier_D"


def content_hash_for_draft(draft: dict[str, Any]) -> str:
    enrichment = draft.get("enrichment") if isinstance(draft.get("enrichment"), dict) else {}
    payload = {
        "proposed_item_id": draft.get("proposed_item_id"),
        "title": draft.get("title"),
        "brand": draft.get("brand"),
        "category_id": draft.get("category_id"),
        "description": draft.get("description"),
        "features": draft.get("features") or [],
        "attributes": draft.get("attributes") or {},
        "price_vnd": draft.get("price_vnd"),
        "price_bucket": draft.get("price_bucket"),
        "image_url": draft.get("image_url"),
        "enrichment": {
            "status": enrichment.get("status"),
            "latest_request_id": enrichment.get("latest_request_id"),
            "applied_fields": enrichment.get("applied_fields") or [],
            "source_urls": enrichment.get("source_urls") or [],
            "quality": enrichment.get("quality"),
            "model": enrichment.get("model"),
            "key_facts": enrichment.get("key_facts") or [],
        },
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_item_document_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    title = str(draft.get("title") or "").strip()
    description = str(draft.get("description") or "").strip()
    features = list(draft.get("features") or [])
    attributes = draft.get("attributes") if isinstance(draft.get("attributes"), dict) else {}
    features_text = _features_text(features)
    details_text = _attributes_text(attributes)
    combined_text = "\n".join(part for part in [title, features_text, description, details_text] if part)
    quality_score = _quality_score(title, description, features, attributes)
    enrichment = draft.get("enrichment") if isinstance(draft.get("enrichment"), dict) else {}
    has_applied_enrichment = enrichment.get("status") == "applied" and bool(enrichment.get("source_urls"))
    if has_applied_enrichment:
        description_enriched = DescriptionEnriched(
            source="tavily_llm_synthesis",
            enrichment_quality=str(enrichment.get("quality") or "low"),
            seller_confirmed=True,
            key_facts=list(enrichment.get("key_facts") or []),
            source_urls=list(enrichment.get("source_urls") or []),
            enrichment_note="Seller applied sourced web enrichment before indexing preview.",
        )
    else:
        description_enriched = DescriptionEnriched(
            source="seller_submitted",
            enrichment_quality="seller_provided",
            seller_confirmed=True,
            key_facts=[{"key": str(key), "value": value} for key, value in sorted(attributes.items())],
            enrichment_note="Seller-submitted product content confirmed during indexing approval.",
        )
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
        source_text=SourceText(
            description_text=description,
            features_text=features_text,
            details_text=details_text,
        ),
        text_stats=TextStats(
            title_words=_word_count(title),
            description_words=_word_count(description),
            features_words=_word_count(features_text),
            details_words=_word_count(details_text),
            combined_words=_word_count(combined_text),
        ),
        cold_start=ColdStartState(is_cold_item=True, interaction_count=0),
        description_enriched=description_enriched,
        created_at=now,
        updated_at=now,
    )
    return to_mongo_dict(item)


def build_full_indexing_bundle_from_draft(
    draft: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    active_settings = settings or get_settings()
    item_doc = build_item_document_from_draft(draft)
    propositions = extract_propositions_llm(item_doc)
    hype_queries = generate_hype_queries_llm(item_doc, propositions)
    if not propositions:
        raise ValueError("no proposition units generated for seller draft")
    if not hype_queries:
        raise ValueError("no HyPE queries generated for seller draft")
    embedding_texts = [f"{build_contextual_header(item_doc)} {query['raw_text']}" for query in hype_queries]
    embeddings = embed_texts(embedding_texts)
    if any(not isinstance(vector, list) or len(vector) != 1024 for vector in embeddings):
        raise ValueError("HyPE embeddings must contain 1024 dimensions")
    proposition_units = build_proposition_units(item_doc, propositions)
    hype_units = build_hype_units(item_doc, hype_queries, embeddings)
    retrieval_units = proposition_units + hype_units
    metadata = {
        "pipeline_version": PREVIEW_PIPELINE_VERSION,
        "llm_model": getattr(active_settings, "ollama_model", "qwen3:8b"),
        "embedding_model": getattr(active_settings, "embedding_model", "BAAI/bge-m3"),
        "proposition_units_generated": len(proposition_units),
        "hype_units_generated": len(hype_units),
        "vector_units_generated": len(hype_units),
    }
    return item_doc, retrieval_units, metadata


def _safe_unit_summary(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in unit.items()
        if key not in {"embedding", "embedding_text"}
    }


def build_seller_indexing_preview(
    draft: dict[str, Any],
    *,
    preview_id: str,
    content_hash: str,
    retrieval_units: list[dict[str, Any]],
    metadata: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    errors, warnings = validate_seller_payload(draft)
    displayed_units = [_safe_unit_summary(unit) for unit in retrieval_units[: active_settings.seller_draft_max_preview_units]]
    return {
        "preview_id": preview_id,
        "content_hash": content_hash,
        "preview_only": True,
        "catalog_write_performed": False,
        "valid": not errors and bool(retrieval_units) and metadata["vector_units_generated"] > 0,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "proposed_item_id": draft.get("proposed_item_id"),
        "estimated_retrieval_units": len(retrieval_units),
        "retrieval_units": displayed_units,
        "llm_model": metadata["llm_model"],
        "embedding_model": metadata["embedding_model"],
        "proposition_units_generated": metadata["proposition_units_generated"],
        "hype_units_generated": metadata["hype_units_generated"],
        "vector_units_generated": metadata["vector_units_generated"],
        "requires_hype_profile_rebuild": False,
        "message": "Full preview includes generated propositions, HyPE vectors, and a commit-ready private bundle.",
    }


def preview_seller_draft_indexing(
    draft_id: str,
    *,
    drafts_collection: Any,
    previews_collection: Any,
    settings: Settings | None = None,
    persist_preview: bool = True,
) -> dict[str, Any]:
    draft = get_seller_draft(draft_id, drafts_collection=drafts_collection)
    if draft.get("status") not in VALID_STATUSES_FOR_PREVIEW:
        errors, _warnings = validate_seller_payload(draft)
        if errors:
            raise ValueError("draft must be valid before indexing preview")
    content_hash = content_hash_for_draft(draft)
    preview_id = f"preview_{uuid.uuid4().hex}"
    try:
        item_doc, retrieval_units, metadata = build_full_indexing_bundle_from_draft(draft, settings=settings)
    except Exception as exc:
        if persist_preview:
            now = utc_now_iso()
            previews_collection.insert_one(
                {
                    "preview_id": preview_id,
                    "draft_id": draft_id,
                    "seller_id": draft.get("seller_id"),
                    "content_hash": content_hash,
                    "status": "failed",
                    "error": f"{exc.__class__.__name__}: {str(exc)[:180]}",
                    "created_at": now,
                    "updated_at": now,
                }
            )
        raise
    preview = build_seller_indexing_preview(
        draft,
        preview_id=preview_id,
        content_hash=content_hash,
        retrieval_units=retrieval_units,
        metadata=metadata,
        settings=settings,
    )
    now = utc_now_iso()
    artifact = {
        "preview_id": preview_id,
        "draft_id": draft_id,
        "seller_id": draft.get("seller_id"),
        "content_hash": content_hash,
        "status": "ready",
        "item_document": item_doc,
        "retrieval_units": retrieval_units,
        "metadata": metadata,
        "created_at": now,
        "updated_at": now,
    }
    if persist_preview:
        previous_summary = draft.get("indexing_preview") if isinstance(draft.get("indexing_preview"), dict) else None
        previews_collection.insert_one(dict(artifact))
        if previous_summary and previous_summary.get("preview_id"):
            previews_collection.update_one(
                {"preview_id": previous_summary["preview_id"], "status": "ready"},
                {"$set": {"status": "invalidated", "updated_at": now, "invalidated_reason": "superseded"}},
            )
        drafts_collection.update_one(
            {"draft_id": draft_id},
            {
                "$set": {
                    "indexing_preview": preview,
                    "status": "previewed",
                    "enrichment.requires_repreview": False,
                    "updated_at": now,
                }
            },
        )
    return {
        "ok": True,
        "enabled": True,
        "draft_id": draft_id,
        "preview": preview,
        "write_scope": ["seller_indexing_previews", "seller_product_drafts"] if persist_preview else [],
        "catalog_write_performed": False,
    }


def _collection_has_item(collection: Any, item_id: str) -> bool:
    return bool(collection.find_one({"_id": item_id}, {"_id": 1}))


def _collection_has_retrieval_units(collection: Any, item_id: str, units: list[dict[str, Any]]) -> bool:
    if hasattr(collection, "count_documents") and int(collection.count_documents({"item_id": item_id})) > 0:
        return True
    return any(collection.find_one({"_id": unit.get("_id")}, {"_id": 1}) for unit in units)


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


def _upsert_item_hype_profile(
    item_id: str,
    item_doc: dict[str, Any],
    retrieval_units: list[dict[str, Any]],
    *,
    item_hype_profiles_collection: Any,
    now: str,
) -> dict[str, Any]:
    hype_units = [unit for unit in retrieval_units if unit.get("unit_type") == "hype_question"]
    profile_doc, stats = build_profile_from_hype_units(item_id, hype_units, item_doc=item_doc, updated_at=now)
    if profile_doc is None:
        raise ValueError("; ".join(stats.errors) or "HyPE profile could not be built")
    doc = dict(profile_doc)
    doc_id = doc.pop("_id", item_id)
    item_hype_profiles_collection.update_one(
        {"_id": doc_id},
        {"$set": doc, "$setOnInsert": {"_id": doc_id}},
        upsert=True,
    )
    return {"status": "ready", "stats": stats.as_dict()}


def approve_and_index_seller_draft(
    draft_id: str,
    *,
    write: bool,
    confirm: str | None,
    drafts_collection: Any,
    previews_collection: Any,
    items_collection: Any,
    retrieval_units_collection: Any,
    item_hype_profiles_collection: Any | None = None,
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
    summary = draft.get("indexing_preview") if isinstance(draft.get("indexing_preview"), dict) else None
    if not summary or not summary.get("preview_id") or not item_id:
        raise ValueError("draft must have a persisted preview bundle before approve-index")
    artifact = previews_collection.find_one({"preview_id": summary["preview_id"]})
    if not artifact or artifact.get("status") != "ready":
        raise ValueError("indexing preview bundle is unavailable or invalidated")
    if artifact.get("content_hash") != content_hash_for_draft(draft) or summary.get("content_hash") != artifact.get("content_hash"):
        raise ValueError("indexing preview is stale; generate indexing preview again before approval")
    item_doc = dict(artifact.get("item_document") or {})
    retrieval_units = [dict(unit) for unit in artifact.get("retrieval_units") or []]
    if item_doc.get("_id") != item_id or not retrieval_units:
        raise ValueError("indexing preview bundle is incomplete")
    if _collection_has_item(items_collection, item_id):
        raise ValueError(f"item already exists: {item_id}")
    if _collection_has_retrieval_units(retrieval_units_collection, item_id, retrieval_units):
        raise ValueError(f"retrieval_units already exist for item: {item_id}")
    now = utc_now_iso()
    item_inserted = False
    retrieval_units_inserted = False
    artifact_committed = False
    try:
        items_collection.insert_one(item_doc)
        item_inserted = True
        retrieval_units_collection.insert_many(retrieval_units, ordered=True)
        retrieval_units_inserted = True
        preview_update_result = previews_collection.update_one(
            {"preview_id": artifact["preview_id"], "status": "ready"},
            {"$set": {"status": "committed", "committed_at": now, "updated_at": now}},
        )
        if _matched_count(preview_update_result) <= 0:
            raise ValueError("indexing preview bundle is no longer ready")
        artifact_committed = True
        draft_update_result = drafts_collection.update_one(
            {"draft_id": draft_id},
            {
                "$set": {
                    "status": "indexed",
                    "indexed_at": now,
                    "approved_at": now,
                    "updated_at": now,
                    "validation_warnings": warnings,
                    "source.seller_confirmed": True,
                    "indexing_preview.preview_only": False,
                    "indexing_preview.catalog_write_performed": True,
                    "indexing_preview.committed_at": now,
                    "indexing_preview.lineage": artifact.get("metadata") or {},
                }
            },
        )
        if _matched_count(draft_update_result) <= 0:
            raise RuntimeError("seller draft update failed during approve-index")
    except Exception as exc:
        rollback_errors = _rollback_catalog_writes(
            item_inserted=item_inserted,
            retrieval_units_inserted=retrieval_units_inserted,
            item_id=item_id,
            items_collection=items_collection,
            retrieval_units_collection=retrieval_units_collection,
        )
        if artifact_committed:
            previews_collection.update_one(
                {"preview_id": artifact["preview_id"], "status": "committed"},
                {"$set": {"status": "ready", "updated_at": now}},
            )
        error_message = str(exc)
        if rollback_errors:
            error_message = error_message + " | " + " | ".join(rollback_errors)
        set_draft_failure(draft_id, drafts_collection=drafts_collection, error=error_message)
        raise
    post_index_status: dict[str, Any]
    if item_hype_profiles_collection is None:
        post_index_status = {"item_hype_profile": "skipped", "retryable": True}
    else:
        try:
            profile_result = _upsert_item_hype_profile(
                item_id,
                item_doc,
                retrieval_units,
                item_hype_profiles_collection=item_hype_profiles_collection,
                now=now,
            )
            post_index_status = {"item_hype_profile": "ready", **profile_result}
        except Exception as exc:
            post_index_status = {
                "item_hype_profile": "failed",
                "retryable": True,
                "error": f"{exc.__class__.__name__}: {str(exc)[:180]}",
            }
    drafts_collection.update_one({"draft_id": draft_id}, {"$set": {"post_index_status": post_index_status, "updated_at": now}})
    return {
        "ok": True,
        "enabled": True,
        "write_performed": True,
        "catalog_write_performed": True,
        "draft_id": draft_id,
        "item_id": item_id,
        "preview_id": artifact["preview_id"],
        "inserted_items": 1,
        "inserted_retrieval_units": len(retrieval_units),
        "post_index_status": post_index_status,
        "writes": ["items", "retrieval_units", "seller_indexing_previews", "seller_product_drafts"]
        + (["item_hype_profiles"] if item_hype_profiles_collection is not None else []),
        "forbidden_writes_performed": [],
        "message": "Seller draft committed from the reviewed vector-ready preview bundle.",
    }
