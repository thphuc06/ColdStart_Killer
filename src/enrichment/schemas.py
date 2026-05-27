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


class WebEnrichmentQuery(BaseModel):
    purpose: str
    query: str


class WebEnrichmentFact(BaseModel):
    field: str
    value: Any
    confidence: float
    source_urls: list[str] = Field(default_factory=list)


class WebEnrichmentSynthesis(BaseModel):
    enriched_description: str = ""
    key_facts: list[WebEnrichmentFact] = Field(default_factory=list)
    quality: str = "low"
    unsupported_claims: list[str] = Field(default_factory=list)


class ApplyEnrichmentPayload(BaseModel):
    fields_to_apply: list[str] = Field(default_factory=list)

