from __future__ import annotations

import builtins
from dataclasses import replace

from src.cache.base import NoopCache
from src.cache.memory_cache import MemoryCache
from src.cache.redis_cache import RedisCache
from src.cache.service import build_cache_backend, get_or_compute
from src.config import get_settings


def _settings(**overrides):
    return replace(get_settings(), **overrides)


def test_backend_none_returns_noop_cache() -> None:
    cache = build_cache_backend(_settings(cache_backend="none"))
    assert isinstance(cache, NoopCache)
    assert cache.get("anything") is None


def test_backend_memory_returns_memory_cache() -> None:
    cache = build_cache_backend(_settings(cache_backend="memory"))
    assert isinstance(cache, MemoryCache)


def test_redis_url_missing_falls_back_to_noop() -> None:
    cache = build_cache_backend(_settings(cache_backend="redis", redis_url=""))
    assert isinstance(cache, NoopCache)
    assert "REDIS_URL" in str(cache.status()["reason"])


def test_redis_package_missing_falls_back_without_crash(monkeypatch) -> None:
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "redis":
            raise ImportError("redis not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    cache = RedisCache.from_settings(_settings(cache_backend="redis", redis_url="redis://localhost:6379/0"))
    assert isinstance(cache, NoopCache)
    assert "redis package" in str(cache.status()["reason"])


def test_get_or_compute_hits_cache_on_second_call() -> None:
    cache = MemoryCache()
    calls = {"count": 0}

    def compute():
        calls["count"] += 1
        return {"ok": True, "count": calls["count"]}

    assert get_or_compute(cache=cache, key="v1:test:item", ttl_seconds=30, compute_fn=compute) == {"ok": True, "count": 1}
    assert get_or_compute(cache=cache, key="v1:test:item", ttl_seconds=30, compute_fn=compute) == {"ok": True, "count": 1}
    assert calls["count"] == 1


def test_get_or_compute_fail_open_on_cache_errors() -> None:
    class BrokenCache:
        backend_name = "broken"

        def get(self, _key):
            raise RuntimeError("cache read failed")

        def set(self, *_args, **_kwargs):
            raise RuntimeError("cache write failed")

        def delete(self, _key):
            raise RuntimeError("delete failed")

        def clear_namespace(self, _namespace):
            raise RuntimeError("clear failed")

        def status(self):
            return {"backend": "broken"}

    assert get_or_compute(cache=BrokenCache(), key="v1:test:item", ttl_seconds=30, compute_fn=lambda: {"ok": True}) == {
        "ok": True
    }
