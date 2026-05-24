from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.behavior.schemas import PrivacySettings, UserDocument
from src.mongodb import get_synthetic_personas_collection, get_users_collection
from src.schemas import to_mongo_dict
from src.utils import utc_now_iso


router = APIRouter(prefix="/api")


class CreateUserRequest(BaseModel):
    allow_personalization: bool = True
    allow_clickstream_logging: bool = True


def _user_summary(doc: dict[str, Any]) -> dict[str, Any]:
    privacy = doc.get("privacy") if isinstance(doc.get("privacy"), dict) else {}
    onboarding = doc.get("onboarding") if isinstance(doc.get("onboarding"), dict) else {}
    return {
        "user_id_hash": doc.get("user_id_hash"),
        "profile_status": doc.get("profile_status", "new"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "privacy": {
            "allow_personalization": bool(privacy.get("allow_personalization", True)),
            "allow_clickstream_logging": bool(privacy.get("allow_clickstream_logging", True)),
        },
        "onboarding": {
            "completed": bool(onboarding.get("completed", False)),
            "selected_categories": list(onboarding.get("selected_categories", [])),
            "selected_price_buckets": list(onboarding.get("selected_price_buckets", [])),
            "selected_seed_item_ids": list(onboarding.get("selected_seed_item_ids", [])),
        },
    }


def _persona_summary(doc: dict[str, Any]) -> dict[str, Any]:
    preferred_categories = doc.get("preferred_categories") if isinstance(doc.get("preferred_categories"), dict) else {}
    preferred_price_buckets = (
        doc.get("preferred_price_buckets") if isinstance(doc.get("preferred_price_buckets"), dict) else {}
    )
    return {
        "persona_id": doc.get("persona_id"),
        "label": doc.get("label", ""),
        "preferred_categories": dict(preferred_categories),
        "preferred_price_buckets": dict(preferred_price_buckets),
        "intent_keywords": list(doc.get("intent_keywords", [])),
        "negative_keywords": list(doc.get("negative_keywords", [])),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@router.get("/users/demo")
def list_demo_users(
    *,
    users_collection: Any | None = None,
    synthetic_personas_collection: Any | None = None,
) -> dict[str, Any]:
    users_collection = users_collection or get_users_collection()
    synthetic_personas_collection = synthetic_personas_collection or get_synthetic_personas_collection()
    cursor = users_collection.find({}, {"_id": 0}).sort("updated_at", -1).limit(50)
    users = [_user_summary(doc) for doc in cursor]
    personas_cursor = synthetic_personas_collection.find(
        {},
        {
            "_id": 0,
            "persona_id": 1,
            "label": 1,
            "preferred_categories": 1,
            "preferred_price_buckets": 1,
            "intent_keywords": 1,
            "negative_keywords": 1,
            "created_at": 1,
            "updated_at": 1,
        },
    ).sort("updated_at", -1).limit(50)
    personas = [_persona_summary(doc) for doc in personas_cursor]
    return {"users": users, "personas": personas}


@router.post("/users")
def create_user(payload: CreateUserRequest, *, users_collection: Any | None = None) -> dict[str, Any]:
    users_collection = users_collection or get_users_collection()
    user_id_hash = f"u_api_{uuid4().hex[:16]}"
    now = utc_now_iso()
    doc = UserDocument(
        _id=user_id_hash,
        user_id_hash=user_id_hash,
        profile_status="new",
        privacy=PrivacySettings(
            allow_personalization=payload.allow_personalization,
            allow_clickstream_logging=payload.allow_clickstream_logging,
        ),
        created_at=now,
        updated_at=now,
    )
    mongo_doc = to_mongo_dict(doc)
    users_collection.insert_one(mongo_doc)
    return _user_summary(mongo_doc)
