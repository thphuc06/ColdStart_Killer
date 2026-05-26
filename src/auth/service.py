from __future__ import annotations

import secrets
from typing import Any

from src.auth.schemas import AuthContext


SUPPORTED_AUTH_MODES = {"disabled", "demo", "production"}


def normalized_auth_mode(settings: Any) -> str:
    mode = str(getattr(settings, "auth_mode", "demo") or "demo").strip().lower()
    return mode if mode in SUPPORTED_AUTH_MODES else "demo"


def disabled_auth_context(settings: Any) -> AuthContext:
    return AuthContext(authenticated=True, role="disabled", auth_mode=normalized_auth_mode(settings), subject_id=None)


def anonymous_auth_context(settings: Any) -> AuthContext:
    return AuthContext(authenticated=False, role="anonymous", auth_mode=normalized_auth_mode(settings), subject_id=None)


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def constant_time_equals(supplied: str | None, expected: str | None) -> bool:
    supplied_value = str(supplied or "")
    expected_value = str(expected or "")
    if not supplied_value or not expected_value:
        return False
    return secrets.compare_digest(supplied_value, expected_value)


def token_matches_any(supplied: str | None, expected_tokens: list[str | None]) -> bool:
    return any(constant_time_equals(supplied, expected) for expected in expected_tokens)

