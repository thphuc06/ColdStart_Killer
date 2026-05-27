from __future__ import annotations

import re
from typing import Any

import httpx

from src.enrichment.providers import ProviderConfigurationError
from src.enrichment.schemas import WebSearchResult


class TavilyProvider:
    name = "tavily"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int = 10,
        search_depth: str = "basic",
        include_raw_content: bool = False,
        snippet_char_limit: int = 1200,
    ) -> None:
        if not api_key.strip():
            raise ProviderConfigurationError("Tavily API key is not configured.")
        self._api_key = api_key
        self._timeout_seconds = max(1, int(timeout_seconds or 10))
        normalized_depth = str(search_depth or "basic").strip().lower()
        self._search_depth = "advanced" if normalized_depth == "advanced" else "basic"
        self._include_raw_content = bool(include_raw_content)
        self._snippet_char_limit = max(200, min(int(snippet_char_limit or 1200), 6000))

    async def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max(1, min(int(max_results or 3), 10)),
            "search_depth": self._search_depth,
            "include_answer": False,
            "include_raw_content": self._include_raw_content,
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
        return _normalize_tavily_results(
            data.get("results", []),
            snippet_char_limit=self._snippet_char_limit,
        )


def _normalize_tavily_results(
    results: list[dict[str, Any]],
    *,
    snippet_char_limit: int,
) -> list[WebSearchResult]:
    normalized: list[WebSearchResult] = []
    for result in results:
        url = str(result.get("url") or "").strip()
        if not url:
            continue
        snippet = str(result.get("content") or result.get("snippet") or "").strip()
        snippet = re.sub(r"\s+", " ", snippet).strip()
        snippet = snippet[:snippet_char_limit]
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

