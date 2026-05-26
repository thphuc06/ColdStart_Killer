from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WebSearchResult(BaseModel):
    title: str = ""
    url: str
    snippet: str = ""
    score: float | None = None
    source: str = "tavily"


class WebEnrichmentSuggestion(BaseModel):
    value: Any
    confidence: float
    source_urls: list[str] = Field(default_factory=list)
    reason: str = ""


class ApplyEnrichmentPayload(BaseModel):
    fields_to_apply: list[str] = Field(default_factory=list)

