from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any


SECRET_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "bearer",
    "mongodb",
    "password",
    "redis",
    "secret",
    "tavily",
    "token",
    "uri",
)
USER_ID_KEYS = {"user_id", "user_id_hash", "buyer_id"}
EMAIL_RE = re.compile(r"(?P<head>[^@\s]{1,2})[^@\s]*@(?P<domain>[^@\s]+)")


def _stable_digest(value: str, length: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def mask_user_id(value: Any) -> Any:
    if value is None:
        return value
    text = str(value)
    if not text:
        return text
    return f"user_{_stable_digest(text)}"


def mask_email(value: Any) -> Any:
    if value is None:
        return value
    text = str(value)
    return EMAIL_RE.sub(lambda match: f"{match.group('head')}***@{match.group('domain')}", text)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SECRET_KEY_PARTS)


def strip_secret_fields(payload: Any) -> Any:
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            if _is_secret_key(str(key)):
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = strip_secret_fields(value)
        return sanitized
    if isinstance(payload, list):
        return [strip_secret_fields(value) for value in payload]
    if isinstance(payload, str):
        return mask_email(payload)
    return payload


def sanitize_debug_payload(payload: Any) -> Any:
    copied = deepcopy(payload)
    return _sanitize_debug_value(copied, current_key="")


def _sanitize_debug_value(value: Any, *, current_key: str) -> Any:
    if _is_secret_key(current_key):
        return "[redacted]"
    if current_key.lower() in USER_ID_KEYS:
        return mask_user_id(value)
    if current_key.lower() == "email":
        return mask_email(value)
    if isinstance(value, dict):
        return {key: _sanitize_debug_value(nested, current_key=str(key)) for key, nested in value.items()}
    if isinstance(value, list):
        return [_sanitize_debug_value(item, current_key=current_key) for item in value]
    if isinstance(value, str):
        return mask_email(value)
    return value


def sanitize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_debug_payload(payload)
    return sanitized if isinstance(sanitized, dict) else {}

