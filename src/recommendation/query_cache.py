from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from src.config import Settings, get_settings
from src.mongodb import get_query_embedding_cache_collection
from src.query_processor import extract_hard_filters, process_query
from src.recommendation.schemas import EMBEDDING_DIM
from src.utils import utc_now_iso


REQUIRED_FIXTURE_FIELDS = (
    "original_query",
    "language_detected",
    "english_query",
    "hype_search_query_en",
    "bm25_search_query_en",
    "hard_filters",
    "query_embedding",
)


def normalize_query_for_cache(raw_query: str) -> str:
    return " ".join(str(raw_query).strip().lower().split())


def _canonical_json(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _safe_hard_filters(raw_query: str) -> dict[str, Any]:
    try:
        filters = extract_hard_filters(raw_query)
    except Exception:
        return {}
    return dict(filters) if isinstance(filters, dict) else {}


def build_query_cache_key(
    raw_query: str,
    *,
    settings: Settings | None = None,
    hard_filters: dict[str, Any] | None = None,
) -> str:
    active_settings = settings or get_settings()
    normalized_query = normalize_query_for_cache(raw_query)
    filters = hard_filters if hard_filters is not None else _safe_hard_filters(raw_query)
    payload = {
        "query_cache_version": active_settings.query_cache_version,
        "embedding_model": active_settings.embedding_model,
        "vector_index_name": active_settings.vector_index_name,
        "text_index_name": active_settings.text_index_name,
        "algorithm_version": active_settings.algorithm_version,
        "ranking_version": active_settings.ranking_version,
        "normalized_query": normalized_query,
        "hard_filters": json.loads(_canonical_json(filters)),
    }
    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _is_embedding(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIM:
        return False
    try:
        return all(math.isfinite(float(item)) for item in value)
    except (TypeError, ValueError):
        return False


def _valid_fixture(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if not all(field in value for field in REQUIRED_FIXTURE_FIELDS):
        return None
    if not isinstance(value.get("hard_filters"), dict):
        return None
    if not _is_embedding(value.get("query_embedding")):
        return None
    return dict(value)


def _parse_cache_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _is_expired(doc: dict[str, Any], settings: Settings) -> bool:
    if settings.query_cache_ttl_days <= 0:
        return False
    timestamp = _parse_cache_time(doc.get("last_used_at")) or _parse_cache_time(doc.get("created_at"))
    if timestamp is None:
        return True
    return datetime.now(UTC) - timestamp > timedelta(days=settings.query_cache_ttl_days)


def _fixture_from_cache_doc(doc: Any, *, settings: Settings, query_hash: str) -> dict[str, Any] | None:
    if not isinstance(doc, dict):
        return None
    expected = {
        "query_hash": query_hash,
        "embedding_model": settings.embedding_model,
        "vector_index_name": settings.vector_index_name,
        "text_index_name": settings.text_index_name,
        "query_cache_version": settings.query_cache_version,
        "algorithm_version": settings.algorithm_version,
        "ranking_version": settings.ranking_version,
    }
    for key, value in expected.items():
        if doc.get(key) != value:
            return None
    if _is_expired(doc, settings):
        return None
    return _valid_fixture(doc.get("processed_query"))


def _cache_document(
    *,
    raw_query: str,
    query_hash: str,
    fixture: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    now = utc_now_iso()
    normalized_query = normalize_query_for_cache(raw_query)
    return {
        "query_hash": query_hash,
        "raw_query": raw_query,
        "normalized_query": normalized_query,
        "english_query": str(fixture.get("english_query") or ""),
        "embedding": list(fixture.get("query_embedding") or []),
        "processed_query": dict(fixture),
        "embedding_model": settings.embedding_model,
        "vector_index_name": settings.vector_index_name,
        "text_index_name": settings.text_index_name,
        "query_cache_version": settings.query_cache_version,
        "algorithm_version": settings.algorithm_version,
        "ranking_version": settings.ranking_version,
        "created_at": now,
        "last_used_at": now,
    }


def _touch_cache_doc(collection: Any, query_hash: str) -> None:
    try:
        collection.update_one(
            {"query_hash": query_hash},
            {"$set": {"last_used_at": utc_now_iso()}, "$inc": {"usage_count": 1}},
            upsert=False,
        )
    except Exception:
        return


def _upsert_cache_doc(collection: Any, doc: dict[str, Any]) -> None:
    try:
        collection.update_one(
            {"query_hash": doc["query_hash"]},
            {
                "$set": {key: value for key, value in doc.items() if key not in {"created_at"}},
                "$setOnInsert": {"created_at": doc["created_at"], "usage_count": 0},
                "$inc": {"usage_count": 1},
            },
            upsert=True,
        )
    except Exception:
        return


def process_query_with_cache(
    raw_query: str,
    *,
    process_query_fn: Callable[[str], dict[str, Any]] = process_query,
    settings: Settings | None = None,
    collection: Any | None = None,
    use_cache: bool | None = None,
    write_cache: bool | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    cache_enabled = active_settings.enable_query_embedding_cache if use_cache is None else bool(use_cache)
    write_enabled = active_settings.query_cache_write_enabled if write_cache is None else bool(write_cache)

    if not cache_enabled:
        return process_query_fn(raw_query)

    query_hash = build_query_cache_key(raw_query, settings=active_settings)
    cache_collection = collection
    try:
        if cache_collection is None:
            cache_collection = get_query_embedding_cache_collection()
        cached_doc = cache_collection.find_one({"query_hash": query_hash})
        cached_fixture = _fixture_from_cache_doc(cached_doc, settings=active_settings, query_hash=query_hash)
        if cached_fixture is not None:
            if write_enabled:
                _touch_cache_doc(cache_collection, query_hash)
            return cached_fixture
    except Exception:
        return process_query_fn(raw_query)

    fixture = dict(process_query_fn(raw_query))
    if write_enabled and cache_collection is not None:
        valid_fixture = _valid_fixture(fixture)
        if valid_fixture is not None:
            _upsert_cache_doc(
                cache_collection,
                _cache_document(
                    raw_query=raw_query,
                    query_hash=query_hash,
                    fixture=valid_fixture,
                    settings=active_settings,
                ),
            )
    return fixture
