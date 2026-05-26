from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from time import monotonic
from typing import Any


class MemoryCache:
    backend_name = "memory"

    def __init__(self, *, max_items: int = 1000) -> None:
        self.max_items = max(1, int(max_items))
        self._lock = threading.RLock()
        self._store: OrderedDict[str, tuple[float | None, Any]] = OrderedDict()

    def _purge_expired_locked(self) -> None:
        now = monotonic()
        expired = [key for key, (expires_at, _value) in self._store.items() if expires_at is not None and expires_at <= now]
        for key in expired:
            self._store.pop(key, None)

    def get(self, key: str) -> Any | None:
        with self._lock:
            self._purge_expired_locked()
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at is not None and expires_at <= monotonic():
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return copy.deepcopy(value)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = int(ttl_seconds) if ttl_seconds is not None else 0
        expires_at = monotonic() + ttl if ttl > 0 else None
        with self._lock:
            self._purge_expired_locked()
            self._store[key] = (expires_at, copy.deepcopy(value))
            self._store.move_to_end(key)
            while len(self._store) > self.max_items:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear_namespace(self, namespace: str) -> None:
        needle = f":{namespace}:"
        with self._lock:
            for key in list(self._store.keys()):
                if needle in key:
                    self._store.pop(key, None)

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._purge_expired_locked()
            size = len(self._store)
        return {
            "backend": self.backend_name,
            "enabled": True,
            "items": size,
            "max_items": self.max_items,
        }
