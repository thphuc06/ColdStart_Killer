from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException

from src.auth.schemas import AuthContext
from src.auth.service import disabled_auth_context, extract_bearer_token, normalized_auth_mode, token_matches_any
from src.config import get_settings


ADMIN_TOKEN_HEADER = "X-Admin-Token"
SELLER_TOKEN_HEADER = "X-Seller-Token"


def _tokens_from_headers(
    *,
    authorization: str | None,
    x_admin_token: str | None,
    x_seller_token: str | None,
) -> list[str | None]:
    return [extract_bearer_token(authorization), x_admin_token, x_seller_token]


def _token_not_configured(role: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": f"{role}_token_not_configured",
            "message": f"{role.upper()}_TOKEN must be configured before using protected admin/write routes.",
        },
    )


def _token_required(role: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "error": f"{role}_token_required",
            "message": f"A valid {role} token is required for this protected action.",
        },
    )


def require_admin(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
) -> AuthContext:
    settings = get_settings()
    mode = normalized_auth_mode(settings)
    if mode == "disabled":
        return disabled_auth_context(settings)

    expected = str(getattr(settings, "admin_token", "") or "").strip()
    if not expected:
        raise _token_not_configured("admin")
    if token_matches_any(extract_bearer_token(authorization), [expected]) or token_matches_any(x_admin_token, [expected]):
        return AuthContext(authenticated=True, role="admin", auth_mode=mode)
    raise _token_required("admin")


def require_admin_for_write(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
) -> AuthContext:
    settings = get_settings()
    mode = normalized_auth_mode(settings)
    if mode == "disabled" or not bool(getattr(settings, "auth_require_admin_for_writes", True)):
        return disabled_auth_context(settings)
    return require_admin(authorization=authorization, x_admin_token=x_admin_token)


def require_seller_or_admin(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
    x_seller_token: Annotated[str | None, Header(alias=SELLER_TOKEN_HEADER)] = None,
) -> AuthContext:
    settings = get_settings()
    mode = normalized_auth_mode(settings)
    if mode == "disabled" or not bool(getattr(settings, "auth_require_admin_for_writes", True)):
        return disabled_auth_context(settings)

    supplied_tokens = _tokens_from_headers(
        authorization=authorization,
        x_admin_token=x_admin_token,
        x_seller_token=x_seller_token,
    )
    admin_token = str(getattr(settings, "admin_token", "") or "").strip()
    seller_token = str(getattr(settings, "seller_token", "") or "").strip()

    if admin_token and any(token_matches_any(token, [admin_token]) for token in supplied_tokens):
        return AuthContext(authenticated=True, role="admin", auth_mode=mode)
    if seller_token and any(token_matches_any(token, [seller_token]) for token in supplied_tokens):
        return AuthContext(authenticated=True, role="seller", auth_mode=mode)
    if not admin_token and not seller_token:
        raise _token_not_configured("admin")
    raise _token_required("seller_or_admin")


def optional_auth_context(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    x_admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
    x_seller_token: Annotated[str | None, Header(alias=SELLER_TOKEN_HEADER)] = None,
) -> AuthContext:
    settings = get_settings()
    mode = normalized_auth_mode(settings)
    if mode == "disabled":
        return disabled_auth_context(settings)

    supplied_tokens = _tokens_from_headers(
        authorization=authorization,
        x_admin_token=x_admin_token,
        x_seller_token=x_seller_token,
    )
    admin_token = str(getattr(settings, "admin_token", "") or "").strip()
    seller_token = str(getattr(settings, "seller_token", "") or "").strip()
    if admin_token and any(token_matches_any(token, [admin_token]) for token in supplied_tokens):
        return AuthContext(authenticated=True, role="admin", auth_mode=mode)
    if seller_token and any(token_matches_any(token, [seller_token]) for token in supplied_tokens):
        return AuthContext(authenticated=True, role="seller", auth_mode=mode)
    return AuthContext(authenticated=False, role="anonymous", auth_mode=mode)
