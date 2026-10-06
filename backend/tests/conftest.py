from collections.abc import Iterator

import pytest

from text2sql.config.settings import Settings, get_settings

# Obviously fake values: tests must never depend on a real .env.
FAKE_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": "postgresql+asyncpg://user:pw@localhost:5432/test",
    "REDIS_URL": "redis://:pw@localhost:6379/0",
    "READER_DATABASE_URL": "postgresql+asyncpg://t2s_reader:pw@localhost:5432/test",
    "APP_DATABASE_URL": "postgresql+asyncpg://t2s_app:pw@localhost:5432/test",
    "OPENAI_API_KEY": "sk-test-not-a-real-key",
    "LLM_MODEL_MAIN": "openai/gpt-5.4",
    "LLM_MODEL_FAST": "openai/gpt-5.4-mini",
    "LLM_MODEL_LOCAL": "ollama_chat/qwen2.5-coder:7b",
    "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
    "LANGFUSE_SECRET_KEY": "sk-lf-test",
    "LANGFUSE_HOST": "https://langfuse.example.com",
}


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield FAKE_ENV
    get_settings.cache_clear()


@pytest.fixture
def settings(fake_env: dict[str, str]) -> Settings:
    del fake_env
    return Settings(_env_file=None)
