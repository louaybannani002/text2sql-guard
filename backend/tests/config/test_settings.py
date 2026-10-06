import pytest
from pydantic import ValidationError

from text2sql.config.settings import Settings

SECRET_VARS = [
    "DATABASE_URL",
    "REDIS_URL",
    "READER_DATABASE_URL",
    "APP_DATABASE_URL",
    "OPENAI_API_KEY",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
]


def test_loads_from_env(settings: Settings) -> None:
    assert settings.app_env == "test"
    assert settings.openai_api_key.get_secret_value() == "sk-test-not-a-real-key"
    assert str(settings.langfuse_host).startswith("https://langfuse.example.com")


def test_secrets_are_masked_in_repr(settings: Settings) -> None:
    rendered = repr(settings)
    assert "sk-test-not-a-real-key" not in rendered
    assert "sk-lf-test" not in rendered


@pytest.mark.parametrize("var", SECRET_VARS)
def test_secret_has_no_default(
    var: str, fake_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    del fake_env
    monkeypatch.delenv(var)
    with pytest.raises(ValidationError, match=var.lower()):
        Settings(_env_file=None)


def test_is_immutable(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]


def test_rejects_invalid_port(fake_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    del fake_env
    monkeypatch.setenv("API_PORT", "70000")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
