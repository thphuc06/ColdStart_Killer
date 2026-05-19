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

