from __future__ import annotations

from time import sleep

from src.cache.memory_cache import MemoryCache


def test_memory_cache_set_get_returns_copy() -> None:
    cache = MemoryCache()
    value = {"items": [1, 2]}
    cache.set("v1:test:item", value, ttl_seconds=30)
    cached = cache.get("v1:test:item")
    assert cached == value
    cached["items"].append(3)
    assert cache.get("v1:test:item") == value


def test_memory_cache_ttl_expiry() -> None:
    cache = MemoryCache()
    cache.set("v1:test:short", {"ok": True}, ttl_seconds=1)
    assert cache.get("v1:test:short") == {"ok": True}
    sleep(1.05)
    assert cache.get("v1:test:short") is None


def test_memory_cache_delete() -> None:
    cache = MemoryCache()
    cache.set("v1:test:item", {"ok": True})
    cache.delete("v1:test:item")
    assert cache.get("v1:test:item") is None


def test_memory_cache_clear_namespace() -> None:
    cache = MemoryCache()
    cache.set("v1:jobs:registry", 1)
    cache.set("v1:evaluation:latest", 2)
    cache.clear_namespace("jobs")
    assert cache.get("v1:jobs:registry") is None
    assert cache.get("v1:evaluation:latest") == 2


def test_memory_cache_max_size_evicts_oldest() -> None:
    cache = MemoryCache(max_items=2)
    cache.set("v1:test:a", "a")
    cache.set("v1:test:b", "b")
    cache.set("v1:test:c", "c")
    assert cache.get("v1:test:a") is None
    assert cache.get("v1:test:b") == "b"
    assert cache.get("v1:test:c") == "c"
