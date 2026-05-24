from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.recommendation.schemas import EMBEDDING_DIM
from src.utils import utc_now_iso


ProfileStatus = Literal["new", "onboarded", "warming", "warm"]
RecommendationSurface = Literal["search", "home", "detail_similar", "seller_preview"]
EventSurface = Literal["search", "home", "detail_similar", "cart", "onboarding", "debug"]
EventType = Literal[
    "impression",
    "click",
    "view_detail",
    "add_to_cart",
    "purchase",
    "hide",
    "dislike",
    "wishlist",
]


def _non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _validate_optional_embedding(value: list[float] | None, field_name: str) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != EMBEDDING_DIM:
        raise ValueError(f"{field_name} must be a {EMBEDDING_DIM}-dimensional embedding")
    normalized = [float(item) for item in value]
    if not all(math.isfinite(item) for item in normalized):
        raise ValueError(f"{field_name} must contain only finite values")
    return normalized


class PrivacySettings(BaseModel):
    allow_personalization: bool = True
    allow_clickstream_logging: bool = True


class OnboardingState(BaseModel):
    completed: bool = False
    completed_at: str | None = None
    selected_categories: list[str] = Field(default_factory=list)
    selected_price_buckets: list[str] = Field(default_factory=list)
    selected_seed_item_ids: list[str] = Field(default_factory=list)


class UserDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    user_id_hash: str
    created_at: str = Field(default_factory=utc_now_iso)
    profile_status: ProfileStatus = "new"
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    onboarding: OnboardingState = Field(default_factory=OnboardingState)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("user_id_hash")
    @classmethod
    def validate_user_id_hash(cls, value: str) -> str:
        return _non_empty(value, "user_id_hash")


class SessionDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    session_id: str
    user_id_hash: str
    started_at: str = Field(default_factory=utc_now_iso)
    ended_at: str | None = None
    locale: Literal["vi", "en"] = "en"
    device_type: Literal["desktop", "mobile", "unknown"] = "unknown"
    entry_source: Literal["home", "search", "direct", "demo"] = "demo"
    active_surface: Literal["home", "search", "detail", "debug"] = "home"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("session_id", "user_id_hash")
    @classmethod
    def validate_non_empty_ids(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)


class RecommendationQueryContext(BaseModel):
    raw_query: str = ""
    english_query: str = ""
    query_type: Literal["specific", "constraint_rich", "normal", "broad", "exploratory", "none"] = "none"
    query_embedding_hash: str | None = None
    query_embedding: list[float] | None = None

    @field_validator("query_embedding")
    @classmethod
    def validate_query_embedding(cls, value: list[float] | None) -> list[float] | None:
        return _validate_optional_embedding(value, "query_embedding")


class RecommendationScores(BaseModel):
    query_hybrid_score: float = 0.0
    profile_score: float = 0.0
    semantic_neighbor_score: float = 0.0
    item_item_cf_score: float = 0.0
    category_affinity_score: float = 0.0
    brand_affinity_score: float = 0.0
    price_affinity_score: float = 0.0
    cold_start_boost: float = 0.0
    exploration_score: float = 0.0
    seen_penalty: float = 0.0
    negative_penalty: float = 0.0
    diversity_adjustment: float = 0.0
    final_score: float = 0.0


class CFEvidence(BaseModel):
    source_item_id: str | None = None
    support: int = 0
    cf_score: float = 0.0
    co_click_count: int = 0
    co_cart_count: int = 0


class RecommendationAttribution(BaseModel):
    matched_unit_ids: list[str] = Field(default_factory=list)
    matched_intents: list[str] = Field(default_factory=list)
    matched_facts: list[str] = Field(default_factory=list)
    matched_channels: list[str] = Field(default_factory=list)
    candidate_sources: list[str] = Field(default_factory=list)
    matched_profile_interest_ids: list[str] = Field(default_factory=list)
    matched_interest_embedding: list[float] | None = None
    matched_neighbor_embedding: list[float] | None = None
    cf_evidence: CFEvidence | None = None
    explanation: str = ""

    @field_validator("matched_interest_embedding", "matched_neighbor_embedding")
    @classmethod
    def validate_attribution_embedding(cls, value: list[float] | None, info) -> list[float] | None:
        return _validate_optional_embedding(value, info.field_name)


class RecommendationLogDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    request_id: str
    surface: RecommendationSurface
    user_id_hash: str
    session_id: str
    algorithm_version: str
    ranking_version: str
    query: RecommendationQueryContext = Field(default_factory=RecommendationQueryContext)
    item_id: str
    rank_position: int
    scores: RecommendationScores = Field(default_factory=RecommendationScores)
    attribution: RecommendationAttribution = Field(default_factory=RecommendationAttribution)
    is_synthetic: bool = False
    shown_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("request_id", "user_id_hash", "session_id", "algorithm_version", "ranking_version", "item_id")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)


class ClickstreamClient(BaseModel):
    component: str = ""
    device_type: Literal["desktop", "mobile", "unknown"] = "unknown"


class ClickstreamEventDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    event_id: str
    idempotency_key: str | None = None
    request_id: str | None = None
    user_id_hash: str
    session_id: str
    surface: EventSurface
    event_type: EventType
    item_id: str
    query_text: str = ""
    rank_position: int | None = None
    dwell_time_ms: int | None = None
    is_synthetic: bool = False
    client: ClickstreamClient = Field(default_factory=ClickstreamClient)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now_iso)
    processed: bool = False
    created_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("event_id", "user_id_hash", "session_id", "item_id")
    @classmethod
    def validate_event_text(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)


class UserItemSignalKey(BaseModel):
    user_id_hash: str
    item_id: str


class EventCounts(BaseModel):
    impression: int = 0
    click: int = 0
    view_detail: int = 0
    add_to_cart: int = 0
    purchase: int = 0
    wishlist: int = 0
    hide: int = 0
    dislike: int = 0


class ReasonScore(BaseModel):
    intent: str = ""
    score: float = 0.0
    source: str = ""
    last_seen_at: str | None = None


class UserItemSignalDocument(BaseModel):
    id: UserItemSignalKey | None = Field(default=None, alias="_id")
    user_id_hash: str
    item_id: str
    implicit_score: float = 0.0
    confidence: float = 0.0
    positive_score: float = 0.0
    negative_score: float = 0.0
    preference: bool = False
    event_counts: EventCounts = Field(default_factory=EventCounts)
    reason_scores: list[ReasonScore] = Field(default_factory=list)
    last_interaction_at: str | None = None
    first_interaction_at: str | None = None
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("user_id_hash", "item_id")
    @classmethod
    def validate_signal_text(cls, value: str, info) -> str:
        return _non_empty(value, info.field_name)


class ProfileQuality(BaseModel):
    num_events: int = 0
    num_positive_items: int = 0
    num_purchases: int = 0
    num_categories: int = 0
    confidence: float = 0.0


class ExplicitPrefs(BaseModel):
    source: Literal["none", "onboarding"] = "none"
    categories: list[str] = Field(default_factory=list)
    price_buckets: list[str] = Field(default_factory=list)
    seed_item_ids: list[str] = Field(default_factory=list)


class PriceAffinity(BaseModel):
    preferred_buckets: dict[str, float] = Field(default_factory=dict)
    median_clicked_price: int | None = None
    median_cart_price: int | None = None
    median_purchased_price: int | None = None


class IntentAffinity(BaseModel):
    intent: str
    score: float = 0.0
    source: str = ""
    last_seen_at: str | None = None


class InterestEvidence(BaseModel):
    click: int = 0
    view_detail: int = 0
    add_to_cart: int = 0
    purchase: int = 0


class InterestVector(BaseModel):
    interest_id: str
    label: str = ""
    embedding: list[float]
    weight: float = 0.0
    categories: list[str] = Field(default_factory=list)
    top_intents: list[str] = Field(default_factory=list)
    evidence: InterestEvidence = Field(default_factory=InterestEvidence)
    top_item_ids: list[str] = Field(default_factory=list)
    last_updated_at: str = Field(default_factory=utc_now_iso)

    @field_validator("interest_id")
    @classmethod
    def validate_interest_id(cls, value: str) -> str:
        return _non_empty(value, "interest_id")


class NegativePreferences(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    brands: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)


class UserProfileDocument(BaseModel):
    id: str | None = Field(default=None, alias="_id")
    user_id_hash: str
    profile_status: ProfileStatus = "new"
    profile_quality: ProfileQuality = Field(default_factory=ProfileQuality)
    explicit_prefs: ExplicitPrefs = Field(default_factory=ExplicitPrefs)
    category_affinity: dict[str, float] = Field(default_factory=dict)
    brand_affinity: dict[str, float] = Field(default_factory=dict)
    price_affinity: PriceAffinity = Field(default_factory=PriceAffinity)
    intent_affinity: list[IntentAffinity] = Field(default_factory=list)
    short_term_embedding: list[float] = Field(default_factory=list)
    long_term_embedding: list[float] = Field(default_factory=list)
    interest_vectors: list[InterestVector] = Field(default_factory=list)
    negative_preferences: NegativePreferences = Field(default_factory=NegativePreferences)
    recent_item_ids: list[str] = Field(default_factory=list)
    purchased_item_ids: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=utc_now_iso)

    model_config = {"populate_by_name": True}

    @field_validator("user_id_hash")
    @classmethod
    def validate_profile_user(cls, value: str) -> str:
        return _non_empty(value, "user_id_hash")
