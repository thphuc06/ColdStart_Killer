from __future__ import annotations

from typing import Annotated, Any

from fastapi import Header, HTTPException

from src.auth.dependencies import ADMIN_TOKEN_HEADER, SELLER_TOKEN_HEADER, require_admin, require_seller_or_admin
from src.auth.schemas import AuthContext
from src.auth.service import disabled_auth_context, normalized_auth_mode
from src.config import get_settings
from src.mongodb import get_users_collection


def seller_subject_scope(auth: AuthContext) -> str | None:
    if auth.role != "seller":
        return None
    return str(auth.subject_id or "").strip() or None


def enforce_seller_scope_for_seller_id(auth: AuthContext, seller_id: str | None) -> str | None:
    scope = seller_subject_scope(auth)
    if scope is None:
        return seller_id
    requested = str(seller_id or "").strip()
    if requested and requested != scope:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "seller_scope_violation",
                "message": "Seller token can only access its own seller scope.",
            },
        )
    return scope


def enforce_seller_scope_for_doc(auth: AuthContext, doc: dict[str, Any], *, resource_name: str) -> None:
    scope = seller_subject_scope(auth)
    if scope is None:
        return
    owner = str(doc.get("seller_id") or "").strip()
    if owner != scope:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "seller_scope_violation",
                "message": f"Seller token cannot access this {resource_name}.",
            },
        )


def require_admin_token(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
) -> AuthContext:
    settings = get_settings()
    if normalized_auth_mode(settings) == "disabled" or not settings.auth_require_admin_for_debug:
        return disabled_auth_context(settings)
    return require_admin(authorization=authorization, x_admin_token=x_admin_token)


def require_seller_or_admin_for_seller_tools(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
    x_seller_token: Annotated[str | None, Header(alias=SELLER_TOKEN_HEADER)] = None,
) -> AuthContext:
    settings = get_settings()
    if not settings.enable_seller_tools:
        return disabled_auth_context(settings)
    return require_seller_or_admin(
        authorization=authorization,
        x_admin_token=x_admin_token,
        x_seller_token=x_seller_token,
    )


def get_user_privacy_settings(
    user_id_hash: str,
    *,
    users_collection: Any | None = None,
) -> dict[str, bool]:
    default_privacy = {
        "allow_personalization": True,
        "allow_clickstream_logging": True,
    }
    unavailable_privacy = {
        "allow_personalization": False,
        "allow_clickstream_logging": False,
    }
    try:
        if users_collection is None:
            users_collection = get_users_collection()
        user_doc = users_collection.find_one({"user_id_hash": user_id_hash}, {"_id": 0, "privacy": 1})
    except Exception:
        return unavailable_privacy
    privacy = user_doc.get("privacy") if isinstance(user_doc, dict) and isinstance(user_doc.get("privacy"), dict) else {}
    return {
        "allow_personalization": bool(privacy.get("allow_personalization", default_privacy["allow_personalization"])),
        "allow_clickstream_logging": bool(privacy.get("allow_clickstream_logging", default_privacy["allow_clickstream_logging"])),
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
