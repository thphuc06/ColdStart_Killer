from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from src.utils import utc_now_iso


class TextStats(BaseModel):
    title_words: int = 0
    description_words: int = 0
    features_words: int = 0
    details_words: int = 0
    combined_words: int = 0


class ColdStartState(BaseModel):
    is_cold_item: bool = True
    interaction_count: int = 0
    rating_number_eval_only: int | None = None


class DescriptionEnriched(BaseModel):
    source: str = "amazon_metadata"
    enrichment_quality: str = "high"
    seller_confirmed: bool = False
    key_facts: list[dict[str, Any]] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    enrichment_note: str = ""


class SourceText(BaseModel):
    description_text: str = ""
    features_text: str = ""
    details_text: str = ""


class DerivationMetadata(BaseModel):
    model_version: str = ""
    source_collection: str = ""
    source_event_max_timestamp: str | None = None
    source_event_count: int | None = None
    source_signal_model_version: str | None = None
    source_signal_count: int | None = None
    source_signal_built_at: str | None = None
    input_policy: str | None = None
    partial_build: bool = False
    built_at: str = Field(default_factory=utc_now_iso)


class ItemDocument(BaseModel):
    id: str = Field(alias="_id")
    raw_parent_asin: str
    source_dataset: str = "Amazon Reviews 2023"
    source_file: str = "analysis/mvp_3000_items_diverse.csv"
    source_category: str
    title_en: str
    title_vi: str = ""
    brand: str = ""
    brand_source: str = "none"
    category_id: str
    category_path: list[str] = Field(default_factory=list)
    raw_main_category: str
    price_usd: float | None = None
    price_vnd: int | None = None
    price_parse_status: str = "missing"
    price_bucket: str = "unknown"
    in_stock: bool = True
    image_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    content_richness: float = 0.0
    quality_score: float = 0.0
    quality_tier: str = "tier_D"
    product_text_for_llm: str
    source_text: SourceText = Field(default_factory=SourceText)
    text_stats: TextStats
    cold_start: ColdStartState = Field(default_factory=ColdStartState)
    description_enriched: DescriptionEnriched = Field(default_factory=DescriptionEnriched)
    created_at: str
    updated_at: str

    model_config = {"populate_by_name": True}


class RetrievalUnitBase(BaseModel):
    id: str = Field(alias="_id")
    item_id: str
    unit_type: Literal["hype_question", "proposition"]
    language: Literal["en"] = "en"
    raw_text: str
    confidence: float = 0.0
    source: str = "llm"
    category_id: str
    price_vnd: int | None = None
    price_bucket: str = "unknown"
    in_stock: bool = True
    is_cold_item: bool = True
    seller_confirmed: bool = False
    generation_model: str
    generation_prompt_version: str

    model_config = {"populate_by_name": True}


class HypeRetrievalUnit(RetrievalUnitBase):
    unit_type: Literal["hype_question"] = "hype_question"
    aspect: str
    embedding_text: str
    embedding: list[float]


class PropositionRetrievalUnit(RetrievalUnitBase):
    unit_type: Literal["proposition"] = "proposition"
    proposition_type: str
    text_search: str
    item_title_en: str
    item_brand: str
    source_field: str = "mixed"


def to_mongo_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(by_alias=True, exclude_none=True)
    return model.dict(by_alias=True, exclude_none=True)
