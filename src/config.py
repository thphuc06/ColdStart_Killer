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
    brave_api_key: str
    embedding_model: str
    use_cuda: bool
    embedding_storage_format: str
    default_index_limit: int
    m0_safe_limit: int
    dedicated_full_limit: int
    mongodb_timeout_ms: int


def get_settings() -> Settings:
    load_environment()
    return Settings(
        mongodb_uri=os.getenv("MONGODB_URI", ""),
        mongodb_db_name=os.getenv("MONGODB_DB_NAME", "coldstart_killer"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        brave_api_key=os.getenv("BRAVE_API_KEY", ""),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        use_cuda=env_bool("USE_CUDA", True),
        embedding_storage_format=os.getenv("EMBEDDING_STORAGE_FORMAT", "list_float"),
        default_index_limit=env_int("DEFAULT_INDEX_LIMIT", 50),
        m0_safe_limit=env_int("M0_SAFE_LIMIT", 3000),
        dedicated_full_limit=env_int("DEDICATED_FULL_LIMIT", 5000),
        mongodb_timeout_ms=env_int("MONGODB_TIMEOUT_MS", 10_000),
    )


def require_mongodb_uri() -> str:
    settings = get_settings()
    if not settings.mongodb_uri:
        raise RuntimeError(
            "MONGODB_URI is missing. Copy .env.example to .env and fill your Atlas connection string."
        )
    return settings.mongodb_uri

