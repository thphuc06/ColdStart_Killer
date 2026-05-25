from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from src.behavior.schemas import OnboardingState, PrivacySettings, UserDocument
from src.mongodb import get_synthetic_personas_collection, get_user_profiles_collection, get_users_collection
from src.schemas import to_mongo_dict
from src.utils import utc_now_iso


router = APIRouter(prefix="/api")


class CreateUserRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    allow_personalization: bool = True
    allow_clickstream_logging: bool = True

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name must not be blank")
        return normalized


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
        "has_profile": bool(doc.get("has_profile", False)),
        "username": doc.get("username") or doc.get("demo_label", ""),
        "demo_label": doc.get("demo_label", ""),
        "demo_source": doc.get("demo_source", "users"),
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


def _profile_backed_user_doc(profile_doc: dict[str, Any], user_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    user_id_hash = str(profile_doc.get("user_id_hash") or "").strip()
    explicit_prefs = profile_doc.get("explicit_prefs") if isinstance(profile_doc.get("explicit_prefs"), dict) else {}
    onboarding = user_doc.get("onboarding") if user_doc and isinstance(user_doc.get("onboarding"), dict) else {}
    doc = dict(user_doc or {})
    doc["user_id_hash"] = user_id_hash
    doc["_id"] = doc.get("_id") or user_id_hash
    doc["profile_status"] = profile_doc.get("profile_status") or doc.get("profile_status", "warm")
    doc["created_at"] = doc.get("created_at") or profile_doc.get("updated_at")
    doc["updated_at"] = profile_doc.get("updated_at") or doc.get("updated_at")
    doc["privacy"] = doc.get("privacy") or {
        "allow_personalization": True,
        "allow_clickstream_logging": True,
    }
    doc["onboarding"] = {
        "completed": bool(onboarding.get("completed", False) or explicit_prefs.get("source") == "onboarding"),
        "completed_at": onboarding.get("completed_at"),
        "selected_categories": list(onboarding.get("selected_categories", explicit_prefs.get("categories", []))),
        "selected_price_buckets": list(
            onboarding.get("selected_price_buckets", explicit_prefs.get("price_buckets", []))
        ),
        "selected_seed_item_ids": list(
            onboarding.get("selected_seed_item_ids", explicit_prefs.get("seed_item_ids", []))
        ),
    }
    doc["has_profile"] = True
    doc["demo_label"] = doc.get("demo_label") or f"Profile-backed shopper {user_id_hash[-6:]}"
    doc["demo_source"] = doc.get("demo_source") or "user_profile"
    return doc


@router.get("/users/demo")
def list_demo_users(
    *,
    users_collection: Any | None = None,
    user_profiles_collection: Any | None = None,
    synthetic_personas_collection: Any | None = None,
) -> dict[str, Any]:
    if users_collection is None:
        users_collection = get_users_collection()
    if user_profiles_collection is None:
        user_profiles_collection = get_user_profiles_collection()
    if synthetic_personas_collection is None:
        synthetic_personas_collection = get_synthetic_personas_collection()
    user_docs = list(users_collection.find({}, {"_id": 0}).sort("updated_at", -1).limit(100))
    user_docs_by_id = {
        str(doc.get("user_id_hash")): doc for doc in user_docs if str(doc.get("user_id_hash") or "").strip()
    }
    profile_cursor = user_profiles_collection.find(
        {},
        {
            "_id": 0,
            "user_id_hash": 1,
            "profile_status": 1,
            "explicit_prefs": 1,
            "profile_quality": 1,
            "updated_at": 1,
        },
    ).sort("updated_at", -1).limit(50)
    profile_docs = [doc for doc in profile_cursor if str(doc.get("user_id_hash") or "").strip()]

    users = []
    seen_user_ids: set[str] = set()
    for profile_doc in profile_docs:
        user_id_hash = str(profile_doc.get("user_id_hash"))
        users.append(_user_summary(_profile_backed_user_doc(profile_doc, user_docs_by_id.get(user_id_hash))))
        seen_user_ids.add(user_id_hash)
    for user_doc in user_docs:
        user_id_hash = str(user_doc.get("user_id_hash") or "")
        if user_id_hash in seen_user_ids:
            continue
        user_doc = dict(user_doc)
        user_doc["has_profile"] = False
        user_doc["demo_source"] = user_doc.get("demo_source") or "users"
        users.append(_user_summary(user_doc))
        if len(users) >= 50:
            break

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
    if users_collection is None:
        users_collection = get_users_collection()
    user_id_hash = f"u_api_{uuid4().hex[:16]}"
    now = utc_now_iso()
    doc = UserDocument(
        _id=user_id_hash,
        user_id_hash=user_id_hash,
        username=payload.display_name,
        profile_status="new",
        privacy=PrivacySettings(
            allow_personalization=payload.allow_personalization,
            allow_clickstream_logging=payload.allow_clickstream_logging,
        ),
        onboarding=OnboardingState(),
        created_at=now,
        updated_at=now,
    )
    mongo_doc = to_mongo_dict(doc)
    mongo_doc["demo_label"] = payload.display_name
    mongo_doc["demo_source"] = "user_created"
    users_collection.insert_one(mongo_doc)
    return _user_summary(mongo_doc)
