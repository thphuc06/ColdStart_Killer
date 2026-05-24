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


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str
    mongodb_db_name: str
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
    algorithm_version: str
    ranking_version: str
    event_ttl_days: int
    cors_allow_origins: str


def get_settings() -> Settings:
    load_environment()
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI", ""),
        mongodb_db_name=os.getenv("MONGODB_DB_NAME", "coldstart_killer"),
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
        algorithm_version=os.getenv("ALGORITHM_VERSION", "rec_v1_profile_cf_hype"),
        ranking_version=os.getenv("RANKING_VERSION", "rank_v1_default_weights"),
        event_ttl_days=env_int("EVENT_TTL_DAYS", 0),
        cors_allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173"),
    )


def require_mongodb_uri() -> str:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError(
            "MONGODB_URI is missing. Copy .env.example to .env and fill your Atlas connection string."
        )
    return settings.mongodb_uri

