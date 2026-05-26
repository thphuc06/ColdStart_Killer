from __future__ import annotations

import logging
from typing import Any, Callable

from src.config import Settings, get_settings

from .base import CacheBackend, NoopCache
from .memory_cache import MemoryCache
from .redis_cache import RedisCache


logger = logging.getLogger(__name__)
_CACHE_BACKEND: CacheBackend | None = None
_CACHE_SIGNATURE: tuple[Any, ...] | None = None


def _settings_signature(settings: Settings) -> tuple[Any, ...]:
    return (
        str(settings.cache_backend or "none").lower(),
        settings.cache_key_version,
        settings.redis_url,
        settings.redis_socket_timeout_seconds,
        settings.redis_connect_timeout_seconds,
    )


def build_cache_backend(settings: Settings) -> CacheBackend:
    backend = str(settings.cache_backend or "none").strip().lower()
    if backend in {"", "none", "off", "disabled"}:
        return NoopCache()
    if backend == "memory":
        return MemoryCache()
    if backend == "redis":
        return RedisCache.from_settings(settings)
    logger.warning("Unknown CACHE_BACKEND=%s; falling back to no-op cache.", backend)
    return NoopCache(f"unknown backend: {backend}")


def get_cache_backend(settings: Settings | None = None) -> CacheBackend:
    global _CACHE_BACKEND, _CACHE_SIGNATURE
    active_settings = settings or get_settings()
    if settings is not None:
        return build_cache_backend(active_settings)
    signature = _settings_signature(active_settings)
    if _CACHE_BACKEND is None or _CACHE_SIGNATURE != signature:
        _CACHE_BACKEND = build_cache_backend(active_settings)
        _CACHE_SIGNATURE = signature
    return _CACHE_BACKEND


def reset_cache_backend_for_tests() -> None:
    global _CACHE_BACKEND, _CACHE_SIGNATURE
    _CACHE_BACKEND = None
    _CACHE_SIGNATURE = None


def get_or_compute(
    *,
    cache: CacheBackend,
    key: str,
    ttl_seconds: int,
    compute_fn: Callable[[], Any],
) -> Any:
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    value = compute_fn()
    if value is not None:
        try:
            cache.set(key, value, ttl_seconds=ttl_seconds)
        except Exception:
            return value
    return value


def cache_status(settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    backend = get_cache_backend(active_settings)
    status = backend.status()
    status.update(
        {
            "configured_backend": str(active_settings.cache_backend or "none").lower(),
            "default_ttl_seconds": active_settings.cache_default_ttl_seconds,
            "key_version": active_settings.cache_key_version,
            "debug_headers": active_settings.cache_debug_headers,
        }
    )
    return status
