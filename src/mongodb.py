from __future__ import annotations

from functools import lru_cache
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from .config import get_settings, require_mongodb_uri


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    uri = require_mongodb_uri()
    return MongoClient(uri, serverSelectionTimeoutMS=settings.mongodb_timeout_ms)


def get_database() -> Database:
    settings = get_settings()
    return get_mongo_client()[settings.mongodb_db_name]


def get_items_collection() -> Collection:
    return get_database()["items"]


def get_retrieval_units_collection() -> Collection:
    return get_database()["retrieval_units"]


def get_users_collection() -> Collection:
    return get_database()["users"]


def get_sessions_collection() -> Collection:
    return get_database()["sessions"]


def get_recommendation_logs_collection() -> Collection:
    return get_database()["recommendation_logs"]


def get_clickstream_events_collection() -> Collection:
    return get_database()["clickstream_events"]


def get_user_item_signals_collection() -> Collection:
    return get_database()["user_item_signals"]


def get_user_profiles_collection() -> Collection:
    return get_database()["user_profiles"]


def get_item_hype_profiles_collection() -> Collection:
    return get_database()["item_hype_profiles"]


def get_item_semantic_neighbors_collection() -> Collection:
    return get_database()["item_semantic_neighbors"]


def get_item_item_cf_edges_collection() -> Collection:
    return get_database()["item_item_cf_edges"]


def get_item_stats_collection() -> Collection:
    return get_database()["item_stats"]


def get_query_embedding_cache_collection() -> Collection:
    return get_database()["query_embedding_cache"]


def get_seller_product_drafts_collection() -> Collection:
    return get_database()["seller_product_drafts"]


def get_web_enrichment_requests_collection() -> Collection:
    return get_database()["web_enrichment_requests"]


def get_synthetic_personas_collection() -> Collection:
    return get_database()["synthetic_personas"]


def get_evaluation_runs_collection() -> Collection:
    return get_database()["evaluation_runs"]


def get_job_runs_collection() -> Collection:
    return get_database()["job_runs"]


def ping_mongodb() -> dict[str, Any]:
    try:
        result = get_mongo_client().admin.command("ping")
        return {"ok": True, "result": result, "database": get_settings().mongodb_db_name}
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "hint": "Check MONGODB_URI, IP allowlist, credentials, and Atlas cluster status.",
        }


def collection_counts() -> dict[str, Any]:
    try:
        items = get_items_collection().count_documents({})
        retrieval_units = get_retrieval_units_collection().count_documents({})
        return {"ok": True, "items": items, "retrieval_units": retrieval_units}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

