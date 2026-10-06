"""Typed application settings, read exclusively from the environment."""

from functools import lru_cache
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

    # Database (secret: contains credentials)
    database_url: SecretStr

    # Cache (secret: contains the password)
    redis_url: SecretStr

    # LLM
    openai_api_key: SecretStr
    openai_model: str = "gpt-4o-mini"

    # Observability
    langfuse_public_key: SecretStr
    langfuse_secret_key: SecretStr
    langfuse_host: AnyHttpUrl


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return Settings()
