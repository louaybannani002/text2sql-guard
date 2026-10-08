import pytest
from pydantic import SecretStr

from text2sql.config.hosts import with_host
from text2sql.config.settings import Settings


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+asyncpg://t2s_reader:p%40ss:w@127.0.0.1:5432/text2sql",
            "postgresql+asyncpg://t2s_reader:p%40ss:w@postgres:5432/text2sql",
        ),
        ("redis://:secret@127.0.0.1:6379/0", "redis://:secret@redis:6379/0"),
        ("redis://127.0.0.1:6379/0", "redis://redis:6379/0"),
    ],
)
def test_with_host_keeps_credentials_and_path(url: str, expected: str) -> None:
    host = "redis:6379" if url.startswith("redis") else "postgres:5432"
    assert with_host(SecretStr(url), host).get_secret_value() == expected


@pytest.mark.usefixtures("fake_env")
def test_settings_rewrite_every_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_HOST", "postgres:5432")
    monkeypatch.setenv("REDIS_HOST", "redis:6379")
    settings = Settings(_env_file=None)
    for url in (settings.database_url, settings.reader_database_url, settings.app_database_url):
        assert "@postgres:5432/" in url.get_secret_value()
    assert "@redis:6379/" in settings.redis_url.get_secret_value()
    assert settings.model_copy().database_url == settings.database_url  # applied once


def test_without_overrides_urls_are_untouched(settings: Settings, fake_env: dict[str, str]) -> None:
    assert settings.database_url.get_secret_value() == fake_env["DATABASE_URL"]
