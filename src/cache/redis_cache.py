from __future__ import annotations

import json
import logging
from typing import Any

from .base import NoopCache


logger = logging.getLogger(__name__)


class RedisCache:
    backend_name = "redis"

    def __init__(self, client: Any, *, key_prefix: str = "coldstart_killer") -> None:
        self.client = client
        self.key_prefix = key_prefix.strip(":") or "coldstart_killer"

    @classmethod
    def from_settings(cls, settings: Any) -> "RedisCache | NoopCache":
        url = str(getattr(settings, "redis_url", "") or "").strip()
        if not url:
            return NoopCache("CACHE_BACKEND=redis requested but REDIS_URL is missing.")
        try:
            import redis  # type: ignore
        except Exception as exc:
            logger.warning("Redis cache disabled because redis package is unavailable: %s", exc)
            return NoopCache("redis package is unavailable")
        try:
            client = redis.Redis.from_url(
                url,
                socket_timeout=int(getattr(settings, "redis_socket_timeout_seconds", 2)),
                socket_connect_timeout=int(getattr(settings, "redis_connect_timeout_seconds", 2)),
                decode_responses=True,
            )
            client.ping()
        except Exception as exc:
            logger.warning("Redis cache disabled because connection failed: %s", exc)
            return NoopCache("redis connection failed")
        return cls(client, key_prefix=f"coldstart_killer:{getattr(settings, 'cache_key_version', 'v1')}")

    def _key(self, key: str) -> str:
        return f"{self.key_prefix}:{key}"

    def get(self, key: str) -> Any | None:
        try:
            value = self.client.get(self._key(key))
            if value is None:
                return None
            return json.loads(value)
        except Exception as exc:
            logger.warning("Redis cache get failed: %s", exc)
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        try:
            payload = json.dumps(value, ensure_ascii=False, default=str)
            ttl = int(ttl_seconds) if ttl_seconds is not None else 0
            if ttl > 0:
                self.client.setex(self._key(key), ttl, payload)
            else:
                self.client.set(self._key(key), payload)
        except Exception as exc:
            logger.warning("Redis cache set failed: %s", exc)

    def delete(self, key: str) -> None:
        try:
            self.client.delete(self._key(key))
        except Exception as exc:
            logger.warning("Redis cache delete failed: %s", exc)

    def clear_namespace(self, namespace: str) -> None:
        try:
            pattern = self._key(f"*:{namespace}:*")
            keys = list(self.client.scan_iter(pattern))
            if keys:
                self.client.delete(*keys)
        except Exception as exc:
            logger.warning("Redis cache namespace clear failed: %s", exc)

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "enabled": True,
            "key_prefix": self.key_prefix,
        }
