from __future__ import annotations

from typing import Awaitable, Protocol

from src.enrichment.schemas import WebSearchResult


class WebEnrichmentProvider(Protocol):
    name: str

    def search(self, query: str, *, max_results: int) -> list[WebSearchResult] | Awaitable[list[WebSearchResult]]:
        ...


class ProviderConfigurationError(RuntimeError):
    """Raised when an optional provider is enabled but not configured."""

