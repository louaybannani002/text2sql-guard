"""Typed application settings, read exclusively from the environment."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

type AppEnv = Literal["development", "test", "staging", "production"]
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """All runtime configuration.

    Secrets are ``SecretStr`` and have no default: startup fails fast if any is missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # App
    app_env: AppEnv = "development"
    log_level: LogLevel = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    # Database (secrets: contain credentials)
    # Admin connection: migrations and data loading only, never request handling.
    database_url: SecretStr
    # Least-privilege roles (migration 0004); their passwords are synced from these URLs.
    reader_database_url: SecretStr  # t2s_reader: runs LLM-generated SQL
    app_database_url: SecretStr  # t2s_app: read/write on schema app
    migrations_dir: Path = Path("db/migrations")
    raw_data_dir: Path = Path("data/raw")
    examples_seed_path: Path = Path("db/seeds/examples.toml")

    # Cache (secret: contains the password)
    redis_url: SecretStr

    # LLM
    openai_api_key: SecretStr
    # LiteLLM model names per role ("provider/model"); swap models via env, not code.
    llm_model_main: str
    llm_model_fast: str
    llm_model_local: str
    llm_embedding_model: str  # its dimension must match app.*.embedding (1536)
    llm_local_api_base: str | None = None  # e.g. http://127.0.0.1:11434 for Ollama
    llm_timeout_s: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    # Observability
    langfuse_public_key: SecretStr
    langfuse_secret_key: SecretStr
    langfuse_host: AnyHttpUrl


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()
