from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.mongodb import get_items_collection
from src.recommendation.candidate_sources import display_image_url, preferred_image_sources
from src.recommendation.similar_products import get_similar_products
from .request_guards import personalization_enabled_for_user


router = APIRouter(prefix="/api")


def _item_projection() -> dict[str, int]:
    return {
        "_id": 1,
        "title_en": 1,
        "brand": 1,
        "source_category": 1,
        "category_id": 1,
        "category_path": 1,
        "price_vnd": 1,
        "price_bucket": 1,
        "image_url": 1,
        "image_urls": 1,
        "quality_score": 1,
        "cold_start": 1,
        "description_enriched": 1,
        "source_text": 1,
        "text_stats": 1,
    }


@router.get("/items/{item_id}")
def get_item_detail(item_id: str, *, items_collection: Any | None = None) -> dict[str, Any]:
    if items_collection is None:
        items_collection = get_items_collection()
    doc = items_collection.find_one({"_id": item_id}, _item_projection())
    if not doc:
        raise HTTPException(status_code=404, detail="item not found")
    cold_start = doc.get("cold_start") if isinstance(doc.get("cold_start"), dict) else {}
    description = doc.get("description_enriched") if isinstance(doc.get("description_enriched"), dict) else {}
    source_text = doc.get("source_text") if isinstance(doc.get("source_text"), dict) else {}
    image_url, image_fallback_url = preferred_image_sources(doc)
    raw_gallery_urls = doc.get("image_urls") if isinstance(doc.get("image_urls"), list) else []
    gallery_urls = list(
        dict.fromkeys(
            display_image_url(str(url).strip())
            for url in raw_gallery_urls
            if isinstance(url, str) and url.strip()
        )
    )
    return {
        "item_id": doc.get("_id"),
        "title": doc.get("title_en", ""),
        "brand": doc.get("brand", ""),
        "source_category": doc.get("source_category", ""),
        "category_id": doc.get("category_id", ""),
        "category_path": list(doc.get("category_path", [])),
        "price_vnd": doc.get("price_vnd"),
        "price_bucket": doc.get("price_bucket", "unknown"),
        "image_url": image_url,
        "image_fallback_url": image_fallback_url,
        "image_urls": gallery_urls,
        "quality_score": doc.get("quality_score", 0.0),
        "cold_start": {
            "is_cold_item": bool(cold_start.get("is_cold_item", True)),
            "interaction_count": int(cold_start.get("interaction_count", 0) or 0),
        },
        "description_enriched": description,
        "source_text": {
            "description_text": str(source_text.get("description_text") or ""),
            "features_text": str(source_text.get("features_text") or ""),
            "details_text": str(source_text.get("details_text") or ""),
        },
        "text_stats": doc.get("text_stats") if isinstance(doc.get("text_stats"), dict) else {},
    }


@router.get("/items/{item_id}/similar")
def get_item_similar(
    item_id: str,
    user_id_hash: str = Query(..., min_length=1),
    session_id: str = Query(..., min_length=1),
    top_k: int = Query(12, ge=1, le=50),
) -> dict[str, Any]:
    effective_personalized = personalization_enabled_for_user(
        user_id_hash,
        personalized=True,
    )
    result = get_similar_products(
        user_id_hash=user_id_hash,
        session_id=session_id,
        source_item_id=item_id,
        top_k=top_k,
        personalized=effective_personalized,
    )
    result["user_id_hash"] = user_id_hash
    return result
