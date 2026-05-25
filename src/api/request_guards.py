from __future__ import annotations

from typing import Annotated, Any

from fastapi import Header, HTTPException

from src.config import get_settings
from src.mongodb import get_users_collection


ADMIN_TOKEN_HEADER = "X-Admin-Token"


def require_admin_token(
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
) -> None:
    expected = str(get_settings().admin_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "admin_token_not_configured",
                "message": "ADMIN_TOKEN must be configured before using debug/demo routes.",
            },
        )
    if x_admin_token == expected:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": "admin_token_required",
            "message": "A valid X-Admin-Token header is required for debug/demo routes.",
        },
    )


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