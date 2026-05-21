from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import pandas as pd
from pymongo import UpdateOne

from .config import get_settings
from .embeddings import embed_texts, estimate_vector_memory
from .llm_hype import generate_hype_queries_llm
from .llm_propositions import extract_propositions_llm
from .mongodb import get_items_collection, get_retrieval_units_collection
from .normalize_amazon import clean_string, slugify_category
from .schemas import HypeRetrievalUnit, ItemDocument, PropositionRetrievalUnit, SourceText, TextStats, to_mongo_dict
from .utils import coerce_list, parse_jsonish, utc_now_iso


logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
DEV_LIMIT = 500
M0_SAFE_LIMIT = 3000
DEDICATED_FULL_LIMIT = 5000


def _as_dict(row: dict | pd.Series) -> dict:
    return row.to_dict() if hasattr(row, "to_dict") else dict(row)


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_text_block(value: Any) -> str:
    if value is None:
        return ""
    lines = [clean_string(line) for line in str(value).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _list_from_cell(value: Any) -> list[str]:
    parsed = parse_jsonish(value)
    if isinstance(parsed, list):
        return [str(item) for item in parsed if str(item).strip()]
    if isinstance(parsed, tuple):
        return [str(item) for item in parsed if str(item).strip()]
    if isinstance(parsed, dict):
        return [str(item) for item in parsed.values() if str(item).strip()]
    return [str(item) for item in coerce_list(value) if str(item).strip()]


def build_item_doc_from_mvp_row(row: dict) -> dict:
    data = _as_dict(row)
    now = utc_now_iso()
    parent_asin = clean_string(data.get("parent_asin"))
    category_path = _list_from_cell(data.get("category_path")) or [clean_string(data.get("main_category"))]
    image_urls = _list_from_cell(data.get("image_urls"))
    image_url = clean_string(data.get("primary_image_url")) or (image_urls[0] if image_urls else None)
    doc = ItemDocument(
        _id=parent_asin,
        raw_parent_asin=parent_asin,
        source_file="analysis/mvp_3000_items_diverse.csv",
        source_category=clean_string(data.get("source_category")) or clean_string(data.get("category_key")) or "unknown",
        title_en=clean_string(data.get("title")),
        brand=clean_string(data.get("brand_candidate")),
        brand_source=clean_string(data.get("brand_source")) or "none",
        category_id=clean_string(data.get("category_id")) or slugify_category(data.get("main_category")),
        category_path=category_path,
        raw_main_category=clean_string(data.get("main_category")) or (category_path[0] if category_path else ""),
        price_usd=_coerce_float(data.get("price_usd")),
        price_vnd=_coerce_int(data.get("price_vnd")),
        price_parse_status=clean_string(data.get("price_parse_status")) or "missing",
        price_bucket=clean_string(data.get("price_bucket")) or "unknown",
        image_url=image_url,
        image_urls=image_urls,
        content_richness=_coerce_float(data.get("content_richness")) or 0.0,
        quality_score=_coerce_float(data.get("quality_score")) or 0.0,
        quality_tier=clean_string(data.get("quality_tier")) or "tier_D",
        product_text_for_llm=_clean_text_block(data.get("product_text_for_llm")),
        source_text=SourceText(
            description_text=_clean_text_block(data.get("description_text")),
            features_text=_clean_text_block(data.get("features_text")),
            details_text=_clean_text_block(data.get("details_text")),
        ),
        text_stats=TextStats(
            title_words=_coerce_int(data.get("title_words")) or 0,
            description_words=_coerce_int(data.get("description_words")) or 0,
            features_words=_coerce_int(data.get("features_words")) or 0,
            details_words=_coerce_int(data.get("details_words")) or 0,
            combined_words=_coerce_int(data.get("combined_words")) or 0,
        ),
        created_at=now,
        updated_at=now,
    )
    return to_mongo_dict(doc)


def build_contextual_header(item: dict) -> str:
    parts = [
        f"Category: {item.get('raw_main_category') or item.get('category_id')}",
        f"Brand: {item.get('brand') or 'unknown'}",
        f"Price bucket: {item.get('price_bucket') or 'unknown'}",
    ]
    return "[" + " | ".join(parts) + "]"


def build_proposition_units(item: dict, propositions: list[dict]) -> list[dict]:
    settings = get_settings()
    units = []
    for prop in propositions:
        raw_text = clean_string(prop.get("raw_text"))
        if not raw_text:
            continue
        unit = PropositionRetrievalUnit(
            _id=str(uuid.uuid4()),
            item_id=item["_id"],
            raw_text=raw_text,
            proposition_type=clean_string(prop.get("proposition_type")) or "spec",
            text_search=raw_text,
            item_title_en=item.get("title_en", ""),
            item_brand=item.get("brand", ""),
            confidence=float(prop.get("confidence", 0.0)),
            source=clean_string(prop.get("source")) or "llm",
            source_field=clean_string(prop.get("source_field")) or "mixed",
            category_id=item.get("category_id", ""),
            price_vnd=item.get("price_vnd"),
            price_bucket=item.get("price_bucket", "unknown"),
            in_stock=bool(item.get("in_stock", True)),
            is_cold_item=bool(item.get("cold_start", {}).get("is_cold_item", True)),
            seller_confirmed=bool(item.get("description_enriched", {}).get("seller_confirmed", False)),
            generation_model=settings.ollama_model,
            generation_prompt_version="proposition_v1",
        )
        units.append(to_mongo_dict(unit))
    return units


def build_hype_units(item: dict, hype_queries: list[dict], embeddings: list[list[float]]) -> list[dict]:
    if len(hype_queries) != len(embeddings):
        raise ValueError("hype_queries and embeddings must have the same length")
    settings = get_settings()
    header = build_contextual_header(item)
    units = []
    for query, embedding in zip(hype_queries, embeddings, strict=True):
        raw_text = clean_string(query.get("raw_text"))
        if not raw_text:
            continue
        unit = HypeRetrievalUnit(
            _id=str(uuid.uuid4()),
            item_id=item["_id"],
            aspect=clean_string(query.get("aspect")) or "function",
            raw_text=raw_text,
            embedding_text=f"{header} {raw_text}",
            embedding=embedding,
            confidence=float(query.get("confidence", 0.0)),
            source=clean_string(query.get("source")) or "llm",
            category_id=item.get("category_id", ""),
            price_vnd=item.get("price_vnd"),
            price_bucket=item.get("price_bucket", "unknown"),
            in_stock=bool(item.get("in_stock", True)),
            is_cold_item=bool(item.get("cold_start", {}).get("is_cold_item", True)),
            seller_confirmed=bool(item.get("description_enriched", {}).get("seller_confirmed", False)),
            generation_model=settings.ollama_model,
            generation_prompt_version="hype_v1",
        )
        units.append(to_mongo_dict(unit))
    return units


def estimate_indexing_size(df, avg_hype_per_item: float = 4.5, avg_props_per_item: float = 5.5) -> dict:
    item_count = len(df)
    expected_hype = int(round(item_count * avg_hype_per_item))
    expected_props = int(round(item_count * avg_props_per_item))
    memory = estimate_vector_memory(expected_hype, dimensions=1024)
    return {
        "item_count": item_count,
        "expected_hype_vectors": expected_hype,
        "expected_propositions": expected_props,
        "expected_retrieval_units": expected_hype + expected_props,
        "raw_vector_memory": memory,
    }


def _warn_for_limit(limit: int) -> None:
    settings = get_settings()
    if limit > M0_SAFE_LIMIT and settings.embedding_storage_format == "list_float":
        logger.warning(
            "Limit %s exceeds M0 safe limit with list_float embeddings. Consider a dedicated cluster or bindata_float32 later.",
            limit,
        )


def first_uninserted_index_from_mongodb(df, id_column: str = "parent_asin") -> int:
    if id_column not in df.columns:
        raise ValueError(f"Cannot resume because {id_column!r} is missing from dataframe")
    csv_ids = [clean_string(value) for value in df[id_column].tolist()]
    csv_ids = [value for value in csv_ids if value]
    if not csv_ids:
        return 0

    existing_ids = {
        clean_string(doc["_id"])
        for doc in get_items_collection().find({"_id": {"$in": csv_ids}}, {"_id": 1})
    }
    for idx, item_id in enumerate(csv_ids):
        if item_id not in existing_ids:
            return idx
    return len(csv_ids)


def index_items_from_dataframe(
    df,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = True,
    sleep_seconds: float = 0.5,
    start_index: int = 0,
    resume: bool = False,
) -> dict:
    start = time.time()
    if resume:
        start_index = first_uninserted_index_from_mongodb(df)
    else:
        start_index = max(int(start_index or 0), 0)
    if limit is None:
        limit = len(df) - start_index
    limit = max(int(limit), 0)
    _warn_for_limit(int(limit))
    end_index = min(start_index + limit, len(df))
    work_df = df.iloc[start_index:end_index]

    item_docs: list[dict] = []
    retrieval_units: list[dict] = []
    failed_items: list[dict] = []

    for idx, (row_index, row) in enumerate(work_df.iterrows(), start=1):
        try:
            item = build_item_doc_from_mvp_row(row)
            propositions = extract_propositions_llm(item)
            hype_queries = generate_hype_queries_llm(item, propositions)
            embedding_texts = [f"{build_contextual_header(item)} {query['raw_text']}" for query in hype_queries]
            embeddings = embed_texts(embedding_texts)
            item_docs.append(item)
            retrieval_units.extend(build_proposition_units(item, propositions))
            retrieval_units.extend(build_hype_units(item, hype_queries, embeddings))
            if idx % 10 == 0:
                logger.info("Indexed pipeline prepared for %s/%s items", idx, len(work_df))
            if sleep_seconds:
                time.sleep(sleep_seconds)
        except Exception as exc:
            failed_items.append({"row_index": int(row_index), "error": str(exc)})
            logger.exception("Failed to prepare item at row %s", row_index)

    item_ids = [doc["_id"] for doc in item_docs]
    if not dry_run and item_docs:
        items_collection = get_items_collection()
        retrieval_collection = get_retrieval_units_collection()
        item_ops = [
            UpdateOne({"_id": doc["_id"]}, {"$set": {key: value for key, value in doc.items() if key != "_id"}}, upsert=True)
            for doc in item_docs
        ]
        if item_ops:
            items_collection.bulk_write(item_ops, ordered=False)
        if item_ids:
            retrieval_collection.delete_many({"item_id": {"$in": item_ids}})
        if retrieval_units:
            retrieval_collection.insert_many(retrieval_units, ordered=False)

    hype_count = sum(1 for unit in retrieval_units if unit.get("unit_type") == "hype_question")
    prop_count = sum(1 for unit in retrieval_units if unit.get("unit_type") == "proposition")
    estimated = estimate_indexing_size(work_df)
    return {
        "dry_run": dry_run,
        "resume": resume,
        "start_index": start_index,
        "end_index_exclusive": end_index,
        "requested_limit": limit,
        "item_count": len(item_docs),
        "hype_units": hype_count,
        "proposition_units": prop_count,
        "failed_items": failed_items,
        "runtime_seconds": round(time.time() - start, 3),
        "estimated_raw_vector_memory_mb": estimated["raw_vector_memory"]["raw_float32_mb"],
        "estimated_retrieval_units": estimated["expected_retrieval_units"],
    }
