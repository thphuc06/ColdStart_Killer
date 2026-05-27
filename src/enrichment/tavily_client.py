from __future__ import annotations

from typing import Any

import httpx

from src.enrichment.providers import ProviderConfigurationError
from src.enrichment.schemas import WebSearchResult


class TavilyProvider:
    name = "tavily"

    def __init__(self, *, api_key: str, timeout_seconds: int = 10) -> None:
        if not api_key.strip():
            raise ProviderConfigurationError("Tavily API key is not configured.")
        self._api_key = api_key
        self._timeout_seconds = max(1, int(timeout_seconds or 10))

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max(1, min(int(max_results or 3), 10)),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json=payload,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Tavily request failed: {exc.__class__.__name__}") from exc

        data = response.json()
        return _normalize_tavily_results(data.get("results", []))


def _normalize_tavily_results(results: list[dict[str, Any]]) -> list[WebSearchResult]:
    normalized: list[WebSearchResult] = []
    for result in results:
        url = str(result.get("url") or "").strip()
        if not url:
            continue
        snippet = str(result.get("content") or result.get("snippet") or "").strip()
        title = str(result.get("title") or "").strip()
        raw_score = result.get("score")
        try:
            score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            score = None
        normalized.append(
            WebSearchResult(
                title=title,
                url=url,
                snippet=snippet,
                score=score,
                source="tavily",
            )
        )
    return normalized

