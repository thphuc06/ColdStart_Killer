from __future__ import annotations

from typing import Any, Protocol


class CacheBackend(Protocol):
    backend_name: str

    def get(self, key: str) -> Any | None:
        ...

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ...

    def delete(self, key: str) -> None:
        ...

    def clear_namespace(self, namespace: str) -> None:
        ...

    def status(self) -> dict[str, Any]:
        ...


class NoopCache:
    backend_name = "none"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        return None

    def delete(self, key: str) -> None:
        return None

    def clear_namespace(self, namespace: str) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "enabled": False,
            "reason": self.reason,
        }
