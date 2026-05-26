from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SENSITIVE_KEY_PARTS = ("authorization", "admin_token", "token", "secret", "password", "api_key", "apikey", "uri")
SAFE_LABEL_RE = re.compile(r"[^a-zA-Z0-9_.=-]+")
MAX_RAW_PART_LENGTH = 64


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _safe_label(value: str) -> str:
    cleaned = SAFE_LABEL_RE.sub("_", value.strip())
    return cleaned.strip("_") or "empty"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def sanitize_cache_key_part(value: Any, *, key_context: str | None = None) -> Any:
    if key_context and _is_sensitive_key(key_context):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(key): sanitize_cache_key_part(item, key_context=str(key)) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [sanitize_cache_key_part(item) for item in value]
    if isinstance(value, str):
        if len(value) > MAX_RAW_PART_LENGTH:
            return {"sha256": _digest(value)}
        if any(marker in value.lower() for marker in ("mongodb+srv://", "bearer ", "token=", "password=", "secret=")):
            return {"sha256": _digest(value)}
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(sanitize_cache_key_part(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _format_parts(parts: dict[str, Any] | list[Any] | tuple[Any, ...] | str | int | bool | None) -> str:
    sanitized = sanitize_cache_key_part(parts)
    if isinstance(sanitized, str):
        if len(sanitized) <= MAX_RAW_PART_LENGTH:
            return _safe_label(sanitized)
        return f"h={_digest(sanitized)}"
    if isinstance(sanitized, dict):
        simple_items: list[str] = []
        for key, value in sanitized.items():
            if isinstance(value, (str, int, bool)) and len(str(value)) <= MAX_RAW_PART_LENGTH:
                simple_items.append(f"{_safe_label(str(key))}={_safe_label(str(value))}")
            elif value is None:
                simple_items.append(f"{_safe_label(str(key))}=null")
            else:
                return f"h={_digest(_canonical_json(sanitized))}"
        return ":".join(simple_items) if simple_items else "empty"
    return f"h={_digest(_canonical_json(sanitized))}"


def make_cache_key(
    namespace: str,
    parts: dict[str, Any] | list[Any] | tuple[Any, ...] | str | int | bool | None,
    *,
    version: str,
) -> str:
    safe_version = _safe_label(str(version or "v1"))
    safe_namespace = _safe_label(str(namespace or "default"))
    return f"{safe_version}:{safe_namespace}:{_format_parts(parts)}"
