from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_environment(env_path: str | Path | None = None) -> None:
    """Load environment variables from .env if present."""
    path = Path(env_path) if env_path else DEFAULT_ENV_PATH
    load_dotenv(path if path.exists() else None)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    mongodb_db_name: str
    admin_token: str
    auth_mode: str
    seller_token: str
    auth_require_admin_for_debug: bool
    auth_require_admin_for_writes: bool
    privacy_mask_debug_data: bool
    ollama_model: str
    embedding_model: str
    use_cuda: bool
    embedding_storage_format: str
    default_index_limit: int
    m0_safe_limit: int
    dedicated_full_limit: int
    mongodb_timeout_ms: int
    vector_index_name: str
    text_index_name: str
    api_host: str
    api_port: int
    demo_mode: bool
    enable_personalization: bool
    enable_event_logging: bool
    enable_onboarding: bool
    onboarding_max_seed_items: int
    onboarding_preview_limit: int
    enable_seller_tools: bool
    seller_index_confirmation: str
    seller_draft_max_preview_units: int
    enable_web_enrichment: bool
    web_enrichment_provider: str
    tavily_api_key: str
    tavily_max_results: int
    web_enrichment_max_queries: int
    web_enrichment_timeout_seconds: int
    web_enrichment_apply_confirmation: str
    enable_query_embedding_cache: bool
    query_cache_write_enabled: bool
    query_cache_version: str
    query_cache_ttl_days: int
    enable_job_runs: bool
    enable_job_trigger_api: bool
    job_run_confirmation: str
    job_run_max_history: int
    cache_backend: str
    cache_default_ttl_seconds: int
    cache_key_version: str
    redis_url: str
    redis_socket_timeout_seconds: int
    redis_connect_timeout_seconds: int
    cache_debug_headers: bool
    algorithm_version: str
    ranking_version: str
    signal_model_version: str
    profile_model_version: str
    cf_model_version: str
    cf_runtime_input_policy: str
    explanation_version: str
    reason_min_contribution: float
    profile_reason_min_contribution: float
    signal_click_weight: float
    signal_detail_short_ms: int
    signal_detail_meaningful_ms: int
    signal_detail_short_weight: float
    signal_detail_medium_weight: float
    signal_detail_long_weight: float
    signal_wishlist_weight: float
    signal_add_to_cart_weight: float
    signal_purchase_weight: float
    signal_repeat_positive_bonus: float
    signal_repeat_positive_bonus_cap: float
    signal_preference_min_deliberate_score: float
    signal_seed_eligible_min_deliberate_score: float
    profile_exploratory_weight: float
    profile_label_max_length: int
    event_ttl_days: int
    cors_allow_origins: str


def get_settings() -> Settings:
    load_environment()
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI", ""),
        mongodb_db_name=os.getenv("MONGODB_DB_NAME", "coldstart_killer"),
        admin_token=os.getenv("ADMIN_TOKEN", ""),
        auth_mode=os.getenv("AUTH_MODE", "demo"),
        seller_token=os.getenv("SELLER_TOKEN", ""),
        auth_require_admin_for_debug=env_bool("AUTH_REQUIRE_ADMIN_FOR_DEBUG", True),
        auth_require_admin_for_writes=env_bool("AUTH_REQUIRE_ADMIN_FOR_WRITES", True),
        privacy_mask_debug_data=env_bool("PRIVACY_MASK_DEBUG_DATA", True),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        use_cuda=env_bool("USE_CUDA", True),
        embedding_storage_format=os.getenv("EMBEDDING_STORAGE_FORMAT", "list_float"),
        default_index_limit=env_int("DEFAULT_INDEX_LIMIT", 50),
        m0_safe_limit=env_int("M0_SAFE_LIMIT", 3000),
        dedicated_full_limit=env_int("DEDICATED_FULL_LIMIT", 5000),
        mongodb_timeout_ms=env_int("MONGODB_TIMEOUT_MS", 10_000),
        vector_index_name=os.getenv("VECTOR_INDEX_NAME", "vector_index"),
        text_index_name=os.getenv("TEXT_INDEX_NAME", "text_index"),
        api_host=os.getenv("API_HOST", "127.0.0.1"),
        api_port=env_int("API_PORT", 8000),
        demo_mode=env_bool("DEMO_MODE", True),
        enable_personalization=env_bool("ENABLE_PERSONALIZATION", True),
        enable_event_logging=env_bool("ENABLE_EVENT_LOGGING", True),
        enable_onboarding=env_bool("ENABLE_ONBOARDING", True),
        onboarding_max_seed_items=env_int("ONBOARDING_MAX_SEED_ITEMS", 8),
        onboarding_preview_limit=env_int("ONBOARDING_PREVIEW_LIMIT", 12),
        enable_seller_tools=env_bool("ENABLE_SELLER_TOOLS", False),
        seller_index_confirmation=os.getenv("SELLER_INDEX_CONFIRMATION", "INDEX_SELLER_DRAFT"),
        seller_draft_max_preview_units=env_int("SELLER_DRAFT_MAX_PREVIEW_UNITS", 20),
        enable_web_enrichment=env_bool("ENABLE_WEB_ENRICHMENT", False),
        web_enrichment_provider=os.getenv("WEB_ENRICHMENT_PROVIDER", "tavily"),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        tavily_max_results=env_int("TAVILY_MAX_RESULTS", 3),
        web_enrichment_max_queries=max(1, min(3, env_int("WEB_ENRICHMENT_MAX_QUERIES", 3))),
        web_enrichment_timeout_seconds=env_int("WEB_ENRICHMENT_TIMEOUT_SECONDS", 10),
        web_enrichment_apply_confirmation=os.getenv(
            "WEB_ENRICHMENT_APPLY_CONFIRMATION",
            "APPLY_WEB_ENRICHMENT",
        ),
        enable_query_embedding_cache=env_bool("ENABLE_QUERY_EMBEDDING_CACHE", False),
        query_cache_write_enabled=env_bool("QUERY_CACHE_WRITE_ENABLED", False),
        query_cache_version=os.getenv("QUERY_CACHE_VERSION", "query_cache_v1"),
        query_cache_ttl_days=env_int("QUERY_CACHE_TTL_DAYS", 0),
        enable_job_runs=env_bool("ENABLE_JOB_RUNS", True),
        enable_job_trigger_api=env_bool("ENABLE_JOB_TRIGGER_API", False),
        job_run_confirmation=os.getenv("JOB_RUN_CONFIRMATION", "RUN_JOB"),
        job_run_max_history=env_int("JOB_RUN_MAX_HISTORY", 50),
        cache_backend=os.getenv("CACHE_BACKEND", "none"),
        cache_default_ttl_seconds=env_int("CACHE_DEFAULT_TTL_SECONDS", 300),
        cache_key_version=os.getenv("CACHE_KEY_VERSION", "v1"),
        redis_url=os.getenv("REDIS_URL", ""),
        redis_socket_timeout_seconds=env_int("REDIS_SOCKET_TIMEOUT_SECONDS", 2),
        redis_connect_timeout_seconds=env_int("REDIS_CONNECT_TIMEOUT_SECONDS", 2),
        cache_debug_headers=env_bool("CACHE_DEBUG_HEADERS", False),
        algorithm_version=os.getenv("ALGORITHM_VERSION", "rec_v2_negative_suppression_seed_guard"),
        ranking_version=os.getenv("RANKING_VERSION", "rank_v1_default_weights"),
        signal_model_version=os.getenv("SIGNAL_MODEL_VERSION", "signal_v4_boundary_hygiene"),
        profile_model_version=os.getenv("PROFILE_MODEL_VERSION", "profile_v4_negative_guard"),
        cf_model_version=os.getenv("CF_MODEL_VERSION", "cf_v1_supported_edges"),
        cf_runtime_input_policy=os.getenv("CF_RUNTIME_INPUT_POLICY", "current_supported"),
        explanation_version=os.getenv("EXPLANATION_VERSION", "explain_v3_contribution_faithful"),
        reason_min_contribution=env_float("REASON_MIN_CONTRIBUTION", 0.05),
        profile_reason_min_contribution=env_float("PROFILE_REASON_MIN_CONTRIBUTION", 0.05),
        signal_click_weight=env_float("SIGNAL_CLICK_WEIGHT", 0.35),
        signal_detail_short_ms=env_int("SIGNAL_DETAIL_SHORT_MS", 5_000),
        signal_detail_meaningful_ms=env_int("SIGNAL_DETAIL_MEANINGFUL_MS", 20_000),
        signal_detail_short_weight=env_float("SIGNAL_DETAIL_SHORT_WEIGHT", 0.10),
        signal_detail_medium_weight=env_float("SIGNAL_DETAIL_MEDIUM_WEIGHT", 0.50),
        signal_detail_long_weight=env_float("SIGNAL_DETAIL_LONG_WEIGHT", 1.25),
        signal_wishlist_weight=env_float("SIGNAL_WISHLIST_WEIGHT", 2.50),
        signal_add_to_cart_weight=env_float("SIGNAL_ADD_TO_CART_WEIGHT", 4.00),
        signal_purchase_weight=env_float("SIGNAL_PURCHASE_WEIGHT", 7.00),
        signal_repeat_positive_bonus=env_float("SIGNAL_REPEAT_POSITIVE_BONUS", 0.25),
        signal_repeat_positive_bonus_cap=env_float("SIGNAL_REPEAT_POSITIVE_BONUS_CAP", 1.50),
        signal_preference_min_deliberate_score=env_float("SIGNAL_PREFERENCE_MIN_DELIBERATE_SCORE", 0.50),
        signal_seed_eligible_min_deliberate_score=env_float("SIGNAL_SEED_ELIGIBLE_MIN_DELIBERATE_SCORE", 0.75),
        profile_exploratory_weight=env_float("PROFILE_EXPLORATORY_WEIGHT", 0.25),
        profile_label_max_length=env_int("PROFILE_LABEL_MAX_LENGTH", 80),
        event_ttl_days=env_int("EVENT_TTL_DAYS", 0),
        cors_allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173"),
    )


def configured_model_versions(settings: Settings | None = None) -> dict[str, str]:
    active_settings = settings or get_settings()
    return {
        "signal_model_version": active_settings.signal_model_version,
        "profile_model_version": active_settings.profile_model_version,
        "cf_model_version": active_settings.cf_model_version,
        "explanation_version": active_settings.explanation_version,
    }


def require_mongodb_uri() -> str:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError(
            "MONGODB_URI is missing. Copy .env.example to .env and fill your Atlas connection string."
        )
    return settings.mongodb_uri

