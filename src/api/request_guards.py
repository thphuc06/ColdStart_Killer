from __future__ import annotations

from typing import Annotated, Any

from fastapi import Header

from src.auth.dependencies import ADMIN_TOKEN_HEADER, require_admin
from src.auth.schemas import AuthContext
from src.auth.service import disabled_auth_context, normalized_auth_mode
from src.config import get_settings
from src.mongodb import get_users_collection


def require_admin_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
) -> AuthContext:
    settings = get_settings()
    if normalized_auth_mode(settings) == "disabled" or not settings.auth_require_admin_for_debug:
        return disabled_auth_context(settings)
    return require_admin(authorization=authorization, x_admin_token=x_admin_token)


def get_user_privacy_settings(
    user_id_hash: str,
    *,
    users_collection: Any | None = None,
) -> dict[str, bool]:
    if users_collection is None:
        users_collection = get_users_collection()
    user_doc = users_collection.find_one({"user_id_hash": user_id_hash}, {"_id": 0, "privacy": 1})
    privacy = user_doc.get("privacy") if isinstance(user_doc, dict) and isinstance(user_doc.get("privacy"), dict) else {}
    return {
        "allow_personalization": bool(privacy.get("allow_personalization", True)),
        "allow_clickstream_logging": bool(privacy.get("allow_clickstream_logging", True)),
    }


def personalization_enabled_for_user(
    user_id_hash: str,
    *,
    personalized: bool,
    users_collection: Any | None = None,
) -> bool:
    privacy = get_user_privacy_settings(user_id_hash, users_collection=users_collection)
    return bool(personalized and privacy["allow_personalization"])


def clickstream_logging_enabled_for_user(
    user_id_hash: str,
    *,
    users_collection: Any | None = None,
) -> bool:
    privacy = get_user_privacy_settings(user_id_hash, users_collection=users_collection)
    return privacy["allow_clickstream_logging"]
