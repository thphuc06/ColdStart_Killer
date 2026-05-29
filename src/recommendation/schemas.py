from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.schemas import DerivationMetadata
from src.utils import utc_now_iso


EMBEDDING_DIM = 1024


def _non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validate_embedding(value: list[float], field_name: str) -> list[float]:
    if len(value) != EMBEDDING_DIM:
        raise ValueError(f"{field_name} must contain {EMBEDDING_DIM} floats")
    try:
        finite = all(math.isfinite(float(item)) for item in value)
    except (TypeError, ValueError):
        finite = False
    if not finite:
        raise ValueError(f"{field_name} contains NaN, Inf, or non-numeric values")
    return [float(item) for item in value]


class ItemHypeProfileDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    item_id: str
    item_semantic_embedding: list[float]
    top_hype_unit_ids: list[str] = Field(default_factory=list)
    top_aspects: list[str] = Field(default_factory=list)
    num_hype_units: int = 0
    category_id: str = ""
    price_bucket: str = "unknown"
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        return _non_empty(value, "item_id")

    @field_validator("item_semantic_embedding")
    @classmethod
    def validate_item_embedding(cls, value: list[float]) -> list[float]:
        return _validate_embedding(value, "item_semantic_embedding")


class SemanticNeighbor(BaseModel):
    neighbor_item_id: str
    neighbor_score: float
    matched_unit_ids: list[str] = Field(default_factory=list)
    matched_aspects: list[str] = Field(default_factory=list)
    source: str = "hype_unit_vector_search"

    @field_validator("neighbor_item_id")
    @classmethod
    def validate_neighbor_item_id(cls, value: str) -> str:
        return _non_empty(value, "neighbor_item_id")


class ItemSemanticNeighborsDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    item_id: str
    neighbors: list[SemanticNeighbor] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        return _non_empty(value, "item_id")


class ItemItemCFEdgeDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    item_id: str
    neighbor_item_id: str
    cf_score: float = 0.0
    co_view_count: int = 0
    co_click_count: int = 0
    co_cart_count: int = 0
    co_purchase_count: int = 0
    support: int = 0
    confidence: float = 0.0
    top_common_user_hashes_sample: list[str] = Field(default_factory=list)
    explanation: str = "Users who interacted with this item also interacted with this recommendation."
    derivation: DerivationMetadata = Field(default_factory=DerivationMetadata)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("item_id", "neighbor_item_id")
    @classmethod
    def validate_item_ids(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)


class ItemStatsColdStart(BaseModel):
    is_cold_item: bool = True
    interaction_count: int = 0
    age_days: int | None = None


class ItemStatsDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    item_id: str
    impression_count: int = 0
    click_count: int = 0
    view_detail_count: int = 0
    add_to_cart_count: int = 0
    purchase_count: int = 0
    hide_count: int = 0
    dislike_count: int = 0
    ctr: float = 0.0
    cart_rate: float = 0.0
    purchase_rate: float = 0.0
    first_seen_at: str | None = None
    last_interaction_at: str | None = None
    cold_start: ItemStatsColdStart = Field(default_factory=ItemStatsColdStart)
    quality_score: float = 0.0
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        return _non_empty(value, "item_id")


class QueryEmbeddingCacheDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    query_hash: str
    raw_query: str
    normalized_query: str = ""
    english_query: str
    embedding: list[float]
    processed_query: dict[str, Any] | None = None
    embedding_model: str
    vector_index_name: str = "vector_index"
    text_index_name: str = "text_index"
    query_cache_version: str = "query_cache_v1"
    algorithm_version: str = ""
    ranking_version: str = ""
    created_at: str = Field(default_factory=utc_now_iso)
    last_used_at: str = Field(default_factory=utc_now_iso)
    usage_count: int = 1

    model_config = {"populate_by_name": True}

    @field_validator("query_hash", "raw_query", "english_query", "embedding_model")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)

    @field_validator("embedding")
    @classmethod
    def validate_query_embedding(cls, value: list[float]) -> list[float]:
        return _validate_embedding(value, "embedding")


class SyntheticPersonaDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    persona_id: str
    label: str
    preferred_categories: dict[str, float] = Field(default_factory=dict)
    preferred_price_buckets: dict[str, float] = Field(default_factory=dict)
    brand_bias: dict[str, float] = Field(default_factory=dict)
    intent_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    intent_embedding: list[float] | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("persona_id", "label")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)

    @field_validator("intent_embedding")
    @classmethod
    def validate_optional_intent_embedding(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        return _validate_embedding(value, "intent_embedding")


class EvaluationRunDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    run_id: str
    run_type: str = "personalization_eval"
    algorithm_version: str
    ranking_version: str
    data_label: str = "synthetic_demo"
    synthetic_data: bool = True
    evaluation_data_mode: str = "synthetic_demo"
    metrics: dict[str, Any] = Field(default_factory=dict)
    baseline_summaries: list[dict[str, Any]] = Field(default_factory=list)
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    live_state_counts: dict[str, int] = Field(default_factory=dict)
    caveat: str = "Synthetic/demo behavior data, not production traffic."
    evaluated_user_count: int = 0
    artifacts: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("run_id", "run_type", "algorithm_version", "ranking_version", "data_label", "evaluation_data_mode", "caveat")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)
